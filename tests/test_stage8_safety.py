"""Offline tests for Stage 8 migration, cleanup, and database safety guards."""
from __future__ import annotations

import asyncio
import configparser
import json
import os
from pathlib import Path
import re
import time

import pytest

from backend.app.core.config import settings
from backend.app.models.camera import Camera
from backend.app.models.user import User
from backend.app.models.settings import SystemSettings
import scripts.cleanup_evidence as cleanup_module
import scripts.migrate_json_to_mongo as migration_module
from scripts.s8_e2e import _inspect_previous_e2e_records
from mongo_test_guard import is_safe_test_database_name, new_test_database_name


class FakeCollection:
    def __init__(self, key_name: str, existing=()):
        self.key_name = key_name
        self.existing = set(existing)
        self.inserted = []

    async def find_one(self, query, _projection=None):
        return {"_id": "existing"} if query[self.key_name] in self.existing else None

    async def insert_one(self, document):
        self.inserted.append(document)


class FakeMigrationTarget:
    def __init__(self, *, users=(), cameras=()):
        self.db = type("FakeDb", (), {
            "users": FakeCollection("username", users),
            "cameras": FakeCollection("camera_id", cameras),
            "vehicle_events": FakeCollection("event_id"),
            "violations": FakeCollection("event_id"),
            "system_settings": FakeCollection("key"),
        })()
        self.closed = False

    @staticmethod
    def _run(coroutine):
        return asyncio.run(coroutine)

    @staticmethod
    def _event_doc(event):
        return {"event_id": event.event_id, "run_id": event.run_id}

    @staticmethod
    def _violation_doc(violation):
        return {"event_id": violation.event_id}

    def close(self):
        self.closed = True


class FakeMigrationSource:
    def __init__(self):
        self.users = [User(id="user-1", username="existing-user", hashed_password="hash", role="viewer")]
        self.cameras = [Camera(camera_id="existing-camera", name="camera")]

    def list_users(self):
        return self.users

    def list_cameras(self):
        return self.cameras

    def list_vehicle_events(self):
        return []

    def list_violations(self, limit):
        return [], 0

    def get_settings(self):
        return SystemSettings()


def test_migration_dry_run_uses_read_only_target_and_performs_no_inserts(monkeypatch):
    target = FakeMigrationTarget()
    monkeypatch.setenv("MONGO_READONLY_URL", "readonly-test-uri")
    monkeypatch.setattr(migration_module, "ReadOnlyMongoTarget", lambda *_: target)
    monkeypatch.setattr(
        migration_module,
        "MongoRepository",
        lambda: pytest.fail("dry-run must not construct MongoRepository"),
    )

    counts = migration_module.migrate(dry_run=True, source_repo=FakeMigrationSource())

    assert counts["users"] == 1
    assert counts["cameras"] == 1
    assert all(not getattr(target.db, name).inserted for name in (
        "users", "cameras", "vehicle_events", "violations", "system_settings"
    ))
    assert target.closed


def test_migration_skips_existing_users_and_cameras_without_overwriting():
    target = FakeMigrationTarget(users={"existing-user"}, cameras={"existing-camera"})

    counts = migration_module.migrate(
        dry_run=False, source_repo=FakeMigrationSource(), target_repo=target
    )

    assert counts["users"] == 0
    assert counts["cameras"] == 0
    assert target.db.users.inserted == []
    assert target.db.cameras.inserted == []


def test_cleanup_preview_is_read_only_and_preserves_files(tmp_path, monkeypatch):
    event_id = "old-compliant-event"

    class FakeViolations:
        async def distinct(self, field, query):
            assert field == "event_id"
            assert query == {"final_decision": "CONFIRMED_VIOLATION"}
            return []

    class FakeClient:
        writes = []

        def __init__(self, *_args, **_kwargs):
            self.traffic_ai = type("FakeDb", (), {"violations": FakeViolations()})()

        def __getitem__(self, _database):
            return self.traffic_ai

        async def close(self):
            pass

    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MONGO_READONLY_URL", "readonly-test-uri")
    metadata = settings.evidence_dir / "old-record" / "metadata.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"decision": "COMPLIANCE", "event": {"event_id": event_id}}))
    old_time = time.time() - 3 * 86400
    os.utime(metadata, (old_time, old_time))
    monkeypatch.setattr(cleanup_module, "AsyncMongoClient", FakeClient)

    candidates = cleanup_module.cleanup(days=1, apply=False)

    assert candidates == 1
    assert metadata.is_file()
    assert not FakeClient.writes


def test_cleanup_apply_never_removes_confirmed_violation_evidence(tmp_path, monkeypatch):
    event_id = "confirmed-event"

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            self.traffic_ai = type("FakeDb", (), {
                "violations": type("FakeViolations", (), {
                    "distinct": lambda *_args, **_kwargs: asyncio.sleep(0, result=[event_id])
                })()
            })()

        def __getitem__(self, _database):
            return self.traffic_ai

        async def close(self):
            pass

    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("MONGO_READONLY_URL", "readonly-test-uri")
    metadata = settings.evidence_dir / "confirmed" / "metadata.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"decision": "COMPLIANCE", "event": {"event_id": event_id}}))
    old_time = time.time() - 3 * 86400
    os.utime(metadata, (old_time, old_time))
    monkeypatch.setattr(cleanup_module, "AsyncMongoClient", FakeClient)

    assert cleanup_module.cleanup(days=1, apply=True) == 0
    assert metadata.is_file()


def test_e2e_prior_run_inspection_queries_only_test_prefixes(monkeypatch):
    queries = []
    databases = []
    test_url = "mongodb://writer:secret@test-cluster.example.test/traffic_ai_test"
    readonly_url = "mongodb://reader:secret@test-cluster.example.test/traffic_ai_test"
    production_url = "mongodb://prod:secret@production.example.test/traffic_ai"

    class Cursor:
        async def to_list(self, length):
            assert length is None
            return []

        def sort(self, *_args):
            return self

    class Collection:
        def find(self, query, projection):
            queries.append((query, projection))
            return Cursor()

    class FakeClient:
        writes = []

        def __init__(self, *_args, **_kwargs):
            class Admin:
                async def command(self, _command):
                    return {"authInfo": {
                        "authenticatedUsers": [{"user": "reader", "db": "admin"}],
                        "authenticatedUserRoles": [{"role": "read", "db": "traffic_ai_e2e_audit"}],
                        "authenticatedUserPrivileges": [{
                            "resource": {"db": "traffic_ai_e2e_audit", "collection": "e2e_runs"},
                            "actions": ["find", "listCollections", "listIndexes"],
                        }],
                    }}

            self.admin = Admin()
            self.db = type("Db", (), {"e2e_runs": Collection()})()
            self.db.__class__.__getitem__ = lambda db, name: getattr(db, name)

        def __getitem__(self, _name):
            databases.append(_name)
            return self.db

        async def close(self):
            pass

    monkeypatch.setenv("MONGO_E2E_ISOLATED", "1")
    monkeypatch.setenv("MONGO_TEST_ISOLATED", "1")
    monkeypatch.setattr(settings, "REPO_BACKEND", "mongo")
    database_name = "traffic_ai_test_0123456789"
    records = _inspect_previous_e2e_records(
        readonly_url,
        database_name,
        test_url=test_url,
        production_url=production_url,
        client_factory=FakeClient,
    )

    assert set(records) == {"audit_manifests"}
    assert len(queries) == 1
    assert "traffic_ai_test_" in str(queries[0][0])
    assert not FakeClient.writes
    assert databases == ["traffic_ai_e2e_audit"]


def test_destructive_mongo_database_names_are_strictly_test_only():
    name = new_test_database_name("traffic_ai_test")
    assert is_safe_test_database_name(name)
    assert not is_safe_test_database_name("traffic_ai")
    assert not is_safe_test_database_name("traffic_ai_test_production")
    assert not is_safe_test_database_name("traffic_ai_test_0123456789_extra")
    with pytest.raises(ValueError):
        new_test_database_name("traffic_ai")


def test_e2e_requires_explicit_isolation_and_strict_test_database():
    from scripts.s8_e2e import _validate_e2e_isolation

    isolated_urls = {
        "test_isolation_confirmation": "1",
        "test_url": "mongodb://writer:secret@test-cluster.example.test/traffic_ai_test",
        "readonly_url": "mongodb://reader:secret@test-cluster.example.test/traffic_ai_test",
        "production_url": "mongodb://prod:secret@production.example.test/traffic_ai",
        "repo_backend": "mongo",
    }
    with pytest.raises(RuntimeError, match="MONGO_E2E_ISOLATED"):
        _validate_e2e_isolation("traffic_ai_test_0123456789", None, **isolated_urls)
    with pytest.raises(RuntimeError, match="traffic_ai_test_"):
        _validate_e2e_isolation("traffic_ai", "1", **isolated_urls)
    _validate_e2e_isolation("traffic_ai_test_0123456789", "1", **isolated_urls)


def test_e2e_isolation_rejects_production_match_or_unverifiable_identity():
    from scripts.s8_e2e import _validate_e2e_isolation

    base = {
        "database_name": "traffic_ai_test_0123456789",
        "isolation_confirmation": "1",
        "test_isolation_confirmation": "1",
        "test_url": "mongodb://writer:secret@test-cluster.example.test/test",
        "readonly_url": "mongodb://reader:secret@test-cluster.example.test/test",
        "production_url": "mongodb://prod:secret@production.example.test/prod",
        "repo_backend": "mongo",
    }
    with pytest.raises(RuntimeError, match="differ from production"):
        _validate_e2e_isolation(
            **{**base, "production_url": "mongodb://prod:secret@test-cluster.example.test/prod"}
        )
    with pytest.raises(RuntimeError, match="deployment identity"):
        _validate_e2e_isolation(**{**base, "production_url": "not-a-mongodb-uri"})
    with pytest.raises(RuntimeError, match="MONGO_TEST_ISOLATED"):
        _validate_e2e_isolation(**{**base, "test_isolation_confirmation": None})
    with pytest.raises(RuntimeError, match="isolated test deployment"):
        _validate_e2e_isolation(
            **{**base, "readonly_url": "mongodb://reader:secret@other.example.test/test"}
        )
    with pytest.raises(RuntimeError, match="REPO_BACKEND"):
        _validate_e2e_isolation(**{**base, "repo_backend": "json"})


def test_randomized_e2e_database_name_requires_test_prefix():
    from scripts.s8_e2e import _new_e2e_database_name

    name = _new_e2e_database_name("traffic_ai_test")
    assert re.fullmatch(r"traffic_ai_test_[0-9a-f]{10}", name)
    with pytest.raises(RuntimeError, match="MONGO_TEST_DB"):
        _new_e2e_database_name("traffic_ai")


def test_e2e_accepts_only_valid_pre_authorized_randomized_database():
    from scripts.s8_e2e import _new_e2e_database_name

    expected = "traffic_ai_test_a1b2c3d4e5"
    assert _new_e2e_database_name("traffic_ai_test", expected) == expected
    for unsafe in (
        "traffic_ai",
        "traffic_ai_test",
        " ",
        "traffic_ai_test_A1B2C3D4E5",
        "traffic_ai_test_a1b2c3d4e5_extra",
    ):
        with pytest.raises(RuntimeError, match="MONGO_TEST_DATABASE"):
            _new_e2e_database_name("traffic_ai_test", unsafe)


def test_e2e_fresh_database_check_is_read_only_and_refuses_existing_data():
    from scripts.s8_e2e import _verify_fresh_e2e_database

    class FakeDatabase:
        def __init__(self, names):
            self.names = names

        async def list_collection_names(self):
            return self.names

    class FakeClient:
        def __init__(self, names):
            self.database = FakeDatabase(names)
            self.closed = False

        def __getitem__(self, _name):
            return self.database

        async def close(self):
            self.closed = True

    empty_client = FakeClient([])
    asyncio.run(_verify_fresh_e2e_database(
        "mongodb://writer:secret@test-cluster.example.test/test",
        "traffic_ai_test_0123456789",
        client_factory=lambda *_args, **_kwargs: empty_client,
    ))
    assert empty_client.closed

    existing_client = FakeClient(["users"])
    with pytest.raises(RuntimeError, match="non-empty randomized"):
        asyncio.run(_verify_fresh_e2e_database(
            "mongodb://writer:secret@test-cluster.example.test/test",
            "traffic_ai_test_0123456789",
            client_factory=lambda *_args, **_kwargs: existing_client,
        ))
    assert existing_client.closed


def test_readonly_connection_rejects_write_privileges():
    from scripts.s8_e2e import _assert_readonly_credentials

    class Admin:
        async def command(self, _command):
            return {"authInfo": {
                "authenticatedUsers": [{"user": "reader", "db": "admin"}],
                "authenticatedUserRoles": [{"role": "custom", "db": "admin"}],
                "authenticatedUserPrivileges": [{
                "resource": {"db": "traffic_ai_e2e_audit", "collection": "e2e_runs"},
                    "actions": ["find", "insert"],
                }],
            }}

    with pytest.raises(RuntimeError, match="write-capable"):
        asyncio.run(_assert_readonly_credentials(type("FakeClient", (), {"admin": Admin()})()))


def test_readonly_connection_rejects_broad_database_scope():
    from scripts.s8_e2e import _assert_readonly_credentials

    class Admin:
        async def command(self, _command):
            return {"authInfo": {
                "authenticatedUsers": [{"user": "reader", "db": "admin"}],
                "authenticatedUserRoles": [{"role": "readAnyDatabase", "db": "admin"}],
                "authenticatedUserPrivileges": [{
                    "resource": {"db": "", "collection": ""},
                    "actions": ["find", "listCollections"],
                }],
            }}

    with pytest.raises(Exception, match="over-scoped"):
        asyncio.run(_assert_readonly_credentials(type("FakeClient", (), {"admin": Admin()})()))


def test_e2e_audit_writer_uses_only_test_url_and_validates_database_name():
    from scripts.s8_e2e import _write_e2e_audit_manifest

    calls = []

    class Collection:
        async def replace_one(self, query, document, upsert):
            calls.append((query, document, upsert))

    class Database:
        e2e_runs = Collection()

        def __getitem__(self, name):
            assert name == "e2e_runs"
            return self.e2e_runs

    class Client:
        def __init__(self, uri, **_kwargs):
            assert uri == "test-writer-uri"

        def __getitem__(self, name):
            assert name == "traffic_ai_e2e_audit"
            return Database()

        async def close(self):
            pass

    document = {"_id": "run-id", "database_name": "traffic_ai_test_0123456789"}
    _write_e2e_audit_manifest("test-writer-uri", document, client_factory=Client)
    assert calls == [({"_id": "run-id"}, document, True)]
    with pytest.raises(RuntimeError, match="unsafe database"):
        _write_e2e_audit_manifest("test-writer-uri", {"_id": "bad", "database_name": "traffic_ai"},
                                  client_factory=Client)


def test_e2e_repository_is_injected_with_test_url_without_changing_production(monkeypatch):
    from backend.app import deps
    from backend.app.core.config import settings as app_settings
    from backend.app.db import mongo
    from backend.app.db import mongo_repo
    from scripts.s8_e2e import _create_e2e_repository

    constructed_mongo = []
    constructed_repository = []

    class FakeMongoDatabase:
        def __init__(self, url, database_name, **kwargs):
            self.url = url
            self.database_name = database_name
            self.kwargs = kwargs
            constructed_mongo.append(self)

        def close(self):
            pass

    class FakeRepository:
        def __init__(self, *, mongo):
            constructed_repository.append(mongo)

        def close(self):
            pass

    production_url = "mongodb://production.example.test/traffic_ai"
    test_url = "mongodb://test.example.test/traffic_ai_test"
    previous_repo = deps._repo
    monkeypatch.setattr(app_settings, "MONGO_URL", production_url)
    monkeypatch.setattr(mongo, "MongoDatabase", FakeMongoDatabase)
    monkeypatch.setattr(mongo_repo, "MongoRepository", FakeRepository)
    monkeypatch.setattr(deps, "_repo", None)

    repo = _create_e2e_repository(test_url, "traffic_ai_test_0123456789")

    assert constructed_mongo[0].url == test_url
    assert constructed_mongo[0].database_name == "traffic_ai_test_0123456789"
    assert constructed_repository == [constructed_mongo[0]]
    assert deps.get_repository() is repo
    assert app_settings.MONGO_URL == production_url
    monkeypatch.setattr(deps, "_repo", previous_repo)


def test_default_pytest_excludes_mongo_marker():
    parser = configparser.ConfigParser()
    parser.read(Path(__file__).parents[1] / "pytest.ini")
    assert "not mongo" in parser["pytest"]["addopts"]
