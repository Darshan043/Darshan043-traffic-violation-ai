"""User and authentication models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

UserRole = Literal["admin", "reviewer", "viewer"]


class User(BaseModel):
    id: str
    username: str
    hashed_password: str
    full_name: str = ""
    role: UserRole
    is_active: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login_at: str | None = None


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    role: UserRole = "viewer"


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)


class UserResponse(BaseModel):
    id: str
    username: str
    role: UserRole
    is_active: bool
    created_at: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
