"""Preview or remove old compliance evidence; confirmed violation evidence is kept."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys

from pymongo import AsyncMongoClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings


async def _read_confirmed_event_ids(client_factory=None) -> set[str]:
    """Use a dedicated read-only credential; never initialize the write repository."""
    readonly_url = os.environ.get("MONGO_READONLY_URL", "")
    if not readonly_url:
        raise ValueError("MONGO_READONLY_URL is required for evidence cleanup inspection")
    client_factory = client_factory or AsyncMongoClient
    client = client_factory(
        readonly_url,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    try:
        return set(await client[settings.MONGO_DB].violations.distinct(
            "event_id", {"final_decision": "CONFIRMED_VIOLATION"}
        ))
    finally:
        await client.close()


def cleanup(
    days: int,
    apply: bool = False,
    *,
    confirmed_event_ids: set[str] | None = None,
    client_factory=None,
) -> int:
    if days < 0:
        raise ValueError("days must be zero or greater")
    if confirmed_event_ids is None:
        confirmed_event_ids = asyncio.run(_read_confirmed_event_ids(client_factory))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = 0
    root = settings.evidence_dir.resolve()
    for metadata in root.rglob("metadata.json"):
        try:
            if metadata.stat().st_mtime >= cutoff.timestamp():
                continue
            details = json.loads(metadata.read_text(encoding="utf-8"))
            decision = details.get("decision") or details.get("event", {}).get("decision")
            event_id = details.get("event", {}).get("event_id")
            # Unknown metadata and confirmed violations are always preserved.
            if decision != "COMPLIANCE" or not isinstance(event_id, str):
                continue
            if event_id in confirmed_event_ids:
                continue
            directory = metadata.parent.resolve()
            if root not in directory.parents:
                continue
            children = list(directory.iterdir())
            if any(child.is_dir() and not child.is_symlink() for child in children):
                continue
            print(f"{'REMOVE' if apply else 'WOULD REMOVE'}: {directory.relative_to(root)}")
            if apply:
                for child in children:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                directory.rmdir()
            candidates += 1
        except (OSError, ValueError, json.JSONDecodeError):
            # Unknown or unreadable records are deliberately preserved.
            continue
    print(f"OK: {'removed' if apply else 'would remove'} {candidates} evidence folders")
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--apply", action="store_true", help="delete the previewed folders")
    args = parser.parse_args()
    try:
        cleanup(args.days, args.apply)
    except Exception as error:
        print(f"FAIL: cleanup failed ({type(error).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
