"""Safely preflight a dedicated MongoDB test database only."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pymongo import AsyncMongoClient
from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TEST_DATABASE_PATTERN = re.compile(r"^traffic_ai_test_[0-9a-f]{10}$")


def _deployment_identity(uri: str) -> tuple[str, ...]:
    """Return normalized endpoint identity without retaining credentials."""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"mongodb", "mongodb+srv"} or not parsed.netloc:
        raise ValueError("MongoDB deployment identity cannot be verified safely")
    authority = parsed.netloc.rsplit("@", 1)[-1]
    hosts = []
    for seed in authority.split(","):
        seed_url = urlsplit(f"//{seed}")
        if not seed_url.hostname:
            raise ValueError("MongoDB deployment identity cannot be verified safely")
        port = seed_url.port if seed_url.port is not None else 27017
        hosts.append(f"{seed_url.hostname.rstrip('.').lower()}:{port}")
    return tuple(sorted(hosts))


def _validate_preflight_config(
    test_url: str | None,
    production_url: str | None,
    configured_prefix: str | None,
    database_name: str | None,
) -> tuple[str, str]:
    """Require an explicitly authorized randomized test database and test endpoint."""
    test_value = (test_url or "").strip()
    if not test_value:
        raise ValueError("MONGO_TEST_URL is missing or empty")
    if configured_prefix != "traffic_ai_test":
        raise ValueError("MONGO_TEST_DB must be exactly traffic_ai_test")
    name = (database_name or "").strip()
    if not _TEST_DATABASE_PATTERN.fullmatch(name) or name == "traffic_ai":
        raise ValueError(
            "MONGO_TEST_DATABASE must match traffic_ai_test_<10 lowercase hexadecimal characters>"
        )
    if not production_url:
        raise ValueError("Production deployment identity cannot be verified safely")
    try:
        test_identity = _deployment_identity(test_value)
        production_identity = _deployment_identity(production_url)
    except (TypeError, ValueError):
        raise ValueError("MongoDB deployment identity cannot be verified safely") from None
    if test_identity == production_identity:
        raise ValueError("MONGO_TEST_URL must use a different MongoDB endpoint from MONGO_URL")
    return test_value, name


def _database_kind(uri: str) -> str:
    """Classify the endpoint without printing its credentials or hostname."""
    try:
        parsed = urlsplit(uri)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return "MongoDB"
    if parsed.scheme == "mongodb+srv" or host.endswith(".mongodb.net"):
        return "Atlas"
    if host in {"localhost", "127.0.0.1", "::1"}:
        return "local MongoDB"
    return "MongoDB"


async def check_mongo(
    *,
    test_url: str | None = None,
    production_url: str | None = None,
    configured_prefix: str | None = None,
    database_name: str | None = None,
    client_factory=AsyncMongoClient,
) -> int:
    """Ping only MONGO_TEST_URL and inspect a validated, fresh test database."""
    if test_url is None:
        test_url = os.environ.get("MONGO_TEST_URL")
    if production_url is None:
        production_url = os.environ.get("MONGO_URL")
    if configured_prefix is None:
        configured_prefix = os.environ.get("MONGO_TEST_DB")
    if database_name is None:
        database_name = os.environ.get("MONGO_TEST_DATABASE")
    try:
        uri, name = _validate_preflight_config(
            test_url, production_url, configured_prefix, database_name
        )
    except ValueError as error:
        print(f"FAIL: {error}")
        return 1

    client = None
    try:
        client = client_factory(
            uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tz_aware=True,
        )
        await client.admin.command("ping")
        database = client[name]
        collections = await database.list_collection_names()
        if collections:
            print("FAIL: refusing to use a non-empty randomized test database")
            return 1
        print(
            f"OK: {_database_kind(uri)} test endpoint ping succeeded; "
            f"database={name}; collections=(none; database is fresh)"
        )
        return 0
    except OperationFailure:
        print("FAIL: authentication or authorization failed; check test-user permissions")
        return 1
    except ServerSelectionTimeoutError:
        print(
            "FAIL: test connection timed out; check the MongoDB service or "
            "Atlas Network Access IP allowlist"
        )
        return 1
    except ConfigurationError:
        print("FAIL: invalid MongoDB test connection settings")
        return 1
    except PyMongoError as error:
        # Driver messages can contain credentials, hosts, or connection options.
        print(f"FAIL: MongoDB request failed ({type(error).__name__})")
        return 1
    except Exception as error:
        # Keep unexpected client and parsing errors from echoing a URI or options.
        print(f"FAIL: MongoDB preflight failed ({type(error).__name__})")
        return 1
    finally:
        if client is not None:
            await client.close()


if __name__ == "__main__":
    # Load only through dotenv's standard precedence: process variables win.
    # No Settings object is imported, so SECRET_KEY is not required by preflight.
    load_dotenv(PROJECT_ROOT / ".env")
    raise SystemExit(asyncio.run(check_mongo()))
