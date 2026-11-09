"""Copy JSON repository records into MongoDB without overwriting conflicts."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings
from backend.app.db.json_repo import JsonFileRepository
from backend.app.db.mongo_repo import MongoRepository, _datetime, _zone_for_mongo


class ReadOnlyMongoTarget:
    """Minimal query-only target used by migration previews."""

    def __init__(self, url: str, database_name: str, client_factory=AsyncMongoClient) -> None:
        if not url:
            raise ValueError("MONGO_READONLY_URL is missing or empty")
        self._loop = asyncio.new_event_loop()
        self.client = client_factory(
            url,
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self.db = self.client[database_name]
        try:
            self._run(self.client.admin.command("ping"))
        except Exception as error:
            try:
                self._run(self.client.close())
            finally:
                self._loop.close()
            raise RuntimeError(f"Read-only Mongo connection failed ({type(error).__name__})") from None

    def _run(self, coroutine):
        return self._loop.run_until_complete(coroutine)

    def close(self) -> None:
        try:
            self._run(self.client.close())
        finally:
            self._loop.close()


def _user_document(user) -> dict:
    return {
        "username": user.username,
        "full_name": user.full_name,
        "password_hash": user.hashed_password,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": _datetime(user.created_at),
        "last_login_at": _datetime(user.last_login_at) if user.last_login_at else None,
    }


def _camera_document(camera) -> dict:
    document = camera.model_dump()
    document["zone"] = _zone_for_mongo(document.get("zone"))
    document["created_at"] = _datetime(document["created_at"])
    document["updated_at"] = _datetime(document["updated_at"])
    return document


def _exists(target, collection_name: str, query: dict) -> bool:
    collection = getattr(target.db, collection_name)
    return target._run(collection.find_one(query, {"_id": 1})) is not None


def _insert_if_new(target, collection_name: str, document: dict) -> bool:
    """Insert only; an existing unique key is a safe skip, never an update."""
    collection = getattr(target.db, collection_name)
    try:
        target._run(collection.insert_one(document))
    except DuplicateKeyError:
        return False
    return True


def migrate(*, dry_run: bool, source_repo=None, target_repo=None) -> dict[str, int]:
    source = source_repo or JsonFileRepository()
    if target_repo is not None:
        target = target_repo
        owns_target = False
    elif dry_run:
        target = ReadOnlyMongoTarget(
            os.environ.get("MONGO_READONLY_URL", ""), settings.MONGO_DB
        )
        owns_target = True
    else:
        target = MongoRepository()
        owns_target = True

    counts = {"users": 0, "cameras": 0, "vehicle_events": 0, "violations": 0, "settings": 0}
    migrated_event_ids: dict[str, str] = {}
    try:
        for user in source.list_users():
            exists = _exists(target, "users", {"username": user.username})
            if exists:
                continue
            if dry_run:
                counts["users"] += 1
            elif _insert_if_new(target, "users", _user_document(user)):
                counts["users"] += 1

        for camera in source.list_cameras():
            exists = _exists(target, "cameras", {"camera_id": camera.camera_id})
            if exists:
                continue
            if dry_run:
                counts["cameras"] += 1
            elif _insert_if_new(target, "cameras", _camera_document(camera)):
                counts["cameras"] += 1

        for event in source.list_vehicle_events():
            stable_run = event.run_id or "json-migration"
            run_prefix = f"{stable_run}_"
            event_id = (
                event.event_id
                if event.event_id.startswith(run_prefix)
                else f"{run_prefix}{event.event_id}"
            )
            migrated_event_ids[event.event_id] = event_id
            migrated = event.model_copy(update={"run_id": stable_run, "event_id": event_id})
            if _exists(target, "vehicle_events", {"event_id": event_id}):
                continue
            if dry_run:
                counts["vehicle_events"] += 1
            elif _insert_if_new(target, "vehicle_events", target._event_doc(migrated)):
                counts["vehicle_events"] += 1

        source_violations, _ = source.list_violations(limit=1_000_000)
        for violation in source_violations:
            violation_id = migrated_event_ids.get(
                violation.event_id, f"json-migration_{violation.event_id}"
            )
            migrated_violation = violation.model_copy(update={"event_id": violation_id})
            if _exists(target, "violations", {"event_id": violation_id}):
                continue
            if dry_run:
                counts["violations"] += 1
            elif _insert_if_new(
                target, "violations", target._violation_doc(migrated_violation)
            ):
                counts["violations"] += 1

        current_settings = source.get_settings().model_dump()
        now = datetime.now(timezone.utc)
        for key, value in current_settings.items():
            if _exists(target, "system_settings", {"key": key}):
                continue
            if dry_run:
                counts["settings"] += 1
            elif _insert_if_new(target, "system_settings", {
                "key": key,
                "value": value,
                "updated_by": "json-migration",
                "updated_at": now,
            }):
                counts["settings"] += 1
        return counts
    finally:
        if owns_target:
            target.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report records that would be inserted")
    args = parser.parse_args()
    if not args.dry_run and settings.REPO_BACKEND != "mongo":
        print("FAIL: set REPO_BACKEND=mongo before applying this migration")
        return 1
    try:
        counts = migrate(dry_run=args.dry_run)
    except Exception as error:
        print(f"FAIL: migration failed ({type(error).__name__})")
        return 1
    action = "would insert" if args.dry_run else "inserted; existing conflicts skipped"
    print(f"OK: {action}: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
