"""System settings router (admin-only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.db.repository import Repository
from backend.app.deps import get_repository, require_role
from backend.app.models.settings import SystemSettings
from backend.app.models.user import User

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SystemSettings)
def get_system_settings(
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> SystemSettings:
    return repo.get_settings()


@router.put("", response_model=SystemSettings)
def update_system_settings(
    payload: SystemSettings,
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> SystemSettings:
    return repo.save_settings(payload)
