"""Pure naming guards for destructive MongoDB integration tests."""
from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import uuid4

TEST_COLLECTIONS = (
    "users",
    "cameras",
    "vehicle_events",
    "violations",
    "system_settings",
)
TEST_DATABASE_PREFIX = "traffic_ai_test"
_SAFE_DATABASE_PATTERN = re.compile(r"^traffic_ai_test_[0-9a-f]{10}$")


def _connection_hosts(uri: str) -> tuple[str, ...]:
    """Return normalized Mongo hosts without retaining URI credentials."""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"mongodb", "mongodb+srv"} or not parsed.netloc:
        raise ValueError("Mongo test URI is invalid or cannot be safely compared")

    # Split the authority after userinfo, then parse each seed independently.
    authority = parsed.netloc.rsplit("@", 1)[-1]
    hosts = []
    for seed in authority.split(","):
        try:
            host = urlsplit(f"//{seed}").hostname
            port = urlsplit(f"//{seed}").port
        except ValueError:
            host = None
            port = None
        if not host:
            raise ValueError("Mongo test URI is invalid or cannot be safely compared")
        normalized_host = host.rstrip(".").lower()
        # Use MongoDB's default port for both URI schemes, so switching between
        # mongodb:// and mongodb+srv:// cannot disguise a matching seed host.
        normalized_port = port if port is not None else 27017
        port_suffix = "" if normalized_port is None else f":{normalized_port}"
        hosts.append(f"{normalized_host}{port_suffix}")
    return tuple(sorted(hosts))


def validate_test_mongo_url(test_url: str | None, production_url: str | None) -> str:
    """Require a test URI and reject the production endpoint without exposing it."""
    test_value = (test_url or "").strip()
    production_value = (production_url or "").strip()
    if not test_value:
        raise ValueError("MONGO_TEST_URL must be explicitly configured")
    test_hosts = _connection_hosts(test_value)
    if production_value and test_hosts == _connection_hosts(production_value):
        raise ValueError("MONGO_TEST_URL must use a different MongoDB endpoint from MONGO_URL")
    return test_value


def is_safe_test_database_name(name: str) -> bool:
    return bool(_SAFE_DATABASE_PATTERN.fullmatch(name)) and name != "traffic_ai"


def new_test_database_name(configured_prefix: str) -> str:
    if configured_prefix != TEST_DATABASE_PREFIX:
        raise ValueError("MONGO_TEST_DB must be exactly traffic_ai_test")
    name = f"{configured_prefix}_{uuid4().hex[:10]}"
    if not is_safe_test_database_name(name):
        raise ValueError("Generated Mongo test database name is unsafe")
    return name


async def verify_fresh_test_database(database, name: str) -> None:
    """Reject unsafe or previously initialized databases before repository setup."""
    if not is_safe_test_database_name(name):
        raise ValueError("Refusing to use an unsafe Mongo test database name")
    if await database.list_collection_names():
        raise ValueError("Refusing to use a Mongo test database that is not fresh")


async def cleanup_test_collections(database, name: str) -> None:
    """Delete documents only from the allowlisted collections in a test database."""
    if not is_safe_test_database_name(name):
        raise ValueError("Refusing to clean an unsafe Mongo test database name")
    for collection_name in TEST_COLLECTIONS:
        await database[collection_name].delete_many({})
