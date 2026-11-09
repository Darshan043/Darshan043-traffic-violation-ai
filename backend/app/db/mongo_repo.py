"""MongoDB-backed implementation of the existing repository interface."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Iterator
from uuid import NAMESPACE_URL, uuid5

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from backend.app.core.config import settings
from backend.app.db.mongo import MongoDatabase
from backend.app.db.repository import Repository
from backend.app.models.camera import Camera
from backend.app.models.event import VehicleEvent
from backend.app.models.settings import SystemSettings
from backend.app.models.user import User
from backend.app.models.violation import Violation

logger = logging.getLogger("traffic_ai.mongo")

_RESULT_DETAILS: dict[str, tuple[str, str, str]] = {
    "HELMET": ("COMPLIANCE", "helmet", "helmet"),
    "NO_HELMET": ("VIOLATION", "no_helmet", "helmet"),
    "SEATBELT": ("COMPLIANCE", "seatbelt", "seatbelt"),
    "NO_SEATBELT": ("VIOLATION", "no_seatbelt", "seatbelt"),
    "NEEDS_REVIEW": ("NEEDS_REVIEW", "unclear", "helmet"),
    "NOT_CHECKED": ("NOT_CHECKED", "unclear", "helmet"),
}


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif value:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        result = datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _iso(value: Any) -> str:
    return _datetime(value).isoformat()


def _object_id(value: str) -> ObjectId | None:
    return ObjectId(value) if ObjectId.is_valid(value) else None


def _user_id_filter(user_id: str) -> dict[str, Any]:
    """Match both current string IDs and ObjectIds written by older versions."""
    object_id = _object_id(user_id)
    candidates: list[Any] = [user_id]
    if object_id is not None:
        candidates.insert(0, object_id)
    if len(candidates) == 1:
        return {"_id": candidates[0]}
    return {"$or": [{"_id": candidate} for candidate in candidates]}


def _relative_evidence(paths: dict[str, Any]) -> dict[str, str | None]:
    root = settings.evidence_dir.resolve()

    def relative(value: Any) -> str | None:
        if not value:
            return None
        path = Path(str(value))
        try:
            resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
            return resolved.relative_to(root).as_posix()
        except (OSError, ValueError):
            return None

    return {
        "full_image": relative(paths.get("full_frame") or paths.get("full_image")),
        "crop_image": relative(
            paths.get("driver_rider_crop")
            or paths.get("crop_image")
            or paths.get("vehicle_crop")
        ),
    }


def _zone_for_mongo(zone: Any) -> dict[str, Any]:
    if isinstance(zone, dict):
        return zone
    flat = [float(item) for item in (zone or [])]
    pairs = [[flat[index], flat[index + 1]] for index in range(0, len(flat) - 1, 2)]
    return {"type": "line" if len(pairs) == 2 else "polygon", "points": pairs}


def _zone_for_model(zone: Any) -> list[float]:
    if isinstance(zone, dict):
        return [float(value) for point in zone.get("points", []) for value in point]
    return [float(item) for item in (zone or [])]


def _legacy_review_status(value: str) -> str:
    return {
        "pending": "UNREVIEWED",
        "not_required": "UNREVIEWED",
        "confirmed": "REVIEWED",
        "rejected": "REVIEWED",
    }.get(value, value)


def _canonical_review_status(value: str, ai_result: str, final_decision: str | None) -> str:
    if value in {"pending", "not_required", "confirmed", "rejected"}:
        return value
    if value == "REVIEWED":
        return "confirmed" if final_decision in {"VIOLATION", "CONFIRMED_VIOLATION"} else "rejected"
    return "pending" if ai_result == "unclear" else "not_required"


def _canonical_final_decision(value: str | None, review_status: str) -> str:
    if value in {"CONFIRMED_VIOLATION", "NOT_A_VIOLATION", "PENDING"}:
        return value
    if value == "VIOLATION":
        return "CONFIRMED_VIOLATION"
    if value in {"COMPLIANCE", "DISMISSED"}:
        return "NOT_A_VIOLATION"
    if review_status == "pending":
        return "PENDING"
    if review_status == "rejected":
        return "NOT_A_VIOLATION"
    return "CONFIRMED_VIOLATION"


class MongoRepository(Repository):
    """Synchronous repository facade using PyMongo's async client on one loop."""

    def __init__(
        self,
        url: str | None = None,
        database_name: str | None = None,
        *,
        mongo: MongoDatabase | None = None,
    ) -> None:
        self.mongo = mongo or MongoDatabase(
            url if url is not None else settings.MONGO_URL,
            database_name or settings.MONGO_DB,
            operation_timeout_seconds=settings.MONGO_OPERATION_TIMEOUT_SECONDS,
        )
        self.db = self.mongo.database
        self.mongo.run(self._seed_settings())

    def _run(self, coroutine):
        return self.mongo.run(coroutine)

    async def _seed_settings(self) -> None:
        defaults = SystemSettings().model_dump()
        now = datetime.now(timezone.utc)
        for key, value in defaults.items():
            await self.db.system_settings.update_one(
                {"key": key},
                {"$setOnInsert": {"value": value, "updated_by": "system", "updated_at": now}},
                upsert=True,
            )

    def initialize(self) -> None:
        """Recheck the connection at application startup."""
        self._run(self.db.command("ping"))

    def close(self) -> None:
        self.mongo.close()

    # Users
    def _user(self, doc: dict[str, Any] | None) -> User | None:
        if not doc:
            return None
        return User(
            id=str(doc.get("_id", "")),
            username=doc["username"],
            hashed_password=doc.get("password_hash", ""),
            full_name=doc.get("full_name", ""),
            role=doc["role"],
            is_active=doc.get("is_active", True),
            created_at=_iso(doc.get("created_at")),
            last_login_at=_iso(doc["last_login_at"]) if doc.get("last_login_at") else None,
        )

    def get_user_by_id(self, user_id: str) -> User | None:
        return self._user(self._run(self.db.users.find_one(_user_id_filter(user_id))))

    def get_user_by_username(self, username: str) -> User | None:
        return self._user(self._run(self.db.users.find_one({"username": username})))

    def list_users(self) -> list[User]:
        async def read():
            return [doc async for doc in self.db.users.find().sort("username", 1)]

        return [user for doc in self._run(read()) if (user := self._user(doc)) is not None]

    def save_user(self, user: User) -> User:
        now = _datetime(user.created_at)
        mongo_id = _object_id(user.id) or user.id
        doc = {
            "username": user.username,
            "full_name": user.full_name,
            "password_hash": user.hashed_password,
            "role": user.role,
            "is_active": user.is_active,
            "created_at": now,
            "last_login_at": _datetime(user.last_login_at) if user.last_login_at else None,
        }

        async def save():
            return await self.db.users.update_one(
                {"_id": mongo_id}, {"$set": doc}, upsert=True
            )

        try:
            self._run(save())
        except DuplicateKeyError:
            logger.warning("Skipped duplicate MongoDB username")
            raise
        return self.get_user_by_username(user.username) or user

    def update_user(self, user_id: str, updates: dict[str, Any]) -> User | None:
        query = _user_id_filter(user_id)
        mapped = dict(updates)
        if "hashed_password" in mapped:
            mapped["password_hash"] = mapped.pop("hashed_password")
        if mapped.get("last_login_at"):
            mapped["last_login_at"] = _datetime(mapped["last_login_at"])

        async def update():
            await self.db.users.update_one(query, {"$set": mapped})
            return await self.db.users.find_one(query)

        return self._user(self._run(update()))

    def record_login(self, user_id: str) -> User | None:
        return self.update_user(user_id, {"last_login_at": datetime.now(timezone.utc).isoformat()})

    # Cameras
    def _camera(self, doc: dict[str, Any] | None) -> Camera | None:
        if not doc:
            return None
        values = {key: value for key, value in doc.items() if key != "_id"}
        values["zone"] = _zone_for_model(values.get("zone"))
        for field in ("created_at", "updated_at"):
            values[field] = _iso(values.get(field))
        return Camera(**values)

    def get_camera(self, camera_id: str) -> Camera | None:
        return self._camera(self._run(self.db.cameras.find_one({"camera_id": camera_id})))

    def list_cameras(self) -> list[Camera]:
        async def read():
            return [doc async for doc in self.db.cameras.find().sort("camera_id", 1)]

        return [camera for doc in self._run(read()) if (camera := self._camera(doc)) is not None]

    def save_camera(self, camera: Camera) -> Camera:
        doc = camera.model_dump()
        doc["zone"] = _zone_for_mongo(doc.get("zone"))
        doc["created_at"] = _datetime(doc["created_at"])
        doc["updated_at"] = _datetime(doc["updated_at"])

        async def save():
            await self.db.cameras.update_one(
                {"camera_id": camera.camera_id}, {"$set": doc}, upsert=True
            )
            return await self.db.cameras.find_one({"camera_id": camera.camera_id})

        return self._camera(self._run(save())) or camera

    def update_camera(self, camera_id: str, updates: dict[str, Any]) -> Camera | None:
        mapped = {key: value for key, value in updates.items() if value is not None}
        if "zone" in mapped:
            mapped["zone"] = _zone_for_mongo(mapped["zone"])
        mapped["updated_at"] = datetime.now(timezone.utc)

        async def update():
            await self.db.cameras.update_one({"camera_id": camera_id}, {"$set": mapped})
            return await self.db.cameras.find_one({"camera_id": camera_id})

        return self._camera(self._run(update()))

    def delete_camera(self, camera_id: str) -> bool:
        result = self._run(self.db.cameras.delete_one({"camera_id": camera_id}))
        return bool(result.deleted_count)

    # Vehicle events
    def _event_doc(self, event: VehicleEvent) -> dict[str, Any]:
        # The API supplies a fresh run_id per processing run. Callers without a
        # run_id get a deterministic fallback, so retrying the same event keeps
        # the same unique key.
        run_id = event.run_id or uuid5(
            NAMESPACE_URL, f"traffic-ai:{event.camera_id}:{event.event_id}"
        ).hex
        run_prefix = f"{run_id}_"
        event_id = (
            event.event_id
            if event.event_id.startswith(run_prefix)
            else f"{run_prefix}{event.event_id}"
        )
        return {
            "event_id": event_id,
            "camera_id": event.camera_id,
            "run_id": run_id,
            "track_id": event.track_id,
            "vehicle_type": event.vehicle_type,
            "violation_type": event.violation_type,
            "decision": event.decision,
            "ai_result": event.ai_result,
            "result": event.result,
            "confidence": event.confidence,
            "frames_used": event.frames_used,
            "reason_code": event.reason,
            "timestamp": _datetime(event.created_at),
            "video_time_sec": event.timestamp_sec,
            "frame_idx": event.frame_idx,
            "evidence": dict(event.evidence),
        }

    def save_event(self, event: VehicleEvent) -> VehicleEvent:
        doc = self._event_doc(event)
        persisted = event.model_copy(update={"event_id": doc["event_id"], "run_id": doc["run_id"]})

        async def insert_or_read():
            try:
                await self.db.vehicle_events.update_one(
                    {"event_id": doc["event_id"]},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
            except DuplicateKeyError:
                # A concurrent upsert can race on the unique event_id index.
                pass
            return await self.db.vehicle_events.find_one({"event_id": doc["event_id"]})

        stored = self._run(insert_or_read())
        return self._event(stored) if stored is not None else persisted

    def save_vehicle_event(self, event: VehicleEvent) -> VehicleEvent:
        return self.save_event(event)

    def _event(self, doc: dict[str, Any]) -> VehicleEvent:
        result = doc.get("result", "NOT_CHECKED")
        legacy_decision, legacy_ai_result, legacy_violation_type = _RESULT_DETAILS.get(
            result, ("NOT_CHECKED", "unclear", "helmet")
        )
        return VehicleEvent(
            event_id=doc["event_id"],
            camera_id=doc["camera_id"],
            run_id=doc.get("run_id", ""),
            track_id=int(doc.get("track_id", 0)),
            vehicle_type=doc.get("vehicle_type", "motorcycle"),
            violation_type=doc.get("violation_type", legacy_violation_type),
            decision=doc.get("decision", legacy_decision),
            ai_result=doc.get("ai_result", legacy_ai_result),
            confidence=float(doc.get("confidence", 0.0)),
            reason=doc.get("reason", doc.get("reason_code", "")),
            frames_used=int(doc.get("frames_used", 0)),
            timestamp_sec=float(doc.get("timestamp_sec", doc.get("video_time_sec", 0.0))),
            frame_idx=int(doc.get("frame_idx", 0)),
            evidence=dict(doc.get("evidence") or {}),
            created_at=_iso(doc.get("created_at", doc.get("timestamp"))),
        )

    def list_vehicle_events(self, camera_id: str | None = None) -> list[VehicleEvent]:
        query = {"camera_id": camera_id} if camera_id else {}

        async def read():
            return [doc async for doc in self.db.vehicle_events.find(query).sort("timestamp", -1)]

        return [self._event(doc) for doc in self._run(read())]

    # Violations
    def _violation_doc(self, violation: Violation) -> dict[str, Any]:
        status = _canonical_review_status(
            violation.review_status, violation.ai_result, violation.final_decision
        )
        final = _canonical_final_decision(violation.final_decision, status)
        return {
            "event_id": violation.event_id,
            "camera_id": violation.camera_id,
            "track_id": violation.track_id,
            "violation_type": violation.violation_type,
            "ai_result": violation.ai_result,
            "detection_confidence": violation.detection_confidence,
            "reason_code": violation.reason_code,
            "evidence": _relative_evidence(violation.evidence),
            "review_status": status,
            "reviewed_by": violation.reviewed_by,
            "reviewed_at": _datetime(violation.reviewed_at) if violation.reviewed_at else None,
            "review_note": violation.review_note,
            "final_decision": final,
            "review_history": list(violation.review_history),
            "created_at": _datetime(violation.created_at),
        }

    def _violation(self, doc: dict[str, Any] | None) -> Violation | None:
        if not doc:
            return None
        status = str(doc.get("review_status", "pending"))
        final = str(doc.get("final_decision", "PENDING"))
        if final == "CONFIRMED_VIOLATION":
            final = "VIOLATION"
        elif final == "NOT_A_VIOLATION":
            final = "DISMISSED"
        return Violation(
            event_id=doc["event_id"],
            camera_id=doc["camera_id"],
            track_id=int(doc["track_id"]),
            violation_type=doc["violation_type"],
            ai_result=doc["ai_result"],
            detection_confidence=float(doc.get("detection_confidence", 0.0)),
            reason_code=doc.get("reason_code", ""),
            evidence=doc.get("evidence", {}),
            review_status=_legacy_review_status(status),
            final_decision=final,
            reviewed_by=doc.get("reviewed_by"),
            reviewed_at=_iso(doc["reviewed_at"]) if doc.get("reviewed_at") else None,
            review_note=doc.get("review_note"),
            created_at=_iso(doc.get("created_at")),
            review_history=doc.get("review_history", []),
        )

    def _violation_filter(
        self,
        violation_type: str | None = None,
        ai_result: str | None = None,
        camera_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        track_id: int | None = None,
        review_status: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if violation_type:
            query["violation_type"] = violation_type
        if ai_result:
            ai_values = {
                "HELMET": "helmet",
                "NO_HELMET": "no_helmet",
                "SEATBELT": "seatbelt",
                "NO_SEATBELT": "no_seatbelt",
                "NEEDS_REVIEW": "unclear",
            }
            if ai_result in ai_values:
                alternatives = [{"ai_result": ai_values[ai_result]}]
            elif ai_result in {
                "COMPLIANCE", "VIOLATION", "PENDING", "CONFIRMED_VIOLATION",
                "NOT_A_VIOLATION", "DISMISSED",
            }:
                decision = {
                    "COMPLIANCE": "NOT_A_VIOLATION",
                    "VIOLATION": "CONFIRMED_VIOLATION",
                    "DISMISSED": "NOT_A_VIOLATION",
                }.get(ai_result, ai_result)
                alternatives = [{"final_decision": decision}]
            else:
                alternatives = [{"ai_result": ai_result}, {"final_decision": ai_result}]
            query["$or"] = alternatives
        if camera_id:
            query["camera_id"] = camera_id
        if track_id is not None:
            query["track_id"] = track_id
        if review_status:
            query["review_status"] = {
                "UNREVIEWED": {"$in": ["pending", "not_required"]},
                "REVIEWED": {"$in": ["confirmed", "rejected"]},
            }.get(review_status, review_status)
        date_filter: dict[str, datetime] = {}
        if date_from:
            date_filter["$gte"] = _datetime(date_from)
        if date_to:
            date_filter["$lte"] = _datetime(date_to)
        if date_filter:
            query["created_at"] = date_filter
        return query

    def get_violation(self, event_id: str) -> Violation | None:
        return self._violation(self._run(self.db.violations.find_one({"event_id": event_id})))

    def list_violations(
        self,
        violation_type: str | None = None,
        ai_result: str | None = None,
        camera_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        track_id: int | None = None,
        review_status: str | None = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[Violation], int]:
        query = self._violation_filter(
            violation_type, ai_result, camera_id, date_from, date_to, track_id, review_status
        )

        async def read():
            total = await self.db.violations.count_documents(query)
            cursor = self.db.violations.find(query).sort("created_at", -1)
            cursor = cursor.skip(max(0, (page - 1) * limit)).limit(limit)
            return [doc async for doc in cursor], total

        docs, total = self._run(read())
        return [item for doc in docs if (item := self._violation(doc)) is not None], total

    def iter_violations(self, **filters: Any) -> Iterator[Violation]:
        query = self._violation_filter(**filters)
        batch_size = 250
        offset = 0
        while True:
            async def read_batch(skip: int):
                cursor = self.db.violations.find(query).sort("created_at", -1).skip(skip).limit(batch_size)
                return [doc async for doc in cursor]

            batch = self._run(read_batch(offset))
            if not batch:
                return
            for doc in batch:
                item = self._violation(doc)
                if item is not None:
                    yield item
            offset += len(batch)

    def save_violation(self, violation: Violation) -> Violation:
        doc = self._violation_doc(violation)

        async def insert():
            try:
                await self.db.violations.update_one(
                    {"event_id": violation.event_id},
                    {"$setOnInsert": doc},
                    upsert=True,
                )
            except DuplicateKeyError:
                # Concurrent upserts can race on the unique event_id index.
                pass

        self._run(insert())
        return self.get_violation(violation.event_id) or violation

    def update_violation(self, event_id: str, updates: dict[str, Any]) -> Violation | None:
        current = self.get_violation(event_id)
        if current is None:
            return None
        allowed = {
            "review_status", "final_decision", "reviewed_by", "reviewed_at", "review_note"
        }
        changes = {
            key: value for key, value in updates.items()
            if key in allowed and value is not None
        }
        if not changes:
            return current
        status_value = changes.get("review_status", current.review_status)
        final_value = changes.get("final_decision", current.final_decision)
        if "final_decision" in changes and "review_status" not in changes:
            canonical_final = _canonical_final_decision(
                str(final_value) if final_value else None, current.review_status
            )
            canonical_status = {
                "CONFIRMED_VIOLATION": "confirmed",
                "NOT_A_VIOLATION": "rejected",
                "PENDING": "pending",
            }[canonical_final]
        else:
            canonical_status = _canonical_review_status(
                str(status_value), current.ai_result, str(final_value) if final_value else None
            )
            canonical_final = _canonical_final_decision(
                str(final_value) if final_value else None, canonical_status
            )
        now = _datetime(changes.get("reviewed_at") or datetime.now(timezone.utc))
        status_or_decision_changed = bool(
            {"review_status", "final_decision"}.intersection(changes)
        )
        reviewed_by = changes.get("reviewed_by", current.reviewed_by)
        review_note = changes.get("review_note", current.review_note)
        history_item = {
            "review_status": canonical_status,
            "final_decision": canonical_final,
            "reviewed_by": reviewed_by,
            "reviewed_at": now,
            "review_note": review_note,
        }
        set_values: dict[str, Any] = {}
        if status_or_decision_changed:
            set_values.update({
                "review_status": canonical_status,
                "final_decision": canonical_final,
            })
        for field in ("reviewed_by", "review_note"):
            if field in changes:
                set_values[field] = changes[field]
        if "reviewed_at" in changes or status_or_decision_changed:
            set_values["reviewed_at"] = now

        async def update():
            await self.db.violations.update_one(
                {"event_id": event_id},
                {"$set": set_values, "$push": {"review_history": history_item}},
            )

        self._run(update())
        return self.get_violation(event_id)

    # Settings
    def get_settings(self) -> SystemSettings:
        async def read():
            return [doc async for doc in self.db.system_settings.find()]

        values = {doc["key"]: doc.get("value") for doc in self._run(read())}
        defaults = SystemSettings().model_dump()
        extra = values.pop("extra", {}) or {}
        known = {key: values.get(key, default) for key, default in defaults.items() if key != "extra"}
        return SystemSettings(**known, extra=extra)

    def save_settings(self, new_settings: SystemSettings) -> SystemSettings:
        now = datetime.now(timezone.utc)
        values = new_settings.model_dump()

        async def save():
            for key, value in values.items():
                await self.db.system_settings.update_one(
                    {"key": key},
                    {"$set": {"value": value, "updated_by": "api", "updated_at": now}},
                    upsert=True,
                )

        self._run(save())
        return new_settings

    # Aggregations for Mongo-backed reporting and explain verification.
    def get_stats_summary(self) -> dict[str, Any]:
        pipeline = [{"$group": {
            "_id": None,
            "total_vehicles": {"$sum": 1},
            "helmet_ok": {"$sum": {"$cond": [{"$eq": ["$result", "HELMET"]}, 1, 0]}},
            "helmet_bad": {"$sum": {"$cond": [{"$eq": ["$result", "NO_HELMET"]}, 1, 0]}},
            "seatbelt_ok": {"$sum": {"$cond": [{"$eq": ["$result", "SEATBELT"]}, 1, 0]}},
            "seatbelt_bad": {"$sum": {"$cond": [{"$eq": ["$result", "NO_SEATBELT"]}, 1, 0]}},
            "needs_review": {"$sum": {"$cond": [{"$eq": ["$result", "NEEDS_REVIEW"]}, 1, 0]}},
        }}]

        async def aggregate():
            cursor = await self.db.vehicle_events.aggregate(pipeline)
            rows = [row async for row in cursor]
            return rows[0] if rows else {}

        row = self._run(aggregate())
        helmet_den = row.get("helmet_ok", 0) + row.get("helmet_bad", 0)
        seatbelt_den = row.get("seatbelt_ok", 0) + row.get("seatbelt_bad", 0)
        compliant = row.get("helmet_ok", 0) + row.get("seatbelt_ok", 0)
        violations = row.get("helmet_bad", 0) + row.get("seatbelt_bad", 0)
        review_statuses = self._run(self._review_status_counts())
        return {
            "total_vehicles": row.get("total_vehicles", 0),
            "total_violations": violations,
            "compliant_vehicles": compliant,
            "violations": violations,
            "needs_review": row.get("needs_review", 0),
            "compliance_percentage": round(compliant * 100 / (compliant + violations), 2) if compliant + violations else 100.0,
            "reviewed_count": review_statuses["reviewed"],
            "unreviewed_count": review_statuses["pending"],
            "helmet_compliance_percentage": round(row.get("helmet_ok", 0) * 100 / helmet_den, 2) if helmet_den else 100.0,
            "seatbelt_compliance_percentage": round(row.get("seatbelt_ok", 0) * 100 / seatbelt_den, 2) if seatbelt_den else 100.0,
            "review_count": row.get("needs_review", 0),
        }

    async def _review_status_counts(self) -> dict[str, int]:
        pipeline = [{"$group": {
            "_id": "$review_status",
            "count": {"$sum": 1},
        }}]
        cursor = await self.db.violations.aggregate(pipeline)
        rows = [row async for row in cursor]
        counts = {row["_id"]: int(row["count"]) for row in rows}
        return {
            "reviewed": counts.get("confirmed", 0) + counts.get("rejected", 0),
            "pending": counts.get("pending", 0),
        }

    def get_stats_daily(self) -> list[dict[str, Any]]:
        pipeline = [
            {"$group": {"_id": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$timestamp"}}, "result": "$result"}, "count": {"$sum": 1}}},
            {"$sort": {"_id.day": -1}},
        ]

        async def aggregate():
            cursor = await self.db.vehicle_events.aggregate(pipeline)
            return [row async for row in cursor]

        rows = self._run(aggregate())
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            day = row["_id"]["day"]
            result = row["_id"]["result"]
            values = grouped.setdefault(day, {"total": 0, "compliant": 0, "violations": 0, "needs_review": 0})
            values["total"] += row["count"]
            if result in {"HELMET", "SEATBELT"}:
                values["compliant"] += row["count"]
            elif result in {"NO_HELMET", "NO_SEATBELT"}:
                values["violations"] += row["count"]
            elif result == "NEEDS_REVIEW":
                values["needs_review"] += row["count"]
        return [
            {
                "date": day,
                "total_vehicles": value["total"],
                "compliant_vehicles": value["compliant"],
                "violations": value["violations"],
                "needs_review": value["needs_review"],
                "compliance_percentage": round(value["compliant"] * 100 / (value["compliant"] + value["violations"]), 2) if value["compliant"] + value["violations"] else 100.0,
            }
            for day, value in sorted(grouped.items(), reverse=True)
        ]

    def get_stats_per_camera(self) -> list[dict[str, Any]]:
        pipeline = [
            {"$group": {"_id": {"camera_id": "$camera_id", "result": "$result"}, "count": {"$sum": 1}}},
            {"$sort": {"_id.camera_id": 1}},
        ]

        async def aggregate():
            cursor = await self.db.vehicle_events.aggregate(pipeline)
            return [row async for row in cursor]

        rows = self._run(aggregate())
        cameras = {camera.camera_id: camera.name for camera in self.list_cameras()}
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            camera_id = row["_id"]["camera_id"]
            result = row["_id"]["result"]
            values = grouped.setdefault(camera_id, {"total": 0, "compliant": 0, "violations": 0, "needs_review": 0})
            values["total"] += row["count"]
            if result in {"HELMET", "SEATBELT"}:
                values["compliant"] += row["count"]
            elif result in {"NO_HELMET", "NO_SEATBELT"}:
                values["violations"] += row["count"]
            elif result == "NEEDS_REVIEW":
                values["needs_review"] += row["count"]
        return [
            {
                "camera_id": camera_id,
                "camera_name": cameras.get(camera_id, camera_id),
                "total_vehicles": value["total"],
                "compliant_vehicles": value["compliant"],
                "violations": value["violations"],
                "needs_review": value["needs_review"],
                "compliance_percentage": round(value["compliant"] * 100 / (value["compliant"] + value["violations"]), 2) if value["compliant"] + value["violations"] else 100.0,
            }
            for camera_id, value in sorted(grouped.items())
        ]

    @staticmethod
    def _winning_plan_index_names(plan: Any) -> set[str]:
        """Collect index names from the winning plan only, excluding rejected plans."""
        names: set[str] = set()

        def visit(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("stage") == "IXSCAN" and node.get("indexName"):
                    names.add(str(node["indexName"]))
                for key, value in node.items():
                    if key != "rejectedPlans":
                        visit(value)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    visit(value)

        visit(plan)
        return names

    @staticmethod
    def _plan_status(winning_plan: Any, expected_index: str) -> str:
        indexes = MongoRepository._winning_plan_index_names(winning_plan)
        if expected_index in indexes:
            return "IXSCAN"
        if indexes:
            return "IXSCAN_OTHER"

        def has_stage(node: Any, stage: str) -> bool:
            if isinstance(node, dict):
                return node.get("stage") == stage or any(
                    has_stage(value, stage)
                    for key, value in node.items()
                    if key != "rejectedPlans"
                )
            if isinstance(node, (list, tuple)):
                return any(has_stage(value, stage) for value in node)
            return False

        return "COLLSCAN" if has_stage(winning_plan, "COLLSCAN") else "UNKNOWN"

    def explain_main_queries(self) -> dict[str, str]:
        async def explain():
            checks = {
                "vehicle_events_camera_timestamp": await self.db.command({
                    "explain": {"find": "vehicle_events", "filter": {"camera_id": "__explain__"}, "sort": {"timestamp": -1}},
                    "verbosity": "queryPlanner",
                }),
                "violations_review_status": await self.db.command({
                    "explain": {"find": "violations", "filter": {"review_status": "pending"}},
                    "verbosity": "queryPlanner",
                }),
            }
            return {
                name: self._plan_status(
                    result.get("queryPlanner", {}).get("winningPlan"), name
                )
                for name, result in checks.items()
            }

        return self._run(explain())
