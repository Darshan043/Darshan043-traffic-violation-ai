"""Explicit opt-in integration checks against a throwaway Mongo database."""
from __future__ import annotations

import asyncio
import csv
from datetime import timedelta
import io
import uuid
import os
from datetime import datetime, timezone

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError, PyMongoError

from backend.app.core.config import settings
from backend.app.db.mongo import MongoDatabase
from backend.app.db.mongo_repo import MongoRepository
from backend.app.models.event import VehicleEvent
from backend.app.models.camera import Camera
from backend.app.models.user import User
from backend.app.models.violation import Violation
from backend.app.db.json_repo import JsonFileRepository
from scripts.migrate_json_to_mongo import migrate
from mongo_test_guard import (
    cleanup_test_collections,
    is_safe_test_database_name,
    new_test_database_name,
    validate_test_mongo_url,
    verify_fresh_test_database,
)

pytestmark = pytest.mark.mongo


async def _verify_database_is_fresh(test_url: str, test_database: str) -> None:
    client = AsyncMongoClient(
        test_url,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        tz_aware=True,
    )
    try:
        await verify_fresh_test_database(client[test_database], test_database)
    finally:
        await client.close()


async def _cleanup_with_client(test_url: str, test_database: str) -> None:
    client = AsyncMongoClient(
        test_url,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        tz_aware=True,
    )
    try:
        await cleanup_test_collections(client[test_database], test_database)
    finally:
        await client.close()


@pytest.fixture(scope="module")
def mongo_repo():
    try:
        test_url = validate_test_mongo_url(
            os.environ.get("MONGO_TEST_URL"),
            settings.MONGO_URL,
        )
    except ValueError as error:
        pytest.fail(str(error))
    configured_prefix = os.environ.get("MONGO_TEST_DB")
    if not configured_prefix:
        pytest.fail("MONGO_TEST_DB must be explicitly set to traffic_ai_test")
    if os.environ.get("MONGO_TEST_ISOLATED") != "1":
        pytest.fail(
            "Set MONGO_TEST_ISOLATED=1 only after confirming this is an isolated test deployment"
        )
    try:
        test_database = new_test_database_name(configured_prefix)
    except ValueError as error:
        pytest.fail(str(error))
    if not is_safe_test_database_name(test_database):
        pytest.fail("Refusing to use a database outside the strict test-only naming policy")
    try:
        asyncio.run(_verify_database_is_fresh(test_url, test_database))
    except PyMongoError as error:
        pytest.fail(f"Mongo test database freshness check failed ({type(error).__name__})")
    except ValueError as error:
        pytest.fail(str(error))

    mongo = None
    try:
        mongo = MongoDatabase(
            test_url,
            test_database,
            operation_timeout_seconds=settings.MONGO_OPERATION_TIMEOUT_SECONDS,
        )
        repo = MongoRepository(mongo=mongo)
    except Exception as error:
        try:
            if mongo is not None:
                mongo.run(cleanup_test_collections(mongo.database, test_database))
            else:
                asyncio.run(_cleanup_with_client(test_url, test_database))
        except Exception as cleanup_error:
            pytest.fail(
                f"Mongo integration setup failed ({type(error).__name__}); "
                f"test cleanup failed ({type(cleanup_error).__name__})"
            )
        finally:
            if mongo is not None:
                mongo.close()
        pytest.fail(f"Mongo integration connection failed ({type(error).__name__})")
    try:
        yield repo
    finally:
        try:
            mongo.run(cleanup_test_collections(mongo.database, test_database))
        finally:
            mongo.close()


def _event(event_id: str, result: str, track_id: int = 1) -> VehicleEvent:
    decision, ai_result, vtype = {
        "HELMET": ("COMPLIANCE", "helmet", "helmet"),
        "NO_HELMET": ("VIOLATION", "no_helmet", "helmet"),
        "NEEDS_REVIEW": ("NEEDS_REVIEW", "unclear", "helmet"),
        "SEATBELT": ("COMPLIANCE", "seatbelt", "seatbelt"),
        "NO_SEATBELT": ("VIOLATION", "no_seatbelt", "seatbelt"),
        "NOT_CHECKED": ("NOT_CHECKED", "unclear", "helmet"),
    }[result]
    return VehicleEvent(
        event_id=event_id,
        run_id=f"run-{event_id}",
        camera_id="camera-test",
        track_id=track_id,
        vehicle_type="motorcycle",
        violation_type=vtype,
        decision=decision,
        ai_result=ai_result,
        confidence=0.9,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _save_event_with_violation(repository, event: VehicleEvent) -> VehicleEvent:
    """Mirror the application flow: event first, then one explicit violation save."""
    saved = repository.save_vehicle_event(event)
    if saved.result in {"NO_HELMET", "NO_SEATBELT", "NEEDS_REVIEW"}:
        pending = saved.result == "NEEDS_REVIEW"
        repository.save_violation(Violation(
            event_id=saved.event_id,
            camera_id=saved.camera_id,
            track_id=saved.track_id,
            violation_type=saved.violation_type,
            ai_result=saved.ai_result,
            detection_confidence=saved.confidence,
            reason_code=saved.reason,
            evidence=saved.evidence,
            review_status="pending" if pending else "not_required",
            final_decision="PENDING" if pending else "CONFIRMED_VIOLATION",
            created_at=saved.created_at,
        ))
    return saved


def test_required_indexes_exist(mongo_repo):
    names = {
        collection: mongo_repo._run(mongo_repo.db[collection].index_information())
        for collection in ("users", "cameras", "vehicle_events", "violations", "system_settings")
    }
    for collection, index in {
        "users": "users_username_unique",
        "cameras": "cameras_camera_id_unique",
        "vehicle_events": "vehicle_events_event_id_unique",
        "violations": "violations_event_id_unique",
        "system_settings": "system_settings_key_unique",
    }.items():
        assert index in names[collection]
    assert "violations_review_status" in names["violations"]
    assert "violations_camera_created_at" in names["violations"]
    assert "violations_violation_type" in names["violations"]
    assert "violations_track_id" in names["violations"]
    assert "vehicle_events_camera_timestamp" in names["vehicle_events"]


def test_duplicate_event_id_is_rejected(mongo_repo):
    event = _event(f"duplicate-{uuid.uuid4().hex}", "HELMET")
    mongo_repo.save_event(event)
    doc = mongo_repo._event_doc(event)
    with pytest.raises(DuplicateKeyError):
        mongo_repo._run(mongo_repo.db.vehicle_events.insert_one(doc))


def test_run_id_makes_repeated_event_ids_unique(mongo_repo):
    event = _event("same-pipeline-event", "HELMET")
    first = mongo_repo.save_event(event.model_copy(update={"run_id": "run-one"}))
    second = mongo_repo.save_event(event.model_copy(update={"run_id": "run-two"}))

    assert first.event_id != second.event_id
    assert first.event_id.startswith("run-one_")
    assert second.event_id.startswith("run-two_")


def test_filters_pagination_and_review_preserve_ai_result(mongo_repo):
    prefix = uuid.uuid4().hex
    saved_events = []
    for index, result in enumerate(("NO_HELMET", "NEEDS_REVIEW", "NO_HELMET")):
        saved_events.append(_save_event_with_violation(
            mongo_repo, _event(f"{prefix}-{index}", result, track_id=index)
        ))
    page, total = mongo_repo.list_violations(camera_id="camera-test", page=1, limit=1)
    assert total >= 3
    assert len(page) == 1
    pending, _ = mongo_repo.list_violations(review_status="pending", limit=20)
    assert any(item.event_id == saved_events[1].event_id for item in pending)
    original = mongo_repo.get_violation(saved_events[0].event_id)
    reviewed = mongo_repo.update_violation(original.event_id, {
        "review_status": "REVIEWED",
        "final_decision": "DISMISSED",
        "reviewed_by": "reviewer-test",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_note": "test review",
    })
    assert reviewed.ai_result == "no_helmet"
    assert reviewed.review_history
    seatbelt_id = f"{prefix}-seatbelt"
    seatbelt_event = _save_event_with_violation(
        mongo_repo, _event(seatbelt_id, "NO_SEATBELT", track_id=88)
    )
    helmets, helmet_total = mongo_repo.list_violations(ai_result="NO_HELMET", limit=50)
    seatbelts, seatbelt_total = mongo_repo.list_violations(
        violation_type="seatbelt", track_id=88, limit=50
    )
    assert helmet_total >= 2
    assert all(item.ai_result == "no_helmet" for item in helmets)
    assert any(item.event_id == seatbelt_event.event_id for item in seatbelts)
    old_date, _ = mongo_repo.list_violations(
        date_to=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat(), limit=50
    )
    saved_ids = {item.event_id for item in saved_events} | {seatbelt_event.event_id}
    assert not any(item.event_id in saved_ids for item in old_date)


def test_summary_fixture_numbers(mongo_repo):
    prefix = uuid.uuid4().hex
    mongo_repo._run(mongo_repo.db.vehicle_events.delete_many({}))
    mongo_repo._run(mongo_repo.db.violations.delete_many({}))
    for index in range(6):
        mongo_repo.save_event(_event(f"{prefix}-helmet-{index}", "HELMET"))
    for index in range(2):
        mongo_repo.save_event(_event(f"{prefix}-nohelmet-{index}", "NO_HELMET"))
        mongo_repo.save_event(_event(f"{prefix}-review-{index}", "NEEDS_REVIEW"))
    summary = mongo_repo.get_stats_summary()
    assert summary["total_vehicles"] == 10
    assert summary["helmet_compliance_percentage"] == 75.0
    assert summary["review_count"] == 2


def test_object_id_and_utc_datetime_serialization(mongo_repo):
    user = User(
        id=str(ObjectId()), username=f"mongo-{uuid.uuid4().hex[:8]}",
        hashed_password="hash", role="viewer",
    )
    saved = mongo_repo.save_user(user)
    assert isinstance(saved.id, str)
    assert datetime.fromisoformat(saved.created_at).utcoffset().total_seconds() == 0
    document = mongo_repo._run(mongo_repo.db.users.find_one({"username": user.username}))
    assert document["created_at"].tzinfo is not None


def test_username_unique_and_settings_defaults(mongo_repo):
    username = f"unique-{uuid.uuid4().hex[:8]}"
    user = User(id=str(ObjectId()), username=username, hashed_password="hash", role="viewer")
    mongo_repo.save_user(user)
    with pytest.raises(DuplicateKeyError):
        mongo_repo._run(mongo_repo.db.users.insert_one({
            "username": username, "password_hash": "x", "role": "viewer",
        }))
    values = mongo_repo.get_settings()
    assert values.frame_skip == 1
    assert values.image_size == 640
    assert values.evidence_retention_days == 30


def test_last_login_camera_crud_and_settings_audit(mongo_repo):
    user = User(id=str(ObjectId()), username=f"login-{uuid.uuid4().hex[:8]}",
                hashed_password="hash", role="reviewer")
    saved = mongo_repo.save_user(user)
    logged_in = mongo_repo.record_login(saved.id)
    assert logged_in.last_login_at is not None
    camera_id = f"cam-{uuid.uuid4().hex[:8]}"
    camera = Camera(camera_id=camera_id, name="test camera")
    mongo_repo.save_camera(camera)
    assert mongo_repo.get_camera(camera_id).name == "test camera"
    assert mongo_repo.update_camera(camera_id, {"name": "updated"}).name == "updated"
    assert mongo_repo.delete_camera(camera_id)
    updated_settings = mongo_repo.get_settings().model_copy(update={"frame_skip": 3})
    mongo_repo.save_settings(updated_settings)
    audit = mongo_repo._run(mongo_repo.db.system_settings.find_one({"key": "frame_skip"}))
    assert audit["value"] == 3
    assert audit["updated_by"] == "api"
    assert audit["updated_at"].tzinfo is not None


def test_json_migration_is_dry_run_safe_and_idempotent(mongo_repo, tmp_path):
    source = JsonFileRepository(tmp_path / "json-source")
    user = User(id=str(uuid.uuid4()), username=f"migration-{uuid.uuid4().hex[:8]}",
                hashed_password="hash", role="viewer")
    source.save_user(user)
    camera_id = f"migration-camera-{uuid.uuid4().hex[:8]}"
    source.save_camera(Camera(camera_id=camera_id, name="migration"))
    original_id = f"migration-event-{uuid.uuid4().hex}"
    event = _event(original_id, "NO_HELMET")
    source.save_vehicle_event(event)
    source.save_violation(Violation(
        event_id=original_id, camera_id="camera-test", track_id=1,
        violation_type="helmet", ai_result="no_helmet", final_decision="VIOLATION",
    ))
    before = mongo_repo._run(mongo_repo.db.vehicle_events.count_documents({}))
    dry = migrate(dry_run=True, source_repo=source, target_repo=mongo_repo)
    assert dry["users"] == 1 and dry["cameras"] == 1
    assert dry["vehicle_events"] == 1 and dry["violations"] == 1
    assert mongo_repo._run(mongo_repo.db.vehicle_events.count_documents({})) == before
    migrate(dry_run=False, source_repo=source, target_repo=mongo_repo)
    again = migrate(dry_run=True, source_repo=source, target_repo=mongo_repo)
    assert again["users"] == 0 and again["cameras"] == 0
    assert again["vehicle_events"] == 0 and again["violations"] == 0


def test_csv_export_streams_rows(mongo_repo):
    from backend.app.routers.violations import export_violations_csv

    _save_event_with_violation(mongo_repo, _event(f"csv-{uuid.uuid4().hex}", "NO_HELMET"))
    response = export_violations_csv(repo=mongo_repo)
    async def read_body():
        return "".join([part async for part in response.body_iterator])

    body = asyncio.run(read_body())
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][0] == "event_id"
    assert any(row[3] == "helmet" for row in rows[1:])


def test_explain_uses_indexes(mongo_repo):
    assert all(value == "IXSCAN" for value in mongo_repo.explain_main_queries().values())
