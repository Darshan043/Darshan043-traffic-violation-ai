"""Offline checks for MongoRepository behavior using in-memory collection fakes."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import uuid

from bson import ObjectId

from backend.app.db.mongo_repo import MongoRepository
from backend.app.models.event import VehicleEvent
from backend.app.models.user import User
from backend.app.models.violation import Violation


def _matches(document, query):
    if "$or" in query and not any(_matches(document, part) for part in query["$or"]):
        return False
    return all(
        key == "$or" or document.get(key) == value
        for key, value in query.items()
    )


class MemoryCollection:
    def __init__(self):
        self.documents = []
        self.update_calls = []

    async def find_one(self, query):
        return deepcopy(next((doc for doc in self.documents if _matches(doc, query)), None))

    async def update_one(self, query, update, upsert=False):
        self.update_calls.append((deepcopy(query), deepcopy(update), upsert))
        document = next((doc for doc in self.documents if _matches(doc, query)), None)
        if document is None:
            if not upsert:
                return None
            document = deepcopy(update.get("$setOnInsert", {}))
            if "_id" in query:
                document["_id"] = query["_id"]
            document.update(deepcopy(update.get("$set", {})))
            self.documents.append(document)
        else:
            document.update(deepcopy(update.get("$set", {})))
            for key, value in update.get("$push", {}).items():
                document.setdefault(key, []).append(deepcopy(value))
        return None


class FakeMongo:
    @staticmethod
    def run(coroutine):
        return asyncio.run(coroutine)


class MemoryDatabase:
    def __init__(self):
        self.users = MemoryCollection()
        self.vehicle_events = MemoryCollection()
        self.violations = MemoryCollection()


def _repository():
    repository = MongoRepository.__new__(MongoRepository)
    repository.mongo = FakeMongo()
    repository.db = MemoryDatabase()
    return repository


def _event(**updates):
    values = {
        "event_id": "event-1",
        "camera_id": "camera-1",
        "run_id": "run-1",
        "track_id": 7,
        "vehicle_type": "car",
        "violation_type": "seatbelt",
        "decision": "NEEDS_REVIEW",
        "ai_result": "unclear",
        "confidence": 0.83,
        "reason": "LOW_CONFIDENCE",
        "frames_used": 9,
        "timestamp_sec": 4.5,
        "frame_idx": 108,
        "evidence": {"full_frame": "storage/evidence/frame.jpg"},
        "created_at": "2026-11-05T12:00:00+00:00",
    }
    values.update(updates)
    return VehicleEvent(**values)


def _violation(**updates):
    values = {
        "event_id": "event-1",
        "camera_id": "camera-1",
        "track_id": 7,
        "violation_type": "helmet",
        "ai_result": "unclear",
        "review_status": "pending",
        "final_decision": "PENDING",
        "reviewed_by": "reviewer-a",
        "reviewed_at": "2026-11-05T12:00:00+00:00",
        "review_note": "initial note",
    }
    values.update(updates)
    return Violation(**values)


def test_event_document_round_trip_preserves_json_repository_fields():
    repository = _repository()
    event = _event()
    document = repository._event_doc(event)

    restored = repository._event(document)
    expected = event.model_copy(update={
        "event_id": document["event_id"],
        "run_id": document["run_id"],
    })

    assert restored.model_dump() == expected.model_dump()


def test_missing_run_id_is_stable_and_explicit_runs_get_distinct_event_ids():
    repository = _repository()
    event = _event(run_id="")

    first = repository._event_doc(event)
    retry = repository._event_doc(event)
    next_run = repository._event_doc(event.model_copy(update={"run_id": "run-2"}))

    assert first["run_id"] == retry["run_id"]
    assert first["event_id"] == retry["event_id"]
    assert next_run["event_id"] != first["event_id"]
    assert next_run["event_id"].startswith("run-2_")


def test_save_vehicle_event_is_idempotent_and_does_not_insert_a_violation():
    repository = _repository()
    event = _event(decision="VIOLATION", ai_result="no_helmet", violation_type="helmet")

    first = repository.save_vehicle_event(event)
    retry = repository.save_vehicle_event(event)

    assert first.event_id == retry.event_id
    assert len(repository.db.vehicle_events.documents) == 1
    assert repository.db.violations.documents == []


def test_save_violation_retry_does_not_overwrite_review_state():
    repository = _repository()
    violation = _violation()
    repository.save_violation(violation)
    document = repository.db.violations.documents[0]
    document.update({
        "review_status": "rejected",
        "final_decision": "NOT_A_VIOLATION",
        "review_note": "review completed",
    })

    retried = repository.save_violation(violation)

    assert retried.review_status == "REVIEWED"
    assert retried.final_decision == "DISMISSED"
    assert retried.review_note == "review completed"
    assert len(repository.db.violations.documents) == 1


def test_compliance_filter_maps_to_canonical_final_decision():
    query = _repository()._violation_filter(ai_result="COMPLIANCE")

    assert query == {"$or": [{"final_decision": "NOT_A_VIOLATION"}]}


def test_partial_violation_update_preserves_omitted_fields_and_ai_result():
    repository = _repository()
    repository.save_violation(_violation())
    before = repository.get_violation("event-1")

    updated = repository.update_violation("event-1", {"review_note": "added note"})

    assert updated.ai_result == before.ai_result
    assert updated.review_status == before.review_status
    assert updated.final_decision == before.final_decision
    assert updated.reviewed_by == before.reviewed_by
    assert updated.reviewed_at == before.reviewed_at
    assert updated.review_note == "added note"
    assert len(updated.review_history) == 1


def test_user_ids_round_trip_for_string_and_legacy_objectid_ids():
    repository = _repository()
    user_id = str(uuid.uuid4())
    user = User(id=user_id, username="viewer-one", hashed_password="hash", role="viewer")

    saved = repository.save_user(user)
    updated = repository.update_user(user_id, {"full_name": "Viewer One"})
    legacy_id = ObjectId()
    repository.db.users.documents.append({
        "_id": legacy_id,
        "username": "legacy-viewer",
        "password_hash": "hash",
        "role": "viewer",
        "is_active": True,
    })

    assert saved.id == user_id
    assert repository.get_user_by_id(user_id).id == user_id
    assert updated.id == user_id and updated.full_name == "Viewer One"
    assert repository.get_user_by_id(str(legacy_id)).id == str(legacy_id)


def test_query_plan_status_uses_only_expected_index_in_winning_plan():
    expected = {
        "stage": "FETCH",
        "inputStage": {"stage": "IXSCAN", "indexName": "vehicle_events_camera_timestamp"},
    }
    rejected_only = {
        "stage": "COLLSCAN",
        "rejectedPlans": [{"stage": "IXSCAN", "indexName": "vehicle_events_camera_timestamp"}],
    }

    assert MongoRepository._plan_status(expected, "vehicle_events_camera_timestamp") == "IXSCAN"
    assert MongoRepository._plan_status(rejected_only, "vehicle_events_camera_timestamp") == "COLLSCAN"
    assert MongoRepository._plan_status(
        {"stage": "IXSCAN", "indexName": "other_index"},
        "vehicle_events_camera_timestamp",
    ) == "IXSCAN_OTHER"
