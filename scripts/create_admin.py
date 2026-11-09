"""Script to securely create an admin user from terminal prompts."""
from __future__ import annotations

import getpass
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.security import get_password_hash
from backend.app.db.json_repo import JsonFileRepository
from backend.app.models.user import User
from backend.app.core.config import settings


def main() -> None:
    print("=== Create Traffic AI Admin User ===")
    username = input("Enter admin username [admin]: ").strip() or "admin"

    if settings.REPO_BACKEND == "mongo":
        from backend.app.db.mongo_repo import MongoRepository

        repo = MongoRepository()
    else:
        repo = JsonFileRepository()
    try:
        existing = repo.get_user_by_username(username)
        if existing:
            print(f"User '{username}' already exists. Overwrite? (y/N): ", end="")
            if input().strip().lower() != "y":
                print("Aborted.")
                return

        password = getpass.getpass("Enter admin password: ")
        if len(password) < 6:
            print("Error: Password must be at least 6 characters.")
            sys.exit(1)

        confirm = getpass.getpass("Confirm admin password: ")
        if password != confirm:
            print("Error: Passwords do not match.")
            sys.exit(1)

        user_id = existing.id if existing else str(uuid.uuid4())
        user = User(
            id=user_id,
            username=username,
            hashed_password=get_password_hash(password),
            role="admin",
            is_active=True,
        )
        repo.save_user(user)
        print(f"Successfully created admin user '{username}' (id: {user_id}).")
    finally:
        close = getattr(repo, "close", None)
        if close:
            close()


if __name__ == "__main__":
    main()
