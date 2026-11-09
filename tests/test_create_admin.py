"""Offline lifecycle checks for the admin creation script."""
from __future__ import annotations

import pytest

from backend.app.core import config
from scripts import create_admin


class FakeRepository:
    def __init__(self, existing=None, *, fail_lookup=False):
        self.existing = existing
        self.fail_lookup = fail_lookup
        self.saved = None
        self.closed = False

    def get_user_by_username(self, _username):
        if self.fail_lookup:
            raise RuntimeError("synthetic repository failure")
        return self.existing

    def save_user(self, user):
        self.saved = user
        return user

    def close(self):
        self.closed = True


def _prepare(monkeypatch, repository):
    monkeypatch.setattr(config.settings, "REPO_BACKEND", "json")
    monkeypatch.setattr(create_admin, "JsonFileRepository", lambda: repository)
    monkeypatch.setattr(create_admin, "get_password_hash", lambda _password: "synthetic-hash")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "new-admin")


def test_admin_repository_closes_after_success(monkeypatch):
    repository = FakeRepository()
    _prepare(monkeypatch, repository)
    answers = iter(("safe-pass", "safe-pass"))
    monkeypatch.setattr(create_admin.getpass, "getpass", lambda _prompt: next(answers))

    create_admin.main()

    assert repository.saved is not None
    assert repository.saved.hashed_password == "synthetic-hash"
    assert repository.closed


def test_admin_repository_closes_after_repository_failure(monkeypatch):
    repository = FakeRepository(fail_lookup=True)
    _prepare(monkeypatch, repository)

    with pytest.raises(RuntimeError, match="synthetic repository failure"):
        create_admin.main()

    assert repository.closed


def test_admin_repository_closes_after_password_prompt_cancellation(monkeypatch):
    repository = FakeRepository()
    _prepare(monkeypatch, repository)

    def cancel(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(create_admin.getpass, "getpass", cancel)
    with pytest.raises(KeyboardInterrupt):
        create_admin.main()

    assert repository.closed


def test_admin_repository_closes_when_existing_user_creation_is_declined(monkeypatch):
    from backend.app.models.user import User

    repository = FakeRepository(existing=User(
        id="synthetic-user-id", username="new-admin", hashed_password="synthetic-hash", role="admin"
    ))
    _prepare(monkeypatch, repository)
    answers = iter(("new-admin", "n"))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    create_admin.main()

    assert repository.saved is None
    assert repository.closed
