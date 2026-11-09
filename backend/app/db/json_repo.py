"""JSON-file repository implementation backed by filelock."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from filelock import FileLock

from backend.app.core.config import settings
from backend.app.db.repository import Repository
from backend.app.models.camera import Camera
from backend.app.models.event import VehicleEvent
from backend.app.models.settings import SystemSettings
from backend.app.models.user import User
from backend.app.models.violation import Violation


class JsonFileRepository(Repository):
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or settings.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.data_dir / "db.lock"
        self._lock = FileLock(str(self.lock_path), timeout=10.0)

        self.users_file = self.data_dir / "users.json"
        self.cameras_file = self.data_dir / "cameras.json"
        self.events_file = self.data_dir / "vehicle_events.json"
        self.violations_file = self.data_dir / "violations.json"
        self.settings_file = self.data_dir / "system_settings.json"

    def _read_json(self, file_path: Path, default: Any) -> Any:
        if not file_path.is_file():
            return default
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, file_path: Path, data: Any) -> None:
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(file_path)

    # --- Users ---
    def get_user_by_id(self, user_id: str) -> User | None:
        with self._lock:
            data = self._read_json(self.users_file, {})
            user_dict = data.get(user_id)
            return User(**user_dict) if user_dict else None

    def get_user_by_username(self, username: str) -> User | None:
        with self._lock:
            data = self._read_json(self.users_file, {})
            for item in data.values():
                if item.get("username") == username:
                    return User(**item)
            return None

    def list_users(self) -> list[User]:
        with self._lock:
            data = self._read_json(self.users_file, {})
            return [User(**item) for item in data.values()]

    def save_user(self, user: User) -> User:
        with self._lock:
            data = self._read_json(self.users_file, {})
            data[user.id] = user.model_dump()
            self._write_json(self.users_file, data)
            return user

    def update_user(self, user_id: str, updates: dict[str, Any]) -> User | None:
        with self._lock:
            data = self._read_json(self.users_file, {})
            if user_id not in data:
                return None
            user_data = data[user_id]
            for key, val in updates.items():
                if val is not None:
                    user_data[key] = val
            data[user_id] = user_data
            self._write_json(self.users_file, data)
            return User(**user_data)

    def record_login(self, user_id: str) -> User | None:
        return self.update_user(user_id, {"last_login_at": datetime.now(timezone.utc).isoformat()})

    # --- Cameras ---
    def get_camera(self, camera_id: str) -> Camera | None:
        with self._lock:
            data = self._read_json(self.cameras_file, {})
            cam_dict = data.get(camera_id)
            return Camera(**cam_dict) if cam_dict else None

    def list_cameras(self) -> list[Camera]:
        with self._lock:
            data = self._read_json(self.cameras_file, {})
            return [Camera(**item) for item in data.values()]

    def save_camera(self, camera: Camera) -> Camera:
        with self._lock:
            data = self._read_json(self.cameras_file, {})
            data[camera.camera_id] = camera.model_dump()
            self._write_json(self.cameras_file, data)
            return camera

    def update_camera(self, camera_id: str, updates: dict[str, Any]) -> Camera | None:
        with self._lock:
            data = self._read_json(self.cameras_file, {})
            if camera_id not in data:
                return None
            cam_data = data[camera_id]
            for key, val in updates.items():
                if val is not None:
                    cam_data[key] = val
            data[camera_id] = cam_data
            self._write_json(self.cameras_file, data)
            return Camera(**cam_data)

    def delete_camera(self, camera_id: str) -> bool:
        with self._lock:
            data = self._read_json(self.cameras_file, {})
            if camera_id in data:
                del data[camera_id]
                self._write_json(self.cameras_file, data)
                return True
            return False

    # --- Vehicle Events ---
    def save_vehicle_event(self, event: VehicleEvent) -> VehicleEvent:
        with self._lock:
            data = self._read_json(self.events_file, [])
            data.append(event.model_dump())
            self._write_json(self.events_file, data)
            return event

    def list_vehicle_events(self, camera_id: str | None = None) -> list[VehicleEvent]:
        with self._lock:
            data = self._read_json(self.events_file, [])
            events = [VehicleEvent(**item) for item in data]
            if camera_id:
                events = [e for e in events if e.camera_id == camera_id]
            return events

    # --- Violations ---
    def get_violation(self, event_id: str) -> Violation | None:
        with self._lock:
            data = self._read_json(self.violations_file, {})
            v_dict = data.get(event_id)
            return Violation(**v_dict) if v_dict else None

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
        with self._lock:
            data = self._read_json(self.violations_file, {})
            violations = [Violation(**item) for item in data.values()]

        # Apply filters
        if violation_type:
            violations = [v for v in violations if v.violation_type == violation_type]
        if ai_result:
            violations = [v for v in violations if v.ai_result == ai_result]
        if camera_id:
            violations = [v for v in violations if v.camera_id == camera_id]
        if track_id is not None:
            violations = [v for v in violations if v.track_id == track_id]
        if review_status:
            violations = [v for v in violations if v.review_status == review_status]
        if date_from:
            violations = [v for v in violations if v.created_at >= date_from]
        if date_to:
            violations = [v for v in violations if v.created_at <= date_to]

        # Sort newest first
        violations.sort(key=lambda v: v.created_at, reverse=True)
        total_count = len(violations)
        start = max(0, (page - 1) * limit)
        end = start + limit
        return violations[start:end], total_count

    def save_violation(self, violation: Violation) -> Violation:
        with self._lock:
            data = self._read_json(self.violations_file, {})
            data[violation.event_id] = violation.model_dump()
            self._write_json(self.violations_file, data)
            return violation

    def update_violation(self, event_id: str, updates: dict[str, Any]) -> Violation | None:
        with self._lock:
            data = self._read_json(self.violations_file, {})
            if event_id not in data:
                return None
            v_data = data[event_id]
            for key, val in updates.items():
                if val is not None:
                    v_data[key] = val
            data[event_id] = v_data
            self._write_json(self.violations_file, data)
            return Violation(**v_data)

    # --- System Settings ---
    def get_settings(self) -> SystemSettings:
        with self._lock:
            data = self._read_json(self.settings_file, None)
            if data is None:
                default_settings = SystemSettings()
                self._write_json(self.settings_file, default_settings.model_dump())
                return default_settings
            return SystemSettings(**data)

    def save_settings(self, new_settings: SystemSettings) -> SystemSettings:
        with self._lock:
            self._write_json(self.settings_file, new_settings.model_dump())
            return new_settings
