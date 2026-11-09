"""FastAPI dependencies for repository, authentication, roles, and rate limiting."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import time
from typing import Callable
from fastapi import Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.config import settings
from backend.app.core.security import decode_access_token
from backend.app.db.json_repo import JsonFileRepository
from backend.app.db.repository import Repository
from backend.app.models.user import User, UserRole

# Global singleton repository
_repo: Repository | None = None


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        if settings.REPO_BACKEND == "mongo":
            from backend.app.db.mongo_repo import MongoRepository

            _repo = MongoRepository()
        else:
            _repo = JsonFileRepository()
    return _repo


def set_repository(repo: Repository) -> None:
    global _repo
    _repo = repo


# Login failure rate limiter: username -> list of failure timestamps
_login_failures: dict[str, list[float]] = defaultdict(list)
FAILURE_WINDOW_SEC = 15 * 60  # 15 minutes
MAX_FAILURES = 5


def check_login_rate_limit(username: str) -> None:
    now = time.time()
    recent = [ts for ts in _login_failures[username] if now - ts < FAILURE_WINDOW_SEC]
    _login_failures[username] = recent
    if len(recent) >= MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 15 minutes.",
        )


def record_login_failure(username: str) -> None:
    _login_failures[username].append(time.time())


def reset_login_failures(username: str) -> None:
    _login_failures.pop(username, None)


security_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    repo: Repository = Depends(get_repository),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {err}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = repo.get_user_by_id(str(user_id))
    if user is None:
        # Check by username as fallback if sub stored username
        user = repo.get_user_by_username(str(user_id))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorized. Allowed: {list(allowed_roles)}",
            )
        return current_user
    return role_checker


def get_user_from_token_str(token: str, repo: Repository) -> User | None:
    """Helper to validate token passed in query strings (e.g. MJPEG stream, WebSocket)."""
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = repo.get_user_by_id(str(user_id)) or repo.get_user_by_username(str(user_id))
    if user and user.is_active:
        return user
    return None
