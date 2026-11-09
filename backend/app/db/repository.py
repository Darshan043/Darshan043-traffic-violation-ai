"""Abstract Repository interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from backend.app.models.camera import Camera
from backend.app.models.event import VehicleEvent
from backend.app.models.settings import SystemSettings
from backend.app.models.user import User
from backend.app.models.violation import Violation


class Repository(ABC):
    # --- Users ---
    @abstractmethod
    def get_user_by_id(self, user_id: str) -> User | None:
        pass

    @abstractmethod
    def get_user_by_username(self, username: str) -> User | None:
        pass

    @abstractmethod
    def list_users(self) -> list[User]:
        pass

    @abstractmethod
    def save_user(self, user: User) -> User:
        pass

    @abstractmethod
    def update_user(self, user_id: str, updates: dict[str, Any]) -> User | None:
        pass

    def record_login(self, user_id: str) -> User | None:
        """Record a successful login; optional repositories can override this."""
        return self.update_user(user_id, {"last_login_at": datetime.now(timezone.utc).isoformat()})

    # --- Cameras ---
    @abstractmethod
    def get_camera(self, camera_id: str) -> Camera | None:
        pass

    @abstractmethod
    def list_cameras(self) -> list[Camera]:
        pass

    @abstractmethod
    def save_camera(self, camera: Camera) -> Camera:
        pass

    @abstractmethod
    def update_camera(self, camera_id: str, updates: dict[str, Any]) -> Camera | None:
        pass

    @abstractmethod
    def delete_camera(self, camera_id: str) -> bool:
        pass

    # --- Vehicle Events ---
    @abstractmethod
    def save_vehicle_event(self, event: VehicleEvent) -> VehicleEvent:
        pass

    @abstractmethod
    def list_vehicle_events(self, camera_id: str | None = None) -> list[VehicleEvent]:
        pass

    # --- Violations ---
    @abstractmethod
    def get_violation(self, event_id: str) -> Violation | None:
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def save_violation(self, violation: Violation) -> Violation:
        pass

    @abstractmethod
    def update_violation(self, event_id: str, updates: dict[str, Any]) -> Violation | None:
        pass

    def iter_violations(self, **filters: Any):
        """Yield filtered violations in pages for export callers."""
        page = 1
        while True:
            items, total = self.list_violations(page=page, limit=500, **filters)
            if not items:
                return
            yield from items
            if page * 500 >= total:
                return
            page += 1

    # --- System Settings ---
    @abstractmethod
    def get_settings(self) -> SystemSettings:
        pass

    @abstractmethod
    def save_settings(self, settings: SystemSettings) -> SystemSettings:
        pass
