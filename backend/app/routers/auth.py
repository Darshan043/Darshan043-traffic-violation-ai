"""Authentication router: login, token issuance, and current user info."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.core.security import create_access_token, verify_password
from backend.app.db.repository import Repository
from backend.app.deps import (
    check_login_rate_limit,
    get_current_user,
    get_repository,
    record_login_failure,
    reset_login_failures,
)
from backend.app.models.user import LoginRequest, TokenResponse, User, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    repo: Repository = Depends(get_repository),
) -> TokenResponse:
    check_login_rate_limit(payload.username)

    user = repo.get_user_by_username(payload.username)
    if user is None or not user.is_active or not verify_password(payload.password, user.hashed_password):
        record_login_failure(payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    reset_login_failures(payload.username)
    user = repo.record_login(user.id) or user
    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
        ),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
    )
