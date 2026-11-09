"""Offline safety tests for opting into destructive Mongo integration tests."""
from __future__ import annotations

import asyncio

import pytest

from backend.app.core import config
from mongo_test_guard import (
    TEST_COLLECTIONS,
    cleanup_test_collections,
    validate_test_mongo_url,
    verify_fresh_test_database,
)
import test_mongo_repository

SAFE_TEST_DATABASE = "traffic_ai_test_0123456789"


class FakeCollection:
    def __init__(self):
        self.delete_calls = []

    async def delete_many(self, query):
        self.delete_calls.append(query)


class FakeDatabase:
    def __init__(self, collection_names=()):
        self.collection_names = list(collection_names)
        self.collections = {}
        self.requested_collections = []
        self.drop_database_calls = []

    async def list_collection_names(self):
        return list(self.collection_names)

    def __getitem__(self, name):
        self.requested_collections.append(name)
        return self.collections.setdefault(name, FakeCollection())

    def drop_database(self, name):
        self.drop_database_calls.append(name)


PRODUCTION_URL = "mongodb+srv://prod_user:prod-secret@cluster.example.test/traffic_ai"
TEST_URL = "mongodb+srv://test_user:test-secret@cluster.example.test/traffic_ai_test"


def test_identical_production_and_test_endpoints_are_rejected_without_uri_leak():
    with pytest.raises(ValueError) as error:
        validate_test_mongo_url(
            "  mongodb+srv://prod_user:prod-secret@cluster.example.test/traffic_ai  ",
            PRODUCTION_URL,
        )

    message = str(error.value)
    assert "different MongoDB endpoint" in message
    for secret in (PRODUCTION_URL, "prod-secret", "prod_user"):
        assert secret not in message


def test_default_port_and_uri_scheme_differences_do_not_bypass_endpoint_check():
    with pytest.raises(ValueError, match="different MongoDB endpoint"):
        validate_test_mongo_url(
            "mongodb://different_user:different-secret@cluster.example.test:27017/other_db",
            PRODUCTION_URL,
        )


def test_missing_test_url_is_rejected_without_secret_leak():
    with pytest.raises(ValueError) as error:
        validate_test_mongo_url("  ", PRODUCTION_URL)

    message = str(error.value)
    assert "MONGO_TEST_URL" in message
    assert PRODUCTION_URL not in message
    assert "prod-secret" not in message


def test_different_test_endpoint_is_accepted():
    result = validate_test_mongo_url(
        "  mongodb+srv://test_user:test-secret@test-cluster.example.test/db  ",
        PRODUCTION_URL,
    )

    assert result == "mongodb+srv://test_user:test-secret@test-cluster.example.test/db"


def test_fixture_rejects_production_endpoint_before_mongo_client_creation(monkeypatch):
    constructed = []

    def unexpected_client(*args, **kwargs):
        constructed.append((args, kwargs))
        raise AssertionError("Mongo client must not be created")

    monkeypatch.setenv("MONGO_TEST_URL", " mongodb+srv://prod_user:prod-secret@cluster.example.test/other_db ")
    monkeypatch.setenv("MONGO_TEST_DB", "traffic_ai_test")
    monkeypatch.setenv("MONGO_TEST_ISOLATED", "1")
    monkeypatch.setattr(config.settings, "MONGO_URL", PRODUCTION_URL)
    monkeypatch.setattr(test_mongo_repository, "MongoDatabase", unexpected_client)

    fixture_generator = test_mongo_repository.mongo_repo.__wrapped__()
    with pytest.raises(BaseException) as error:
        next(fixture_generator)

    assert "different MongoDB endpoint" in str(error.value)
    assert "prod-secret" not in str(error.value)
    assert constructed == []


def test_rejected_error_does_not_include_test_uri_or_credentials():
    with pytest.raises(ValueError) as error:
        validate_test_mongo_url(TEST_URL, PRODUCTION_URL)

    message = str(error.value)
    for secret in (TEST_URL, PRODUCTION_URL, "test-secret", "prod-secret"):
        assert secret not in message


def test_cleanup_deletes_only_allowlisted_collections_without_dropping_database():
    database = FakeDatabase()

    asyncio.run(cleanup_test_collections(database, SAFE_TEST_DATABASE))

    assert tuple(database.requested_collections) == TEST_COLLECTIONS
    assert all(
        database.collections[name].delete_calls == [{}]
        for name in TEST_COLLECTIONS
    )
    assert database.drop_database_calls == []


def test_freshness_guard_refuses_unsafe_preexisting_database_without_cleanup():
    database = FakeDatabase(collection_names=("users", "unrelated"))

    with pytest.raises(ValueError, match="unsafe Mongo test database"):
        asyncio.run(verify_fresh_test_database(database, "traffic_ai"))

    assert database.requested_collections == []
    assert database.drop_database_calls == []


def test_freshness_guard_refuses_existing_safe_test_database_without_deleting():
    database = FakeDatabase(collection_names=("users",))

    with pytest.raises(ValueError, match="not fresh"):
        asyncio.run(verify_fresh_test_database(database, SAFE_TEST_DATABASE))

    assert database.requested_collections == []
    assert database.drop_database_calls == []
