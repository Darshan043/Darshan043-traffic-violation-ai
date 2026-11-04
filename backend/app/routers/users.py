"""User management router (admin-only)."""
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.security import get_password_hash
from backend.app.db.repository import Repository
from backend.app.deps import get_current_user, get_repository, require_role
from backend.app.models.user import User, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
def list_users(
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> list[UserResponse]:
    users = repo.list_users()
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> UserResponse:
    existing = repo.get_user_by_username(payload.username)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Username '{payload.username}' already exists",
        )

    user = User(
        id=str(uuid.uuid4()),
        username=payload.username,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
        is_active=True,
    )
    saved = repo.save_user(user)
    return UserResponse(
        id=saved.id,
        username=saved.username,
        role=saved.role,
        is_active=saved.is_active,
        created_at=saved.created_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    payload: UserUpdate,
    current_user: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> UserResponse:
    user = repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # An admin cannot disable themselves
    if user_id == current_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin cannot disable themselves",
        )

    updates = {}
    if payload.role is not None:
        updates["role"] = payload.role
    if payload.is_active is not None:
        updates["is_active"] = payload.is_active
    if payload.password:
        updates["hashed_password"] = get_password_hash(payload.password)

    updated = repo.update_user(user_id, updates)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserResponse(
        id=updated.id,
        username=updated.username,
        role=updated.role,
        is_active=updated.is_active,
        created_at=updated.created_at,
    )


@router.delete("/{user_id}", response_model=UserResponse)
def delete_user(
    user_id: str,
    current_user: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> UserResponse:
    """Disable instead of delete; an admin cannot disable themselves."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin cannot disable themselves",
        )

    user = repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updated = repo.update_user(user_id, {"is_active": False})
    assert updated is not None
    return UserResponse(
        id=updated.id,
        username=updated.username,
        role=updated.role,
        is_active=updated.is_active,
        created_at=updated.created_at,
    )
