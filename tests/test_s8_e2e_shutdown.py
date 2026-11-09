"""Tests for cooperative E2E shutdown without starting Uvicorn or a video worker."""
from __future__ import annotations

import asyncio
import builtins
from datetime import datetime
import json
import os
from pathlib import Path

import pytest

from scripts import s8_e2e


class FakeServer:
    def __init__(self, actions):
        self.actions = actions
        self._should_exit = False

    @property
    def should_exit(self):
        return self._should_exit

    @should_exit.setter
    def should_exit(self, value):
        self.actions.append("server-exit")
        self._should_exit = value


def test_e2e_storage_is_configured_before_first_backend_import(tmp_path, monkeypatch):
    expected_storage = tmp_path / "storage"
    imported_backend_modules = []

    class StopBeforeBackendImport(Exception):
        pass

    original_import = builtins.__import__

    def inspect_first_backend_import(name, *args, **kwargs):
        if name == "backend.app.core.config":
            imported_backend_modules.append(name)
            assert Path(os.environ["STORAGE_DIR"]) == expected_storage
            assert os.environ["TRAFFIC_AI_DEVICE"] == "cpu"
            assert (expected_storage / "logs").is_dir()
            assert (expected_storage / "uploads").is_dir()
            assert (expected_storage / "evidence").is_dir()
            raise StopBeforeBackendImport
        return original_import(name, *args, **kwargs)

    monkeypatch.setenv("STORAGE_DIR", "project-storage")
    monkeypatch.setattr(builtins, "__import__", inspect_first_backend_import)
    try:
        s8_e2e._run_e2e(
            tmp_path,
            "s8-e2e-user",
            "synthetic-password",
            "s8-e2e-camera",
            "s8-e2e-camera-busy",
            set(),
            set(),
            s8_e2e._new_evidence(),
            "2026-11-06T00:00:00+00:00",
        )
    except StopBeforeBackendImport:
        pass
    else:
        raise AssertionError("test should stop at the first backend import")

    assert imported_backend_modules == ["backend.app.core.config"]


@pytest.mark.parametrize(
    ("test_url", "readonly_url"),
    [
        (
            "mongodb://test.example.test/traffic_ai_test",
            "mongodb://test.example.test/traffic_ai_test",
        ),
        (
            "mongodb://test.example.test/traffic_ai_test",
            "mongodb://other-test.example.test/traffic_ai_test",
        ),
    ],
    ids=["test-endpoint-matches-production", "readonly-endpoint-mismatch"],
)
def test_rejected_e2e_isolation_performs_no_mongo_connections_or_writes(
    tmp_path, monkeypatch, test_url, readonly_url
):
    from backend.app.core.config import settings

    production_url = (
        test_url if test_url.startswith("mongodb://test.example.test")
        and readonly_url.startswith("mongodb://test.example.test")
        else "mongodb://production.example.test/traffic_ai"
    )
    # The first case deliberately makes the test deployment equal production.
    if "other-test.example.test" in readonly_url:
        production_url = "mongodb://production.example.test/traffic_ai"
    monkeypatch.setattr(settings, "REPO_BACKEND", "mongo")
    monkeypatch.setattr(settings, "MONGO_URL", production_url)
    monkeypatch.setenv("MONGO_TEST_URL", test_url)
    monkeypatch.setenv("MONGO_E2E_READONLY_URL", readonly_url)
    monkeypatch.setenv("MONGO_TEST_DB", "traffic_ai_test")
    monkeypatch.setenv("MONGO_TEST_ISOLATED", "1")
    monkeypatch.setenv("MONGO_E2E_ISOLATED", "1")
    video = tmp_path / "helmet_test.mp4"
    video.write_bytes(b"synthetic test placeholder")
    monkeypatch.setattr(s8_e2e, "VIDEO", video)
    monkeypatch.setattr(
        s8_e2e, "_new_e2e_database_name", lambda _prefix: "traffic_ai_test_0123456789"
    )

    attempted_mongo_operations = []

    def unexpected_operation(*_args, **_kwargs):
        attempted_mongo_operations.append("mongo operation")
        raise AssertionError("Mongo operation must not start before isolation validation")

    monkeypatch.setattr(s8_e2e, "_verify_fresh_e2e_database", unexpected_operation)
    monkeypatch.setattr(s8_e2e, "_inspect_previous_e2e_records", unexpected_operation)
    monkeypatch.setattr(s8_e2e, "_create_e2e_repository", unexpected_operation)
    monkeypatch.setattr(s8_e2e, "_write_e2e_audit_manifest", unexpected_operation)

    result = s8_e2e._run_e2e(
        tmp_path,
        "s8-e2e-user",
        "synthetic-password",
        "s8-e2e-camera",
        "s8-e2e-camera-busy",
        set(),
        set(),
        s8_e2e._new_evidence(),
        "2026-11-06T00:00:00+00:00",
    )

    assert result == 1
    assert attempted_mongo_operations == []


def test_audit_finalization_failure_does_not_raise_over_e2e_exception(monkeypatch, capsys):
    original_error = RuntimeError("synthetic E2E failure")
    document = {
        "_id": "run-id",
        "database_name": "traffic_ai_test_0123456789",
        "phases": {},
    }

    def fail_audit_write(*_args, **_kwargs):
        raise OSError("synthetic audit storage failure")

    monkeypatch.setattr(s8_e2e, "_write_e2e_audit_manifest", fail_audit_write)
    caught_error = None
    try:
        raise original_error
    except RuntimeError as error:
        caught_error = error
        finalized = s8_e2e._finalize_e2e_audit_manifest(
            "test-writer-uri", document, False,
            {"failure_category": "e2e_failed", "failure_message": "synthetic E2E failure"},
        )

    assert caught_error is original_error
    assert finalized is False
    assert "audit manifest update failed (OSError)" in capsys.readouterr().out


class FakeServerThread:
    def __init__(self, actions, *, stops_on_join=True):
        self.actions = actions
        self.alive = True
        self.stops_on_join = stops_on_join

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.actions.append("server-join")
        self.actions.append(("join-timeout", timeout))
        if self.stops_on_join:
            self.alive = False


class FakeResponse:
    status_code = 200
    text = ""


def test_shutdown_stops_camera_before_uvicorn(monkeypatch, capsys):
    actions = []

    class FakeHttpClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, url, headers):
            actions.append("camera-stop")
            assert url.endswith("/api/cameras/camera-test/stop")
            assert headers["Authorization"] == "Bearer test-token"
            return FakeResponse()

    monkeypatch.setattr(s8_e2e.httpx, "Client", FakeHttpClient)
    server = FakeServer(actions)
    thread = FakeServerThread(actions)

    assert s8_e2e._graceful_shutdown(server, thread, "test-token", "camera-test") == (True, True)
    assert actions == ["camera-stop", "server-exit", "server-join", ("join-timeout", 30)]
    assert "test-token" not in capsys.readouterr().out


def test_request_uses_access_token_without_logging_it(capsys):
    token = "actual-login-token-value"

    class FakeResponse:
        status_code = 200

        def __init__(self):
            self.text = json.dumps({"access_token": token})

        @staticmethod
        def json():
            return {}

    class FakeClient:
        headers = None

        def request(self, _method, _url, headers, **_kwargs):
            self.headers = headers
            return FakeResponse()

    client = FakeClient()
    s8_e2e.RESPONSE_BODIES.clear()
    s8_e2e._request(client, "GET", "/api/test", token)

    assert client.headers["Authorization"] == f"Bearer {token}"
    assert token not in "".join(s8_e2e.RESPONSE_BODIES)
    assert token not in capsys.readouterr().out


def test_wait_run_uses_access_token_without_logging_it(capsys):
    token = "actual-login-token-value"
    recorder = type("Recorder", (), {"finished": type("Flag", (), {"is_set": lambda self: True})()})()

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "processing"}

    class FakeClient:
        headers = None

        def get(self, _url, headers):
            self.headers = headers
            return FakeResponse()

    client = FakeClient()
    s8_e2e._wait_run(recorder, client, token, "camera-test", evidence=s8_e2e._new_evidence())

    assert client.headers["Authorization"] == f"Bearer {token}"
    assert token not in capsys.readouterr().out


def test_failed_camera_stop_still_shuts_down_uvicorn(monkeypatch):
    actions = []

    class FailedHttpClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *_args, **_kwargs):
            actions.append("camera-stop-failed")
            response = FakeResponse()
            response.status_code = 503
            return response

    monkeypatch.setattr(s8_e2e.httpx, "Client", FailedHttpClient)
    server = FakeServer(actions)
    thread = FakeServerThread(actions)

    assert s8_e2e._graceful_shutdown(server, thread, "test-token", "camera-test") == (False, True)
    assert actions[:3] == ["camera-stop-failed", "server-exit", "server-join"]
    assert server.should_exit
    assert not thread.is_alive()


def test_shutdown_timeout_reports_server_thread_still_alive(monkeypatch):
    actions = []

    class FailedHttpClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(s8_e2e.httpx, "Client", FailedHttpClient)
    server = FakeServer(actions)
    thread = FakeServerThread(actions, stops_on_join=False)

    assert s8_e2e._graceful_shutdown(
        server, thread, "test-token", "camera-test", timeout=0.25
    ) == (True, False)
    assert actions == ["server-exit", "server-join", ("join-timeout", 0.25)]
    assert server.should_exit
    assert thread.is_alive()


def test_repository_is_not_closed_while_server_thread_is_alive():
    actions = []
    thread = FakeServerThread(actions, stops_on_join=False)

    class FakeRepository:
        closed = False

        def close(self):
            self.closed = True

    repo = FakeRepository()
    assert not s8_e2e._close_repository_if_safe(repo, thread, server_stopped=False)
    assert not s8_e2e._close_repository_if_safe(repo, thread, server_stopped=True)
    assert not repo.closed

    thread.alive = False
    assert s8_e2e._close_repository_if_safe(repo, thread, server_stopped=True)
    assert repo.closed


def test_cli_output_redaction_and_manifest_fields(tmp_path):
    unsafe = (
        'mongodb+srv://user:secret@cluster.test/db password_hash=hash123 '
        'Authorization: Bearer eyJabcdefgh.payload.signature '
        'json={"access_token":"jwt-secret","MONGO_URL":"mongodb://host/db"}'
    )
    safe = s8_e2e._redact_sensitive_text(unsafe)
    assert "secret" not in safe
    assert "hash123" not in safe
    assert "eyJabcdefgh" not in safe
    assert "cluster.test" not in safe and "jwt-secret" not in safe

    s8_e2e._save_cli_logs(tmp_path, unsafe, "password=stderr-secret")
    stdout_log = (tmp_path / "cli_stdout.log").read_text(encoding="utf-8")
    stderr_log = (tmp_path / "cli_stderr.log").read_text(encoding="utf-8")
    assert "secret" not in stdout_log and "cluster.test" not in stdout_log
    assert "stderr-secret" not in stderr_log
    backend_log = tmp_path / "backend.log"
    backend_log.write_text(unsafe, encoding="utf-8")
    s8_e2e._sanitize_log_file(backend_log)
    assert "secret" not in backend_log.read_text(encoding="utf-8")

    manifest_path = s8_e2e._write_manifest(
        tmp_path,
        "s8-e2e-user",
        ["s8-e2e-camera"],
        {"run-1"},
        {"event-1"},
        "2026-11-05T12:00:00+00:00",
        "2026-11-05T12:01:00+00:00",
        "PASS",
        {
            **s8_e2e._new_evidence(),
            "cli_baseline_event_count": 6,
            "first_run_mongo_event_count": 6,
            "second_run_mongo_event_count": 12,
            "second_run_added_event_count": 6,
            "api_statistics_comparison_result": "PASS",
            "camera_processing_completion_result": "PASS",
            "websocket_finished_result": "PASS",
            "graceful_shutdown_result": "PASS",
        },
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["execution_started_at"] == "2026-11-05T12:00:00+00:00"
    assert manifest["execution_finished_at"] == "2026-11-05T12:01:00+00:00"
    assert datetime.fromisoformat(manifest["execution_started_at"]).utcoffset().total_seconds() == 0
    assert datetime.fromisoformat(manifest["execution_finished_at"]).utcoffset().total_seconds() == 0
    assert manifest["test_result"] == "PASS"
    assert manifest["evidence_folder"] == str(tmp_path.resolve())
    assert manifest["username"] == "s8-e2e-user"
    assert manifest["camera_ids"] == ["s8-e2e-camera"]
    assert manifest["run_ids"] == ["run-1"]
    assert manifest["event_ids"] == ["event-1"]
    assert manifest["cli_baseline_event_count"] == 6
    assert manifest["first_run_mongo_event_count"] == 6
    assert manifest["second_run_mongo_event_count"] == 12
    assert manifest["second_run_added_event_count"] == 6
    assert manifest["api_statistics_comparison_result"] == "PASS"
    assert manifest["camera_processing_completion_result"] == "PASS"
    assert manifest["websocket_finished_result"] == "PASS"
    assert manifest["graceful_shutdown_result"] == "PASS"
    assert "cli_stdout.log" in manifest["log_files"]
    assert not {"password", "password_hash", "token", "mongo_url"} & set(manifest)


def test_manifest_is_preserved_when_e2e_setup_fails(tmp_path, monkeypatch):
    evidence_folder = tmp_path / "failed-e2e"
    evidence_folder.mkdir()
    monkeypatch.setattr(s8_e2e.tempfile, "mkdtemp", lambda **_: str(evidence_folder))

    def fail_before_e2e(*_args, **_kwargs):
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(s8_e2e, "_run_e2e", fail_before_e2e)

    assert s8_e2e.main() == 1
    manifest = json.loads((evidence_folder / "test_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_result"] == "FAIL"
    assert manifest["evidence_folder"] == str(evidence_folder.resolve())
    assert manifest["username"].startswith("s8-e2e-")
    started = datetime.fromisoformat(manifest["execution_started_at"])
    finished = datetime.fromisoformat(manifest["execution_finished_at"])
    assert started.utcoffset().total_seconds() == 0
    assert finished.utcoffset().total_seconds() == 0
    assert finished >= started
    assert manifest["failure_reason"] == "RuntimeError (details omitted)"


def test_manifest_records_assertion_failure(tmp_path, monkeypatch):
    evidence_folder = tmp_path / "assertion-failed"
    evidence_folder.mkdir()
    monkeypatch.setattr(s8_e2e.tempfile, "mkdtemp", lambda **_: str(evidence_folder))

    def fail_assertion(*_args, **_kwargs):
        s8_e2e.check("API statistics comparison", False)

    monkeypatch.setattr(s8_e2e, "_run_e2e", fail_assertion)

    assert s8_e2e.main() == 1
    manifest = json.loads((evidence_folder / "test_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_result"] == "FAIL"
    assert manifest["failure_reason"] == "Assertion failed: API statistics comparison"


def test_readonly_inspection_diagnostic_is_safe_and_recorded(tmp_path):
    class OperationFailure(Exception):
        code = 18

    class Admin:
        async def command(self, _command):
            raise OperationFailure(
                "mongodb+srv://reader:db-password@private.example.test/?token=jwt-secret "
                "SECRET_KEY=signing-secret"
            )

    class FakeClient:
        admin = Admin()

    evidence = s8_e2e._new_evidence()
    try:
        asyncio.run(s8_e2e._assert_readonly_credentials(FakeClient()))
    except s8_e2e.PriorRunInspectionError as error:
        s8_e2e._record_failure(evidence, error)
    else:
        raise AssertionError("credential verification should report the synthetic failure")

    manifest_path = s8_e2e._write_manifest(
        tmp_path,
        "s8-e2e-user",
        [],
        set(),
        set(),
        "2026-11-06T00:00:00+00:00",
        "2026-11-06T00:00:01+00:00",
        "FAIL",
        evidence,
    )
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["failure_step"] == "read-only credential connectionStatus verification"
    assert manifest["failure_exception_type"] == "OperationFailure"
    assert manifest["failure_category"] == "authentication_failed"
    assert manifest["failure_message"] == "MongoDB rejected authentication."
    for secret in (
        "reader", "db-password", "private.example.test", "jwt-secret", "signing-secret"
    ):
        assert secret not in manifest_text


def test_manifest_cannot_pass_when_graceful_shutdown_fails(tmp_path, monkeypatch):
    evidence_folder = tmp_path / "shutdown-failed"
    evidence_folder.mkdir()
    monkeypatch.setattr(s8_e2e.tempfile, "mkdtemp", lambda **_: str(evidence_folder))

    def run_with_shutdown_failure(*args):
        evidence = args[-2]
        evidence.update({
            "cli_baseline_event_count": 6,
            "first_run_mongo_event_count": 6,
            "second_run_mongo_event_count": 12,
            "second_run_added_event_count": 6,
            "api_statistics_comparison_result": "PASS",
            "camera_processing_completion_result": "PASS",
            "websocket_finished_result": "PASS",
            "graceful_shutdown_result": "FAIL",
        })
        s8_e2e.CHECKS.append(("all fake assertions", True))
        return 0

    monkeypatch.setattr(s8_e2e, "_run_e2e", run_with_shutdown_failure)

    assert s8_e2e.main() == 1
    manifest = json.loads((evidence_folder / "test_manifest.json").read_text(encoding="utf-8"))
    assert manifest["test_result"] == "FAIL"
    assert manifest["graceful_shutdown_result"] == "FAIL"
    assert manifest["failure_reason"] == "Required E2E evidence or assertions did not pass"


def test_status_polling_interval_is_two_seconds():
    assert s8_e2e.STATUS_POLL_INTERVAL_SECONDS == 2.0


def test_cli_baseline_is_local_only_and_does_not_change_parent_mongo_settings(
    tmp_path, monkeypatch
):
    production_url = "mongodb://production.example.test/traffic_ai"
    monkeypatch.setenv("MONGO_URL", production_url)
    monkeypatch.setenv("REPO_BACKEND", "mongo")

    test_url = "mongodb://test.example.test/traffic_ai_test"
    database_name = "traffic_ai_test_0123456789"
    cli_env = s8_e2e._cli_environment(tmp_path / "storage", test_url, database_name)

    assert cli_env["REPO_BACKEND"] == "json"
    assert cli_env["STORAGE_DIR"] == str(tmp_path / "storage")
    assert cli_env["MONGO_URL"] == test_url
    assert cli_env["MONGO_DB"] == database_name
    assert os.environ["MONGO_URL"] == production_url
    assert os.environ["REPO_BACKEND"] == "mongo"
