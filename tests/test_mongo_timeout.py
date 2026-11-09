"""Unit tests for Mongo coroutine deadlines without MongoDB or model imports."""
from __future__ import annotations

import asyncio
from threading import Event, Lock, Thread

import pytest

from backend.app.core.config import Settings
from backend.app.db import mongo as mongo_module
from backend.app.db.mongo import MongoDatabase, MongoOperationTimeout, MongoShutdownTimeout


@pytest.fixture
def loop_only_database():
    database = MongoDatabase.__new__(MongoDatabase)
    database.operation_timeout_seconds = 0.03
    database._loop = asyncio.new_event_loop()
    database._started = Event()
    database._state_lock = Lock()
    database._close_lock = Lock()
    database._active_runs = 0
    database._active_runs_empty = Event()
    database._active_runs_empty.set()
    database._closing = False
    database._closed = False
    database._client = None
    database._client_close_future = None
    database._thread = Thread(target=database._run_loop, daemon=True)
    database._thread.start()
    assert database._started.wait(timeout=2)
    try:
        yield database
    finally:
        if database._thread.is_alive():
            database.close(timeout=2)


def test_operation_timeout_cancels_and_awaits_pending_coroutine(loop_only_database, monkeypatch):
    started = Event()
    cancelled = Event()
    submitted = []
    submit = asyncio.run_coroutine_threadsafe

    def capture_future(coroutine, loop):
        future = submit(coroutine, loop)
        submitted.append(future)
        return future

    monkeypatch.setattr(mongo_module.asyncio, "run_coroutine_threadsafe", capture_future)

    async def slow_operation():
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    with pytest.raises(MongoOperationTimeout, match="timed out after 0.03 seconds"):
        loop_only_database.run(slow_operation())

    assert started.is_set()
    assert cancelled.wait(timeout=1)
    assert submitted[0].done()

    async def count_other_tasks():
        current = asyncio.current_task()
        return sum(task is not current for task in asyncio.all_tasks())

    # The one remaining task is run()'s normal wrapper for this inspection call.
    assert loop_only_database.run(count_other_tasks()) == 1


def test_mongo_operation_timeout_defaults_to_thirty_seconds(monkeypatch):
    monkeypatch.delenv("MONGO_OPERATION_TIMEOUT_SECONDS", raising=False)
    config = Settings(SECRET_KEY="test-secret-key-long-enough-for-validation", _env_file=None)
    assert config.MONGO_OPERATION_TIMEOUT_SECONDS == 30.0


def test_close_confirms_event_loop_thread_has_stopped():
    database = MongoDatabase.__new__(MongoDatabase)
    database.operation_timeout_seconds = 1
    database._loop = asyncio.new_event_loop()
    database._started = Event()
    database._state_lock = Lock()
    database._close_lock = Lock()
    database._active_runs = 0
    database._active_runs_empty = Event()
    database._active_runs_empty.set()
    database._closing = False
    database._closed = False
    database._client = None
    database._client_close_future = None
    database._thread = Thread(target=database._run_loop, daemon=True)
    database._thread.start()
    assert database._started.wait(timeout=2)

    database.close(timeout=2)

    assert not database._thread.is_alive()
    assert database._loop.is_closed()
    assert database._closed


def test_close_timeout_leaves_loop_open_for_pending_client_close():
    database = MongoDatabase.__new__(MongoDatabase)
    database.operation_timeout_seconds = 1
    database._loop = asyncio.new_event_loop()
    database._started = Event()
    database._state_lock = Lock()
    database._close_lock = Lock()
    database._active_runs = 0
    database._active_runs_empty = Event()
    database._active_runs_empty.set()
    database._closing = False
    database._closed = False
    database._client_close_future = None

    class SlowClient:
        async def close(self):
            await asyncio.sleep(10)

    database._client = SlowClient()
    database._thread = Thread(target=database._run_loop, daemon=True)
    database._thread.start()
    assert database._started.wait(timeout=2)

    with pytest.raises(MongoShutdownTimeout, match="event loop remains open"):
        database.close(timeout=0.02)

    assert database._thread.is_alive()
    assert not database._loop.is_closed()
    database._loop.call_soon_threadsafe(database._loop.stop)
    database._thread.join(timeout=2)
    assert not database._thread.is_alive()


def test_close_does_not_close_client_or_loop_while_repository_operation_runs(loop_only_database):
    loop_only_database.operation_timeout_seconds = 10
    started = Event()
    release = asyncio.Event()

    async def pending_operation():
        started.set()
        await release.wait()

    operation_thread = Thread(target=lambda: loop_only_database.run(pending_operation()))
    operation_thread.start()
    assert started.wait(timeout=1)

    with pytest.raises(MongoShutdownTimeout, match="Mongo operations are still active"):
        loop_only_database.close(timeout=0.02)

    assert loop_only_database._thread.is_alive()
    assert not loop_only_database._loop.is_closed()
    assert not loop_only_database._closing
    loop_only_database._loop.call_soon_threadsafe(release.set)
    operation_thread.join(timeout=1)
    assert not operation_thread.is_alive()
