"""Offline tests for the test-only MongoDB connection preflight."""
from __future__ import annotations

import asyncio

import pytest

from scripts import check_mongo


PRODUCTION_URL = "mongodb+srv://prod-user:prod-secret@prod.example.test/traffic_ai"
TEST_URL = "mongodb+srv://test-user:test-secret@test.example.test/test"
SAFE_DATABASE = "traffic_ai_test_a1b2c3d4e5"


def _valid_args(**overrides):
    return {
        "test_url": TEST_URL,
        "production_url": PRODUCTION_URL,
        "configured_prefix": "traffic_ai_test",
        "database_name": SAFE_DATABASE,
        **overrides,
    }


def test_preflight_missing_test_url_fails_before_client_creation(capsys):
    def unexpected_client(*_args, **_kwargs):
        pytest.fail("preflight must not create a client without MONGO_TEST_URL")

    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(test_url=""), client_factory=unexpected_client
    ))

    output = capsys.readouterr().out
    assert result == 1
    assert "MONGO_TEST_URL" in output
    assert "prod-secret" not in output
    assert TEST_URL not in output


def test_preflight_rejects_production_endpoint_before_client_creation(capsys):
    def unexpected_client(*_args, **_kwargs):
        pytest.fail("preflight must reject a production endpoint before connecting")

    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(test_url=PRODUCTION_URL), client_factory=unexpected_client
    ))

    output = capsys.readouterr().out
    assert result == 1
    assert "different MongoDB endpoint" in output
    assert PRODUCTION_URL not in output
    assert "prod-secret" not in output


@pytest.mark.parametrize("database_name", [
    "traffic_ai",
    "traffic_ai_test",
    "traffic_ai_test_A1B2C3D4E5",
    "traffic_ai_test_a1b2c3d4e5_extra",
])
def test_preflight_rejects_unsafe_database_names_before_client_creation(database_name, capsys):
    def unexpected_client(*_args, **_kwargs):
        pytest.fail("preflight must reject an unsafe database name before connecting")

    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(database_name=database_name), client_factory=unexpected_client
    ))

    output = capsys.readouterr().out
    assert result == 1
    assert "MONGO_TEST_DATABASE" in output
    assert "traffic_ai_test_<10 lowercase hexadecimal characters>" in output


def test_preflight_requires_exact_test_base(capsys):
    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(configured_prefix="traffic_ai"),
        client_factory=lambda *_args, **_kwargs: pytest.fail("no client expected"),
    ))

    assert result == 1
    assert "MONGO_TEST_DB must be exactly traffic_ai_test" in capsys.readouterr().out


def test_preflight_uses_only_test_uri_and_checks_fresh_named_database(capsys):
    constructed = []

    class FakeDatabase:
        async def list_collection_names(self):
            return []

    class FakeAdmin:
        async def command(self, command):
            assert command == "ping"
            return {"ok": 1}

    class FakeClient:
        admin = FakeAdmin()

        def __init__(self, uri, **_kwargs):
            constructed.append(uri)

        def __getitem__(self, name):
            assert name == SAFE_DATABASE
            return FakeDatabase()

        async def close(self):
            pass

    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(), client_factory=FakeClient
    ))

    output = capsys.readouterr().out
    assert result == 0
    assert constructed == [TEST_URL]
    assert PRODUCTION_URL not in output
    assert "database=" + SAFE_DATABASE in output
    assert "test-secret" not in output


def test_preflight_refuses_nonempty_randomized_database(capsys):
    class FakeDatabase:
        async def list_collection_names(self):
            return ["users"]

    class FakeAdmin:
        async def command(self, _command):
            return {"ok": 1}

    class FakeClient:
        admin = FakeAdmin()

        def __init__(self, *_args, **_kwargs):
            pass

        def __getitem__(self, _name):
            return FakeDatabase()

        async def close(self):
            pass

    result = asyncio.run(check_mongo.check_mongo(
        **_valid_args(), client_factory=FakeClient
    ))

    assert result == 1
    assert "non-empty randomized test database" in capsys.readouterr().out
