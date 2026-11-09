"""Run the required Stage 8 API/video check without exposing credentials."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote, urlencode, urlsplit

from dotenv import load_dotenv
import httpx
import uvicorn
import websockets
from pymongo import AsyncMongoClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VIDEO = ROOT / "data" / "videos" / "helmet_test.mp4"
BASE = "http://127.0.0.1:8765"
CHECKS: list[tuple[str, bool]] = []
RESPONSE_BODIES: list[str] = []
STATUS_POLL_INTERVAL_SECONDS = 2.0
MANIFEST_LOG_FILES = (
    "cli_stdout.log",
    "cli_stderr.log",
    "storage/logs/backend.log",
)
EVIDENCE_DEFAULTS = {
    "cli_baseline_event_count": None,
    "first_run_mongo_event_count": None,
    "second_run_mongo_event_count": None,
    "second_run_added_event_count": None,
    "api_statistics_comparison_result": "NOT_RUN",
    "camera_processing_completion_result": "NOT_RUN",
    "websocket_finished_result": "NOT_RUN",
    "graceful_shutdown_result": "NOT_RUN",
    "failure_reason": None,
    "failure_step": None,
    "failure_exception_type": None,
    "failure_category": None,
    "failure_message": None,
}
_E2E_DATABASE_PATTERN = re.compile(r"^traffic_ai_test_[0-9a-f]{10}$")
_E2E_AUDIT_DATABASE = "traffic_ai_e2e_audit"
_E2E_AUDIT_COLLECTION = "e2e_runs"
_READ_ONLY_ACTIONS = frozenset({
    "changeStream",
    "collStats",
    "dbHash",
    "dbStats",
    "find",
    "killCursors",
    "listCollections",
    "listIndexes",
    "listSearchIndexes",
    "planCacheRead",
})


def _mongo_deployment_identity(uri: str) -> tuple[str, ...]:
    """Return endpoint identity without exposing URI credentials."""
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"mongodb", "mongodb+srv"} or not parsed.netloc:
        raise ValueError("Invalid MongoDB deployment identity")
    authority = parsed.netloc.rsplit("@", 1)[-1]
    hosts = []
    for seed in authority.split(","):
        parsed_seed = urlsplit(f"//{seed}")
        if not parsed_seed.hostname:
            raise ValueError("Invalid MongoDB deployment identity")
        port = parsed_seed.port if parsed_seed.port is not None else 27017
        hosts.append(f"{parsed_seed.hostname.rstrip('.').lower()}:{port}")
    return tuple(sorted(hosts))


def _new_e2e_database_name(
    configured_prefix: str | None,
    preauthorized_database_name: str | None = None,
) -> str:
    """Resolve a fresh random name or validate the exact name pre-authorized for this run."""
    if configured_prefix != "traffic_ai_test":
        raise RuntimeError("MONGO_TEST_DB must be traffic_ai_test")
    if preauthorized_database_name in (None, ""):
        database_name = f"{configured_prefix}_{uuid.uuid4().hex[:10]}"
    else:
        database_name = preauthorized_database_name.strip()
    if not _E2E_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError(
            "MONGO_TEST_DATABASE must match traffic_ai_test_<10 lowercase hexadecimal characters>"
        )
    return database_name


def _validate_e2e_isolation(
    database_name: str,
    isolation_confirmation: str | None,
    *,
    test_isolation_confirmation: str | None = None,
    test_url: str | None = None,
    readonly_url: str | None = None,
    production_url: str | None = None,
    repo_backend: str | None = None,
) -> None:
    """Require isolated E2E settings and prove test endpoints differ from production."""
    if isolation_confirmation != "1":
        raise RuntimeError(
            "Set MONGO_E2E_ISOLATED=1 only after confirming a separate isolated Mongo deployment"
        )
    if test_isolation_confirmation != "1":
        raise RuntimeError("MONGO_TEST_ISOLATED=1 is required for isolated E2E")
    if repo_backend != "mongo":
        raise RuntimeError("E2E requires REPO_BACKEND=mongo")
    if not _E2E_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError(
            "E2E requires database name traffic_ai_test_<10 lowercase hexadecimal characters>"
        )
    if not test_url:
        raise RuntimeError("MONGO_TEST_URL is required for isolated E2E writes")
    if not readonly_url:
        raise RuntimeError("MONGO_E2E_READONLY_URL is required for read-only inspection")
    if not production_url:
        raise RuntimeError("Production deployment identity cannot be verified")
    try:
        test_identity = _mongo_deployment_identity(test_url)
        readonly_identity = _mongo_deployment_identity(readonly_url)
        production_identity = _mongo_deployment_identity(production_url)
    except (TypeError, ValueError):
        raise RuntimeError("MongoDB deployment identity cannot be verified safely") from None
    if test_identity == production_identity:
        raise RuntimeError("MongoDB test deployment must differ from production")
    if readonly_identity != test_identity:
        raise RuntimeError("MONGO_E2E_READONLY_URL must use the isolated test deployment")


async def _assert_readonly_credentials(client, expected_database: str = _E2E_AUDIT_DATABASE) -> None:
    """Require an authenticated principal whose effective privileges are read-only."""
    try:
        status = await client.admin.command(
            {"connectionStatus": 1, "showPrivileges": True}
        )
    except Exception as error:
        category, message = _mongo_diagnostic(error)
        raise PriorRunInspectionError(
            "read-only credential connectionStatus verification",
            error,
            category,
            message,
        ) from None
    auth_info = status.get("authInfo", {})
    users = auth_info.get("authenticatedUsers", [])
    roles = auth_info.get("authenticatedUserRoles", [])
    privileges = auth_info.get("authenticatedUserPrivileges", [])
    if not users or not roles or not privileges:
        raise PriorRunInspectionError(
            "read-only credential principal and privilege verification",
            RuntimeError("unverifiable principal"),
            "readonly_principal_unverifiable",
            "The read-only connection did not return a verifiable authenticated principal and privileges.",
        )
    actions = {
        action
        for privilege in privileges
        for action in privilege.get("actions", [])
    }
    resources = [privilege.get("resource", {}) for privilege in privileges]
    if (not actions or not actions.issubset(_READ_ONLY_ACTIONS)
            or not resources or any(resource.get("db") != expected_database
                                   or resource.get("collection") not in {"", _E2E_AUDIT_COLLECTION}
                                   for resource in resources)):
        raise PriorRunInspectionError(
            "read-only credential privilege verification",
            RuntimeError("unverifiable privileges"),
            "readonly_privileges_unverifiable_or_write_capable",
            "The read-only connection has write-capable, over-scoped, or otherwise unverifiable privileges.",
        )


async def _verify_fresh_e2e_database(
    test_url: str,
    database_name: str,
    *,
    client_factory=AsyncMongoClient,
) -> None:
    if not _E2E_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError("Refusing to inspect a non-randomized E2E database")
    client = client_factory(
        test_url,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    try:
        database = client[database_name]
        if await database.list_collection_names():
            raise RuntimeError("Refusing to use a non-empty randomized E2E database")
    finally:
        await client.close()


def _create_e2e_repository(test_url: str, database_name: str):
    """Create and inject a repository explicitly bound to the E2E test database."""
    from backend.app.db.mongo import MongoDatabase
    from backend.app.db.mongo_repo import MongoRepository
    from backend.app.deps import get_repository, set_repository
    from backend.app.core.config import settings

    mongo = MongoDatabase(
        test_url,
        database_name,
        operation_timeout_seconds=settings.MONGO_OPERATION_TIMEOUT_SECONDS,
    )
    try:
        repository = MongoRepository(mongo=mongo)
        set_repository(repository)
        if get_repository() is not repository:
            repository.close()
            raise RuntimeError("E2E test repository could not be installed safely")
    except Exception:
        mongo.close()
        raise
    return repository


def _cli_environment(
    storage: Path,
    test_url: str,
    database_name: str,
) -> dict[str, str]:
    """Keep CLI local-only and ensure any accidental Mongo access stays isolated."""
    env = os.environ.copy()
    env["STORAGE_DIR"] = str(storage)
    env["TRAFFIC_AI_DEVICE"] = "cpu"
    env["REPO_BACKEND"] = "json"
    env["MONGO_URL"] = test_url
    env["MONGO_DB"] = database_name
    return env


def _configure_e2e_storage(temp_root: Path) -> Path:
    """Set up all backend file output under this run's temporary directory."""
    storage = temp_root / "storage"
    for child in ("data", "logs", "uploads", "evidence"):
        (storage / child).mkdir(parents=True, exist_ok=True)
    os.environ["STORAGE_DIR"] = str(storage)
    os.environ["TRAFFIC_AI_DEVICE"] = "cpu"
    return storage


def _redact_sensitive_text(text: str) -> str:
    """Redact credentials and bearer tokens before persisting subprocess output."""
    from backend.app.core.logging_config import SensitiveDataRedactionFilter

    text = SensitiveDataRedactionFilter.redact(text)
    text = re.sub(
        r"(?i)([\"']?(?:password|password_hash|hashed_password|access_token|refresh_token|"
        r"authorization|token|mongo_url|secret_key|api_key)[\"']?\s*[=:]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;&}]+)",
        r'\1"REDACTED"',
        text,
    )
    text = re.sub(r"(?i)mongodb(?:\+srv)?://[^\s'\"<>]+", "mongodb://REDACTED", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer REDACTED", text)
    text = re.sub(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "REDACTED_JWT",
        text,
    )
    return text


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _save_cli_logs(temp_root: Path, stdout: str | bytes | None, stderr: str | bytes | None) -> None:
    (temp_root / "cli_stdout.log").write_text(
        _redact_sensitive_text(_as_text(stdout)), encoding="utf-8"
    )
    (temp_root / "cli_stderr.log").write_text(
        _redact_sensitive_text(_as_text(stderr)), encoding="utf-8"
    )


def _sanitize_log_file(path: Path) -> None:
    if path.is_file():
        original = path.read_text(encoding="utf-8", errors="replace")
        path.write_text(_redact_sensitive_text(original), encoding="utf-8")


def _write_manifest(
    temp_root: Path,
    username: str,
    camera_ids: list[str],
    run_ids: set[str],
    event_ids: set[str],
    execution_started_at: str,
    execution_finished_at: str,
    test_result: str,
    evidence: dict,
) -> Path:
    """Persist redacted run metadata and the allowlisted evidence fields."""
    path = temp_root / "test_manifest.json"
    manifest = {
        "execution_started_at": execution_started_at,
        "execution_finished_at": execution_finished_at,
        "test_result": test_result,
        "evidence_folder": str(temp_root.resolve()),
        "username": username,
        "camera_ids": camera_ids,
        "run_ids": sorted(run_ids),
        "event_ids": sorted(event_ids),
        "log_files": list(MANIFEST_LOG_FILES),
    }
    manifest.update({key: evidence.get(key) for key in EVIDENCE_DEFAULTS})
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


class E2EAssertionError(AssertionError):
    """An assertion failure with a safe, fixed check label for the manifest."""

    def __init__(self, check_name: str) -> None:
        super().__init__(check_name)
        self.check_name = check_name


class PriorRunInspectionError(RuntimeError):
    """A prior-run inspection failure with only safe diagnostic fields."""

    def __init__(
        self,
        step: str,
        error: Exception,
        category: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.exception_type = type(error).__name__
        self.category = category
        self.safe_message = message


def _mongo_diagnostic(error: Exception) -> tuple[str, str]:
    """Map driver exceptions to fixed messages that cannot contain connection data."""
    name = type(error).__name__
    code = getattr(error, "code", None)
    if name == "ServerSelectionTimeoutError":
        return "server_selection_timeout", "MongoDB server selection timed out."
    if name in {"ConnectTimeout", "NetworkTimeout", "TimeoutError"}:
        return "connection_timeout", "The MongoDB connection timed out."
    if name == "OperationFailure" and code == 18:
        return "authentication_failed", "MongoDB rejected authentication."
    if name == "OperationFailure" and code == 13:
        return "authorization_failed", "MongoDB denied the requested read-only verification operation."
    if name == "OperationFailure":
        return "mongodb_operation_failed", "MongoDB rejected the read-only verification operation."
    if name in {"ConfigurationError", "InvalidURI"}:
        return "mongodb_configuration_error", "The MongoDB client configuration could not be parsed or used."
    if name in {"AutoReconnect", "ConnectionFailure", "NetworkError"}:
        return "connection_failure", "The MongoDB connection could not be established or maintained."
    return "mongodb_driver_error", "The MongoDB driver raised an error during read-only verification."


def _new_evidence() -> dict:
    return dict(EVIDENCE_DEFAULTS)


def _safe_failure_reason(error: Exception) -> str:
    if isinstance(error, E2EAssertionError):
        return f"Assertion failed: {error.check_name}"
    if isinstance(error, PriorRunInspectionError):
        return f"Prior-run inspection failed: {error.step}"
    return f"{type(error).__name__} (details omitted)"


def _record_failure(evidence: dict, error: Exception) -> None:
    evidence["failure_reason"] = _safe_failure_reason(error)
    if isinstance(error, PriorRunInspectionError):
        evidence.update({
            "failure_step": error.step,
            "failure_exception_type": error.exception_type,
            "failure_category": error.category,
            "failure_message": error.safe_message,
        })


def _record_status(evidence: dict, key: str, ok: bool) -> None:
    if evidence.get(key) != "FAIL":
        evidence[key] = "PASS" if ok else "FAIL"


def _required_evidence_passed(evidence: dict) -> bool:
    counts = (
        "cli_baseline_event_count",
        "first_run_mongo_event_count",
        "second_run_mongo_event_count",
        "second_run_added_event_count",
    )
    statuses = (
        "api_statistics_comparison_result",
        "camera_processing_completion_result",
        "websocket_finished_result",
        "graceful_shutdown_result",
    )
    return all(isinstance(evidence.get(key), int) for key in counts) and all(
        evidence.get(key) == "PASS" for key in statuses
    )


def check(name: str, ok: bool) -> None:
    CHECKS.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}: {name}", flush=True)
    if not ok:
        raise E2EAssertionError(name)


class FinishedRecorder:
    def __init__(self, token: str) -> None:
        self.token = token
        self.finished = threading.Event()
        self.connected = threading.Event()
        self.stop_requested = threading.Event()
        self.messages: list[dict] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        if not self.connected.wait(10):
            raise TimeoutError("WebSocket did not connect")

    def _run(self) -> None:
        async def receive() -> None:
            ws_url = BASE.replace("http://", "ws://") + "/ws/alerts?" + urlencode({"token": self.token})
            async with websockets.connect(ws_url, open_timeout=8) as socket:
                self.connected.set()
                while not self.stop_requested.is_set():
                    try:
                        message = json.loads(await asyncio.wait_for(socket.recv(), timeout=1))
                    except asyncio.TimeoutError:
                        continue
                    self.messages.append(message)
                    if message.get("type") == "finished":
                        self.finished.set()
                        return

        try:
            asyncio.run(receive())
        except Exception:
            self.connected.set()

    def close(self) -> None:
        self.stop_requested.set()
        self.thread.join(timeout=3)


def _request(client: httpx.Client, method: str, path: str, access_token: str | None = None,
             expected: int = 200, report_result: bool = True, **kwargs) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}))
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    response = client.request(method, BASE + path, headers=headers, **kwargs)
    RESPONSE_BODIES.append(_redact_sensitive_text(response.text))
    if report_result:
        check(f"{method} {path} -> {expected}", response.status_code == expected)
    elif response.status_code != expected:
        raise RuntimeError(f"Request returned HTTP {response.status_code}")
    return response


def _inspect_previous_e2e_records(
    readonly_url: str | None = None,
    database_name: str | None = None,
    *,
    test_url: str | None = None,
    production_url: str | None = None,
    client_factory=AsyncMongoClient,
) -> dict[str, list[dict]]:
    """Read prior audit manifests only; randomized run database contents are not verified."""
    uri = readonly_url or os.environ.get("MONGO_E2E_READONLY_URL", "")
    test_uri = test_url or os.environ.get("MONGO_TEST_URL", "")
    production_uri = production_url
    from backend.app.core.config import settings as app_settings
    if production_uri is None:
        production_uri = app_settings.MONGO_URL
    if not database_name or not _E2E_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError("Prior-run inspection requires the randomized E2E database")
    _validate_e2e_isolation(
        database_name,
        os.environ.get("MONGO_E2E_ISOLATED"),
        test_isolation_confirmation=os.environ.get("MONGO_TEST_ISOLATED"),
        test_url=test_uri,
        readonly_url=uri,
        production_url=production_uri,
        repo_backend=app_settings.REPO_BACKEND,
    )

    async def inspect() -> dict[str, list[dict]]:
        try:
            client = client_factory(
                uri,
                tz_aware=True,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
        except Exception as error:
            category, message = _mongo_diagnostic(error)
            raise PriorRunInspectionError(
                "read-only MongoDB client creation",
                error,
                category,
                message,
            ) from None
        try:
            await _assert_readonly_credentials(client)
            db = client[_E2E_AUDIT_DATABASE]
            try:
                docs = await db[_E2E_AUDIT_COLLECTION].find(
                    {"database_name": {"$regex": "^traffic_ai_test_[0-9a-f]{10}$"}},
                    {"_id": 1, "database_name": 1, "status": 1, "started_at": 1,
                     "updated_at": 1, "finished_at": 1, "phases": 1, "records": 1,
                     "failure.category": 1},
                ).sort("started_at", -1).to_list(length=None)
                return {"audit_manifests": docs}
            except Exception as error:
                category, message = _mongo_diagnostic(error)
                raise PriorRunInspectionError(
                    "read-only E2E audit manifest query", error, category, message
                ) from None
        finally:
            await client.close()

    return asyncio.run(inspect())


def _check_previous_run_cleanup(
    readonly_url: str,
    test_url: str,
    production_url: str,
    database_name: str,
) -> None:
    records = _inspect_previous_e2e_records(
        readonly_url,
        database_name,
        test_url=test_url,
        production_url=production_url,
    )
    manifests = records["audit_manifests"]
    print("PREVIOUS_E2E_AUDIT_MANIFESTS (manifest only; randomized database records are not verified): "
          + json.dumps(manifests, default=str), flush=True)
    check("Previous Stage 8 audit manifests inspected", True)


def _write_e2e_audit_manifest(test_url: str, document: dict, *, client_factory=AsyncMongoClient) -> None:
    """Upsert an audit manifest through the isolated test writer, never the reader."""
    if not _E2E_DATABASE_PATTERN.fullmatch(document.get("database_name", "")):
        raise RuntimeError("Refusing to write audit manifest for an unsafe database name")

    async def write():
        client = client_factory(test_url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        try:
            await client[_E2E_AUDIT_DATABASE][_E2E_AUDIT_COLLECTION].replace_one(
                {"_id": document["_id"]}, document, upsert=True
            )
        finally:
            await client.close()
    asyncio.run(write())


def _finalize_e2e_audit_manifest(
    test_url: str, document: dict, passed: bool, evidence: dict
) -> bool:
    """Record a terminal status without raising over the E2E result or exception."""
    now = datetime.now(timezone.utc)
    document["status"] = "succeeded" if passed else "failed"
    document["phases"]["e2e"] = "succeeded" if passed else "failed"
    document["updated_at"] = now
    document["finished_at"] = now
    if not passed:
        document["failure"] = {
            "category": evidence.get("failure_category") or "e2e_failed",
            "message": _redact_sensitive_text(str(
                evidence.get("failure_message") or evidence.get("failure_reason")
                or "E2E checks failed"
            ))[:500],
        }
    try:
        _write_e2e_audit_manifest(test_url, document)
    except Exception as audit_error:
        print(f"FAIL: E2E audit manifest update failed ({type(audit_error).__name__})", flush=True)
        return False
    return True


def _api_counts(client: httpx.Client, token: str, camera_id: str) -> dict[str, int]:
    cameras = _request(client, "GET", "/api/stats/cameras", token).json()
    row = next((item for item in cameras if item["camera_id"] == camera_id), None)
    if row is None:
        return {"total_vehicles": 0, "compliant_vehicles": 0, "violations": 0, "needs_review": 0}
    return {key: int(row[key]) for key in (
        "total_vehicles", "compliant_vehicles", "violations", "needs_review"
    )}


def _wait_health(server: uvicorn.Server, server_thread: threading.Thread, timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2) as client:
        while time.monotonic() < deadline:
            if not server_thread.is_alive():
                raise RuntimeError("Backend exited before health check")
            try:
                if client.get(BASE + "/api/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.25)
    raise TimeoutError("Backend health check timed out")


def _graceful_shutdown(
    server: uvicorn.Server | None,
    server_thread: threading.Thread | None,
    access_token: str | None,
    camera_id: str | None,
    camera_exists: bool = True,
    timeout: float = 30,
) -> tuple[bool, bool]:
    """Stop the camera over the API before asking Uvicorn to exit cooperatively."""
    if server is None or server_thread is None:
        return True, True
    camera_stopped = True
    if server_thread.is_alive() and camera_exists and access_token and camera_id:
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{BASE}/api/cameras/{camera_id}/stop",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            RESPONSE_BODIES.append(response.text)
            camera_stopped = response.status_code == 200
        except httpx.HTTPError:
            camera_stopped = False
    # Always ask Uvicorn to exit, including when the camera stop API failed.
    server.should_exit = True
    server_thread.join(timeout=timeout)
    return camera_stopped, not server_thread.is_alive()


def _close_repository_if_safe(repo, server_thread, server_stopped: bool) -> bool:
    """Do not close Mongo's loop while a Uvicorn thread may still use it."""
    if not server_stopped or (server_thread is not None and server_thread.is_alive()):
        return False
    repo.close()
    return True


def _wait_run(recorder: FinishedRecorder, client: httpx.Client, access_token: str,
              camera_id: str, evidence: dict, timeout: int = 300) -> None:
    deadline = time.monotonic() + timeout
    saw_processing = False
    status_count = 0
    while time.monotonic() < deadline:
        response = client.get(
            f"{BASE}/api/cameras/{camera_id}/status",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        status_count += 1
        if response.status_code != 200:
            _record_status(evidence, "camera_processing_completion_result", False)
            check("Camera status endpoint stays healthy during processing", False)
            raise RuntimeError(f"Camera status endpoint returned HTTP {response.status_code}")
        saw_processing |= response.json().get("status") == "processing"
        if recorder.finished.is_set():
            break
        time.sleep(STATUS_POLL_INTERVAL_SECONDS)
    status_ok = status_count > 0
    camera_completed = status_ok and saw_processing
    _record_status(evidence, "camera_processing_completion_result", camera_completed)
    _record_status(evidence, "websocket_finished_result", recorder.finished.is_set())
    check("Camera status endpoint stays healthy during processing", status_ok)
    check("WebSocket received finished event", recorder.finished.is_set())
    check("Camera status reached processing", saw_processing)


def _run_e2e(
    temp_root: Path,
    user_name: str,
    password: str,
    camera_id: str,
    second_camera: str,
    generated_run_ids: set[str],
    generated_event_ids: set[str],
    evidence: dict,
    started_at: str,
) -> int:
    storage = _configure_e2e_storage(temp_root)

    # Settings and logging are initialized by backend imports, so the isolated
    # storage location must be in place before importing any backend module.
    from backend.app.core.config import settings
    from backend.app.core.security import get_password_hash
    from backend.app.models.user import User
    from backend.app.models.event import result_from_pipeline

    if settings.REPO_BACKEND != "mongo":
        evidence["failure_reason"] = "REPO_BACKEND is not mongo"
        print("FAIL: launch with REPO_BACKEND=mongo", flush=True)
        return 1
    if not VIDEO.is_file():
        evidence["failure_reason"] = "Required test video is missing"
        print("FAIL: data/videos/helmet_test.mp4 is missing", flush=True)
        return 1

    repo = None
    server = None
    server_thread = None
    token = None
    recorder = None
    server_stopped = True
    camera_created = False
    final_counts: dict[str, int] = {}
    indexes: dict[str, str] = {}
    cli_summary: Counter = Counter()
    first_event_ids: set[str] = set()
    first_run_ids: set[str] = set()
    failed = False
    test_url = ""
    audit_doc = None
    isolation_validated = False
    try:
        test_url = os.environ.get("MONGO_TEST_URL", "").strip()
        readonly_url = os.environ.get("MONGO_E2E_READONLY_URL", "").strip()
        database_name = _new_e2e_database_name(
            os.environ.get("MONGO_TEST_DB"),
            os.environ.get("MONGO_TEST_DATABASE"),
        )
        env = _cli_environment(storage, test_url, database_name)
        _validate_e2e_isolation(
            database_name,
            os.environ.get("MONGO_E2E_ISOLATED"),
            test_isolation_confirmation=os.environ.get("MONGO_TEST_ISOLATED"),
            test_url=test_url,
            readonly_url=readonly_url,
            production_url=settings.MONGO_URL,
            repo_backend=settings.REPO_BACKEND,
        )
        isolation_validated = True
        audit_doc = {
            "_id": uuid.uuid4().hex,
            "database_name": database_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "finished_at": None,
            "phases": {"fresh_database_verified": "not_started", "e2e": "running"},
            "records": {"users": [], "cameras": [], "vehicle_events": [], "violations": []},
            "failure": {"category": None, "message": None},
        }
        check("Repository is configured for MongoDB", settings.REPO_BACKEND == "mongo")
        check("Mongo test database and operation timeout are configured",
              bool(database_name) and settings.MONGO_OPERATION_TIMEOUT_SECONDS == 30)
        print(f"MONGO_REPO_CONFIG: backend={settings.REPO_BACKEND}; "
              f"database={database_name}; operation_timeout_seconds="
              f"{settings.MONGO_OPERATION_TIMEOUT_SECONDS:g}", flush=True)
        asyncio.run(_verify_fresh_e2e_database(test_url, database_name))
        check("Randomized Mongo test database is fresh", True)
        audit_doc["phases"]["fresh_database_verified"] = "succeeded"
        _check_previous_run_cleanup(
            readonly_url,
            test_url,
            settings.MONGO_URL,
            database_name,
        )
        _write_e2e_audit_manifest(test_url, audit_doc)
        repo = _create_e2e_repository(test_url, database_name)
        check("Fresh test username and camera ID are unused",
              repo.get_user_by_username(user_name) is None
              and repo.get_camera(camera_id) is None
              and repo.get_camera(second_camera) is None)
        repo.save_user(User(
            id=uuid.uuid4().hex, username=user_name, hashed_password=get_password_hash(password), role="admin"
        ))
        audit_doc["records"]["users"].append(user_name)
        audit_doc["updated_at"] = datetime.now(timezone.utc)
        _write_e2e_audit_manifest(test_url, audit_doc)
        server = uvicorn.Server(uvicorn.Config(
            "backend.app.main:app",
            host="127.0.0.1",
            port=8765,
            workers=1,
            log_level="info",
        ))
        server_thread = threading.Thread(
            target=server.run,
            name="stage8-e2e-uvicorn",
            daemon=True,
        )
        server_thread.start()
        _wait_health(server, server_thread)
        check("Mongo repository startup ping and indexes", True)
        with httpx.Client(timeout=30) as client:
            login = _request(client, "POST", "/api/auth/login", expected=200,
                             json={"username": user_name, "password": password}).json()
            token = login["access_token"]
            created = _request(client, "POST", "/api/cameras", token, expected=201,
                               json={"camera_id": camera_id, "name": "Stage 8 E2E",
                                     "source_type": "file", "checks": ["helmet"],
                                     "zone": [0.0, 0.9, 1.0, 0.9]})
            check("Create camera through API", created.json()["camera_id"] == camera_id)
            camera_created = True
            audit_doc["records"]["cameras"].extend([camera_id, second_camera])
            _request(client, "POST", "/api/cameras", token, expected=201,
                     json={"camera_id": second_camera, "name": "Busy camera",
                           "source_type": "file", "checks": ["helmet"]})
            with VIDEO.open("rb") as video:
                uploaded = _request(client, "POST", f"/api/cameras/{camera_id}/video", token,
                                    expected=200, files={"file": (VIDEO.name, video, "video/mp4")})
            check("Upload helmet_test.mp4 through API", Path(uploaded.json()["source_path"]).is_file())

            cli_json = temp_root / "cli_events.json"
            try:
                cli = subprocess.run(
                    [sys.executable, "scripts/run_video.py", "--source", str(VIDEO), "--mode", "helmet",
                     "--zone", "0,0.9,1,0.9", "--camera-id", camera_id, "--device", "cpu", "--no-show",
                     "--json", str(cli_json), "--evidence-dir", str(temp_root / "cli-evidence")],
                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=600, check=False,
                )
            except subprocess.TimeoutExpired as error:
                _save_cli_logs(temp_root, error.stdout, error.stderr)
                evidence["failure_reason"] = "CLI baseline timed out"
                raise RuntimeError("CLI baseline timed out") from None
            _save_cli_logs(temp_root, cli.stdout, cli.stderr)
            check("CLI baseline completes", cli.returncode == 0 and cli_json.is_file())
            cli_events = json.loads(cli_json.read_text(encoding="utf-8"))
            evidence["cli_baseline_event_count"] = len(cli_events)
            cli_summary = Counter(result_from_pipeline(e.get("decision", ""), e.get("ai_result", "")) for e in cli_events)
            baseline = _api_counts(client, token, camera_id)

            run_ids: list[set[str]] = []
            response_ids: list[set[str]] = []
            for run_number in (1, 2):
                recorder = FinishedRecorder(token)
                recorder.start()
                _request(client, "POST", f"/api/cameras/{camera_id}/start", token)
                if run_number == 1:
                    conflict = _request(client, "POST", f"/api/cameras/{second_camera}/start", token, expected=409)
                    check("Concurrent camera start returns 409", conflict.status_code == 409)
                with client.stream("GET", BASE + f"/api/stream/{camera_id}",
                                   params={"token": token}, timeout=httpx.Timeout(10, read=10)) as stream:
                    check("Authenticated stream responds", stream.status_code == 200)
                    frame_chunk = next(stream.iter_bytes(chunk_size=2048), b"")
                    check("Video stream returns bytes", bool(frame_chunk))
                _wait_run(recorder, client, token, camera_id, evidence)
                stop = _request(client, "POST", f"/api/cameras/{camera_id}/stop", token)
                check("Stop endpoint succeeds", stop.json().get("status") == "offline")
                violations = _request(client, "GET", f"/api/violations?camera={camera_id}&limit=500", token).json()
                summary = _request(client, "GET", "/api/stats/summary", token).json()
                camera_counts = _api_counts(client, token, camera_id)
                final_counts = camera_counts
                docs = repo._run(repo.db.vehicle_events.find({"camera_id": camera_id}).to_list(length=None))
                if run_number == 1:
                    evidence["first_run_mongo_event_count"] = len(docs)
                mongo_violations = repo._run(
                    repo.db.violations.find({"camera_id": camera_id}).to_list(length=None)
                )
                expected_violation_ids = {
                    doc["event_id"] for doc in docs
                    if doc["result"] in {"NO_HELMET", "NO_SEATBELT", "NEEDS_REVIEW"}
                }
                api_violation_ids = {item["event_id"] for item in violations["items"]}
                check("Violations API returns filtered camera data", all(
                    item["camera_id"] == camera_id for item in violations["items"]
                ))
                check("Violations API count matches MongoDB",
                      violations["total"] == len(mongo_violations) == len(expected_violation_ids))
                check("Violations API event IDs match MongoDB",
                      api_violation_ids == {item["event_id"] for item in mongo_violations})
                check("Summary API reports vehicle totals", summary["total_vehicles"] >= camera_counts["total_vehicles"])
                ids = {doc["event_id"] for doc in docs}
                generated_event_ids.update(ids)
                audit_doc["records"]["vehicle_events"] = sorted(generated_event_ids)
                audit_doc["records"]["violations"] = sorted({
                    item["event_id"] for item in mongo_violations
                })
                audit_doc["updated_at"] = datetime.now(timezone.utc)
                _write_e2e_audit_manifest(test_url, audit_doc)
                response_ids.append({item["event_id"] for item in violations["items"]})
                run_ids.append({doc["run_id"] for doc in docs})
                generated_run_ids.update(run_ids[-1])
                check(f"Run {run_number} stored vehicle events", len(docs) > 0)
                api_mongo_counts_match = camera_counts["total_vehicles"] == len(docs)
                if not api_mongo_counts_match:
                    evidence["api_statistics_comparison_result"] = "FAIL"
                check("API vehicle total matches MongoDB event count", api_mongo_counts_match)
                check(f"Run {run_number} has the expected unique run IDs",
                      len(run_ids[-1]) == run_number)
                if run_number == 1:
                    first_event_ids = ids
                    first_run_ids = run_ids[0]
                    check("First-run Mongo result counts match CLI", Counter(
                        doc["result"] for doc in docs
                    ) == cli_summary)
                    actual = {"total_vehicles": camera_counts["total_vehicles"],
                              "compliant_vehicles": camera_counts["compliant_vehicles"],
                              "violations": camera_counts["violations"],
                              "needs_review": camera_counts["needs_review"]}
                    expected = {
                        "total_vehicles": len(cli_events),
                        "compliant_vehicles": cli_summary["HELMET"] + cli_summary["SEATBELT"],
                        "violations": cli_summary["NO_HELMET"] + cli_summary["NO_SEATBELT"],
                        "needs_review": cli_summary["NEEDS_REVIEW"],
                    }
                    first_api_matches_cli = actual == expected
                    if not first_api_matches_cli:
                        evidence["api_statistics_comparison_result"] = "FAIL"
                    check("API first-run totals and result counts match CLI", first_api_matches_cli)
                    baseline = actual
                else:
                    expected_twice = {key: value * 2 for key, value in baseline.items()}
                    counts_incremented = camera_counts == expected_twice
                    if not counts_incremented:
                        evidence["api_statistics_comparison_result"] = "FAIL"
                    check("Second run adds a full new set of results", counts_incremented)
                    new_run_ids = run_ids[1] - first_run_ids
                    new_event_ids = ids - first_event_ids
                    second_run_docs = [doc for doc in docs if doc["run_id"] in new_run_ids]
                    evidence["second_run_mongo_event_count"] = len(second_run_docs)
                    evidence["second_run_added_event_count"] = len(docs) - int(
                        evidence["first_run_mongo_event_count"] or 0
                    )
                    check("Second run has distinct run and event IDs",
                          len(first_run_ids) == 1 and len(new_run_ids) == 1
                          and first_run_ids.isdisjoint(new_run_ids)
                          and first_event_ids.isdisjoint(new_event_ids)
                          and len(second_run_docs) == len(cli_events)
                          and len(new_event_ids) == len(cli_events)
                          and len(ids) == len(docs) == len(cli_events) * 2)
                    mongo_increment_matches = (
                        evidence["second_run_added_event_count"] == len(cli_events)
                    )
                    if not mongo_increment_matches:
                        evidence["api_statistics_comparison_result"] = "FAIL"
                    check("Second run adds the expected Mongo event count", mongo_increment_matches)
                    check("Second-run Mongo result counts match CLI",
                          Counter(doc["result"] for doc in second_run_docs) == cli_summary)
                if run_number == 1:
                    check("First API run has result records", bool(response_ids[0]) or cli_summary["HELMET"] > 0)
                recorder.close()

            if evidence["api_statistics_comparison_result"] != "FAIL":
                evidence["api_statistics_comparison_result"] = "PASS"

            indexes = repo.explain_main_queries()
            check("Explain plans use indexes", all(stage == "IXSCAN" for stage in indexes.values()))
            check("Five documented collections exist",
                  set(repo._run(repo.db.list_collection_names())) == {
                      "users", "cameras", "vehicle_events", "violations", "system_settings"
                  })
            expected_result_values = {"HELMET", "NO_HELMET", "NEEDS_REVIEW", "NOT_CHECKED", "SEATBELT", "NO_SEATBELT"}
            check("Persisted event result labels are valid", all(
                doc["result"] in expected_result_values
                for doc in repo._run(repo.db.vehicle_events.find({"camera_id": camera_id}).to_list(length=None))
            ))
            final_docs = repo._run(repo.db.vehicle_events.find({"camera_id": camera_id}).to_list(length=None))
            generated_run_ids.update(doc["run_id"] for doc in final_docs)
            generated_event_ids.update(doc["event_id"] for doc in final_docs)
            camera_stopped, server_stopped = _graceful_shutdown(
            server, server_thread, token, camera_id, camera_exists=camera_created
        )
        _record_status(evidence, "graceful_shutdown_result", camera_stopped and server_stopped)
        check("Camera stop API completed before Uvicorn shutdown", camera_stopped)
        check("Uvicorn shut down gracefully", server_stopped)
        if not (camera_stopped and server_stopped):
            raise RuntimeError("Backend did not shut down gracefully")
        connection_urls = (
            settings.MONGO_URL,
            test_url,
            readonly_url,
        )
        password_parts = []
        for connection_url in connection_urls:
            parsed = urlsplit(connection_url)
            password_parts.append(unquote(parsed.password or ""))
        all_logs = ""
        log_path = Path(env["STORAGE_DIR"]) / "logs" / "backend.log"
        _sanitize_log_file(log_path)
        if log_path.exists():
            all_logs += log_path.read_text(encoding="utf-8", errors="replace")
        response_text = "\n".join(RESPONSE_BODIES)
        checked_text = all_logs + response_text
        url_secret_absent = all(connection_url not in checked_text for connection_url in connection_urls) and all(
            part not in checked_text for part in password_parts if part
        )
        check("Mongo URL/password absent from logs and API responses", url_secret_absent)
        check("No internal test password printed in server logs", password not in all_logs)
        print("EXPLAIN: " + json.dumps(indexes, sort_keys=True), flush=True)
        print("CLI_RESULT_COUNTS: " + json.dumps(dict(cli_summary), sort_keys=True), flush=True)
        print("API_CAMERA_COUNTS_AFTER_TWO_RUNS: " + json.dumps(final_counts, sort_keys=True), flush=True)
    except Exception as error:
        if not evidence.get("failure_reason"):
            _record_failure(evidence, error)
        _write_manifest(
            temp_root,
            user_name,
            [camera_id, second_camera],
            generated_run_ids,
            generated_event_ids,
            started_at,
            datetime.now(timezone.utc).isoformat(),
            "FAIL",
            evidence,
        )
        print(f"FAIL: end-to-end check stopped ({type(error).__name__})", flush=True)
        failed = True
    finally:
        if recorder is not None:
            recorder.close()
        if server_thread is not None and server_thread.is_alive():
            camera_stopped, server_stopped = _graceful_shutdown(
                server, server_thread, token, camera_id, camera_exists=camera_created
            )
            _record_status(evidence, "graceful_shutdown_result", camera_stopped and server_stopped)
            print(f"{'PASS' if camera_stopped else 'FAIL'}: camera stop during final shutdown", flush=True)
            print(f"{'PASS' if server_stopped else 'FAIL'}: Uvicorn cooperative shutdown", flush=True)
        if repo is not None:
            try:
                if server_stopped:
                    _sanitize_log_file(storage / "logs" / "backend.log")
                else:
                    print("FAIL: Mongo repository left open because Uvicorn is still running", flush=True)
            finally:
                if not _close_repository_if_safe(repo, server_thread, server_stopped):
                    print("FAIL: Mongo repository left open because Uvicorn is still running", flush=True)
        if isolation_validated and audit_doc is not None and test_url:
            audit_passed = (not failed and server_stopped and all(result for _, result in CHECKS)
                            and _required_evidence_passed(evidence)
                            and not evidence.get("failure_reason"))
            if not _finalize_e2e_audit_manifest(test_url, audit_doc, audit_passed, evidence):
                failed = True
        print(f"GENERATED_TEST_USERNAME: {user_name}", flush=True)
        print(f"GENERATED_CAMERA_IDS: {camera_id}, {second_camera}", flush=True)
        print("GENERATED_RUN_IDS: " + json.dumps(sorted(generated_run_ids)), flush=True)
        print("GENERATED_EVENT_IDS: " + json.dumps(sorted(generated_event_ids)), flush=True)
        print(f"PRESERVED_TEMP_ARTIFACTS: {temp_root}", flush=True)
        print(f"PRESERVED_BACKEND_LOG: {storage / 'logs' / 'backend.log'}", flush=True)
    passed = (
        all(result for _, result in CHECKS)
        and _required_evidence_passed(evidence)
        and not evidence.get("failure_reason")
    )
    return 1 if failed or not passed else 0


def main() -> int:
    CHECKS.clear()
    RESPONSE_BODIES.clear()
    load_dotenv(ROOT / ".env", override=False)
    started_at = datetime.now(timezone.utc).isoformat()
    temp_root = Path(tempfile.mkdtemp(prefix="traffic-ai-stage8-"))
    user_name = "s8-e2e-" + uuid.uuid4().hex[:10]
    camera_id = "s8-e2e-" + uuid.uuid4().hex[:10]
    second_camera = camera_id + "-busy"
    generated_run_ids: set[str] = set()
    generated_event_ids: set[str] = set()
    evidence = _new_evidence()
    result = 1
    try:
        result = _run_e2e(
            temp_root,
            user_name,
            secrets.token_urlsafe(32),
            camera_id,
            second_camera,
            generated_run_ids,
            generated_event_ids,
            evidence,
            started_at,
        )
    except Exception as error:
        if not evidence.get("failure_reason"):
            _record_failure(evidence, error)
        print(f"FAIL: end-to-end check stopped ({type(error).__name__})", flush=True)
        result = 1
    finally:
        passed = (
            result == 0
            and all(ok for _, ok in CHECKS)
            and _required_evidence_passed(evidence)
            and not evidence.get("failure_reason")
        )
        test_result = "PASS" if passed else "FAIL"
        if not passed and not evidence.get("failure_reason"):
            evidence["failure_reason"] = "Required E2E evidence or assertions did not pass"
        manifest_path = _write_manifest(
            temp_root,
            user_name,
            [camera_id, second_camera],
            generated_run_ids,
            generated_event_ids,
            started_at,
            datetime.now(timezone.utc).isoformat(),
            test_result,
            evidence,
        )
        print(f"PRESERVED_TEMP_ARTIFACTS: {temp_root}", flush=True)
        print(f"PRESERVED_TEST_MANIFEST: {manifest_path}", flush=True)
        print(f"RESULT: {test_result} ({len(CHECKS)} checks)", flush=True)
    return 0 if test_result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
