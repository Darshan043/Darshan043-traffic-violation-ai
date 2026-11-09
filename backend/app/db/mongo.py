"""MongoDB connection and idempotent collection/index setup."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from threading import Event, Lock, Thread, current_thread
import time
from typing import Any, Coroutine, TypeVar

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import PyMongoError

T = TypeVar("T")


class MongoOperationTimeout(TimeoutError):
    """A Mongo operation exceeded its configured wait while cancellation completed."""


class MongoShutdownTimeout(TimeoutError):
    """Mongo resources did not finish shutting down within the allowed wait."""

COLLECTION_NAMES = (
    "users",
    "cameras",
    "vehicle_events",
    "violations",
    "system_settings",
)


async def create_indexes(database: Any) -> None:
    """Create named indexes on every collection; safe to call at each startup."""
    await database.users.create_index(
        [("username", ASCENDING)], unique=True, name="users_username_unique"
    )
    await database.cameras.create_index(
        [("camera_id", ASCENDING)], unique=True, name="cameras_camera_id_unique"
    )
    await database.vehicle_events.create_index(
        [("event_id", ASCENDING)], unique=True, name="vehicle_events_event_id_unique"
    )
    await database.vehicle_events.create_index(
        [("camera_id", ASCENDING), ("timestamp", DESCENDING)],
        name="vehicle_events_camera_timestamp",
    )
    await database.violations.create_index(
        [("event_id", ASCENDING)], unique=True, name="violations_event_id_unique"
    )
    await database.violations.create_index(
        [("camera_id", ASCENDING), ("created_at", DESCENDING)],
        name="violations_camera_created_at",
    )
    await database.violations.create_index(
        [("review_status", ASCENDING)], name="violations_review_status"
    )
    await database.violations.create_index(
        [("violation_type", ASCENDING)], name="violations_violation_type"
    )
    await database.violations.create_index(
        [("track_id", ASCENDING)], name="violations_track_id"
    )
    await database.system_settings.create_index(
        [("key", ASCENDING)], unique=True, name="system_settings_key_unique"
    )


class MongoDatabase:
    """Keep AsyncMongoClient on one owned event loop behind the sync repo API."""

    def __init__(
        self,
        url: str,
        database_name: str,
        *,
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        if not url:
            raise ValueError("MONGO_URL is missing or empty")
        if operation_timeout_seconds <= 0:
            raise ValueError("Mongo operation timeout must be greater than zero")
        self.url = url
        self.database_name = database_name
        self.operation_timeout_seconds = float(operation_timeout_seconds)
        self._loop = asyncio.new_event_loop()
        self._started = Event()
        self._state_lock = Lock()
        self._close_lock = Lock()
        self._active_runs = 0
        self._active_runs_empty = Event()
        self._active_runs_empty.set()
        self._closing = False
        self._closed = False
        self._client_close_future: Future | None = None
        self._thread = Thread(
            target=self._run_loop,
            name="traffic-ai-mongo-loop",
            daemon=True,
        )
        self._thread.start()
        if not self._started.wait(timeout=5):
            raise RuntimeError("MongoDB event loop did not start")
        self._client: AsyncMongoClient | None = None
        self._database: Any = None
        try:
            self.run(self._connect())
        except Exception as error:
            self.close()
            # Driver exception strings may include connection details.
            if isinstance(error, PyMongoError):
                raise RuntimeError(
                    f"MongoDB connection failed ({type(error).__name__})"
                ) from None
            raise

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    def run(self, coroutine: Coroutine[Any, Any, T]) -> T:
        with self._state_lock:
            if self._closing or self._closed:
                coroutine.close()
                raise RuntimeError("MongoDB is shutting down")
            self._active_runs += 1
            self._active_runs_empty.clear()

        async def run_with_timeout() -> T:
            operation = asyncio.create_task(coroutine)
            try:
                return await asyncio.wait_for(
                    operation,
                    timeout=self.operation_timeout_seconds,
                )
            except asyncio.TimeoutError:
                if not operation.done():
                    operation.cancel()
                # wait_for normally waits for cancellation itself; gather makes
                # completion explicit before the concurrent future is resolved.
                await asyncio.gather(operation, return_exceptions=True)
                raise MongoOperationTimeout(
                    f"MongoDB operation timed out after "
                    f"{self.operation_timeout_seconds:g} seconds"
                ) from None
            except asyncio.CancelledError:
                if not operation.done():
                    operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
                raise

        try:
            future = asyncio.run_coroutine_threadsafe(run_with_timeout(), self._loop)
            # Do not impose a second concurrent-future timeout here. The coroutine
            # above owns the deadline and does not finish until cancellation ends.
            return future.result()
        finally:
            with self._state_lock:
                self._active_runs -= 1
                if self._active_runs == 0:
                    self._active_runs_empty.set()

    async def _connect(self) -> None:
        self._client = AsyncMongoClient(
            self.url,
            tz_aware=True,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
        self._database = self._client[self.database_name]
        await self._client.admin.command("ping")
        await create_indexes(self._database)

    @property
    def database(self) -> Any:
        if self._database is None:
            raise RuntimeError("MongoDB has not been initialized")
        return self._database

    def close(self, timeout: float | None = None) -> None:
        if not self._close_lock.acquire(blocking=False):
            raise MongoShutdownTimeout("Mongo shutdown is already in progress")
        try:
            self._close_impl(timeout)
        finally:
            self._close_lock.release()

    def _close_impl(self, timeout: float | None = None) -> None:
        if current_thread() is self._thread:
            raise RuntimeError("MongoDB cannot be closed from its event-loop thread")
        if not self._thread.is_alive():
            self._closed = True
            return
        wait_seconds = (
            max(5.0, self.operation_timeout_seconds + 5.0)
            if timeout is None else max(0.0, float(timeout))
        )
        deadline = time.monotonic() + wait_seconds
        with self._state_lock:
            self._closing = True
        if not self._active_runs_empty.wait(timeout=max(0.0, deadline - time.monotonic())):
            with self._state_lock:
                self._closing = False
            raise MongoShutdownTimeout("Mongo operations are still active; resources remain open")

        if self._client is not None:
            if self._client_close_future is None:
                self._client_close_future = asyncio.run_coroutine_threadsafe(
                    self._client.close(), self._loop
                )
            try:
                self._client_close_future.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeoutError:
                # Keep the loop alive and reject new operations. A later close()
                # call can wait for this same close operation to finish.
                raise MongoShutdownTimeout("Mongo client close timed out; event loop remains open") from None
            except Exception as error:
                raise RuntimeError(
                    f"Mongo client close failed ({type(error).__name__}); event loop remains open"
                ) from None
            self._client = None
            self._client_close_future = None

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._thread.is_alive():
            raise MongoShutdownTimeout("Mongo event-loop thread did not stop; loop remains open")
        self._closed = True
