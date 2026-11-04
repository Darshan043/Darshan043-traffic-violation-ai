"""Run the Stage 7 backend smoke checks against an isolated temporary store."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid

import httpx
import psutil
import websockets


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BASE_URL = "http://127.0.0.1:8000"
HEALTH_URL = f"{BASE_URL}/api/health"
VIDEO_PATH = ROOT / "data" / "videos" / "helmet_test.mp4"
CLI_EVENTS_PATH = ROOT / "storage" / "cli_events.json"
ZONE_PATH = ROOT / "ai_engine" / "config" / "cameras" / "helmet_test.json"
STREAM_OUTPUT = ROOT / "data" / "output" / "s7_stream"
CHECKS: list[tuple[str, bool, str]] = []


def report(name: str, passed: bool, details: str = "") -> None:
    CHECKS.append((name, passed, details))
    state = "PASS" if passed else "FAIL"
    suffix = f" :: {details}" if details else ""
    print(f"{state}: {name}{suffix}", flush=True)


def require(name: str, passed: bool, details: str = "") -> None:
    report(name, passed, details)
    if not passed:
        raise RuntimeError(f"Smoke check failed: {name}")


def _safe_error(response: httpx.Response) -> str:
    message = re.sub(r"(?i)(token=)[^&\s'\"]+", r"\1REDACTED", response.text)
    return f"HTTP {response.status_code}: {message[:300]}"


def _api(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str | None = None,
    expected: int = 200,
    **kwargs,
) -> httpx.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{BASE_URL}{path}", headers=headers, **kwargs)
    require(
        f"{method} {path} returns {expected}",
        response.status_code == expected,
        "" if response.status_code == expected else _safe_error(response),
    )
    return response


def _start_backend(storage_dir: Path, log_path: Path, device: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["STORAGE_DIR"] = str(storage_dir)
    env["SECRET_KEY"] = os.environ["S7_SMOKE_SECRET_KEY"]
    env["TRAFFIC_AI_DEVICE"] = device
    env.pop("S7_SMOKE_PASSWORD", None)
    env.pop("S7_SMOKE_SECRET_KEY", None)
    env.pop("CUDA_VISIBLE_DEVICES", None)
    if device == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = "-1"
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    return process


def _wait_for_backend(process: subprocess.Popen, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Backend exited before becoming healthy")
            try:
                if client.get(HEALTH_URL).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.25)
    raise TimeoutError("Backend health check timed out")


def _stop_backend(
    process: subprocess.Popen | None,
    camera_id: str | None = None,
    token: str | None = None,
) -> None:
    if process is None or process.poll() is not None:
        return
    if camera_id and token:
        try:
            response = httpx.post(
                f"{BASE_URL}/api/cameras/{camera_id}/stop",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            print(f"CLEANUP: stop camera returned HTTP {response.status_code}", flush=True)
        except httpx.HTTPError:
            print("CLEANUP: API stop could not be reached; checking worker processes", flush=True)
    child_pids = [child.pid for child in _backend_children(process.pid)]
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Stop-Process -Id {int(process.pid)} -Force",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Backend PID {process.pid} did not exit after Stop-Process") from exc
    for child_pid in child_pids:
        if psutil.pid_exists(child_pid):
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Stop-Process -Id {int(child_pid)} -Force",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"CLEANUP: stopped leftover worker PID {child_pid}", flush=True)


class WebSocketRecorder:
    def __init__(self, token: str) -> None:
        self._uri = f"ws://127.0.0.1:8000/ws/alerts?token={token}"
        self.connected = threading.Event()
        self.finished = threading.Event()
        self.offline = threading.Event()
        self.stopped = threading.Event()
        self.messages: list[dict] = []
        self.errors: list[str] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        if not self.connected.wait(timeout=15):
            raise TimeoutError("WebSocket did not connect")
        if self.errors:
            raise RuntimeError("WebSocket connection failed")

    def _run(self) -> None:
        async def receive() -> None:
            try:
                async with websockets.connect(self._uri, open_timeout=10) as socket:
                    self.connected.set()
                    while not self.stopped.is_set():
                        try:
                            raw = await asyncio.wait_for(socket.recv(), timeout=0.25)
                        except asyncio.TimeoutError:
                            continue
                        message = json.loads(raw)
                        self.messages.append({
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "received_monotonic": time.monotonic(),
                            "message": message,
                        })
                        if message.get("type") == "finished":
                            self.finished.set()
                        elif (
                            message.get("type") == "camera_status"
                            and message.get("status") == "offline"
                        ):
                            self.offline.set()
            except Exception:
                self.errors.append("WebSocket receive failed")
                self.connected.set()

        asyncio.run(receive())

    def close(self) -> None:
        self.stopped.set()
        self.thread.join(timeout=5)


def _read_mjpeg_frames(
    client: httpx.Client,
    camera_id: str,
    token: str,
    count: int,
    timeout: float = 30,
    ignore_frame: bytes | None = None,
) -> list[bytes]:
    frames: list[bytes] = []
    buffer = bytearray()
    with client.stream(
        "GET",
        f"{BASE_URL}/api/stream/{camera_id}",
        params={"token": token},
        timeout=httpx.Timeout(timeout, read=timeout),
    ) as response:
        require("MJPEG endpoint responds", response.status_code == 200, f"HTTP {response.status_code}")
        for chunk in response.iter_bytes(chunk_size=8192):
            buffer.extend(chunk)
            while len(frames) < count:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 1024 * 1024:
                        del buffer[:-2]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start:end + 2])
                if frame != ignore_frame:
                    frames.append(frame)
                del buffer[:end + 2]
            if len(frames) >= count:
                break
    return frames


def _backend_children(server_pid: int) -> list[psutil.Process]:
    try:
        return psutil.Process(server_pid).children(recursive=True)
    except psutil.Error:
        return []


def _run_cli_baseline(device: str, output_dir: Path) -> tuple[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "cli_events.json"
    evidence_path = output_dir / "evidence"

    def run(selected_device: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("S7_SMOKE_PASSWORD", None)
        env.pop("S7_SMOKE_SECRET_KEY", None)
        env.pop("CUDA_VISIBLE_DEVICES", None)
        if selected_device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = "-1"
        return subprocess.run(
            [
                sys.executable,
                "scripts/run_video.py",
                "--source",
                str(VIDEO_PATH),
                "--mode",
                "helmet",
                "--device",
                selected_device,
                "--no-show",
                "--json",
                str(events_path),
                "--evidence-dir",
                str(evidence_path),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    result = run(device)
    if result.returncode != 0 and device != "cpu" and "cuda" in result.stderr.lower():
        report("CLI CUDA run failed; retry baseline on CPU", True, result.stderr[-250:].strip())
        device = "cpu"
        result = run(device)
    if result.returncode != 0:
        error = re.sub(r"(?i)(token=)[^&\s'\"]+", r"\1REDACTED", result.stderr[-500:])
        raise RuntimeError(f"CLI baseline failed on {device}: {error}")
    cli_events = json.loads(events_path.read_text(encoding="utf-8"))
    require("Run CLI baseline before starting backend", isinstance(cli_events, list))
    print(result.stdout[-1500:], flush=True)
    report("CLI baseline device", True, device)
    return device, events_path


def _wait_for_worker(server_pid: int, timeout: float = 15.0) -> psutil.Process:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        children = _backend_children(server_pid)
        if children:
            return max(children, key=lambda process: process.create_time())
        time.sleep(0.1)
    raise TimeoutError("AI worker process did not appear under the backend")


def _map_cli_result(event: dict) -> str:
    from backend.app.models.event import result_from_pipeline

    return result_from_pipeline(event.get("decision", ""), event.get("ai_result", ""))


def _run_first_video(
    client: httpx.Client,
    camera_id: str,
    token: str,
    device: str,
) -> tuple[WebSocketRecorder, list[dict], str]:
    recorder = WebSocketRecorder(token)
    recorder.start()
    no_signal = _read_mjpeg_frames(client, camera_id, token, 1)[0]
    report("Capture pre-run MJPEG placeholder for comparison", True)
    _api(client, "POST", f"/api/cameras/{camera_id}/start", token=token)
    frames = _read_mjpeg_frames(
        client,
        camera_id,
        token,
        10,
        timeout=60,
        ignore_frame=no_signal,
    )
    require(
        "Fetch 10 live MJPEG frames",
        len(frames) == 10,
        f"got {len(frames)} frames different from the pre-run placeholder",
    )
    STREAM_OUTPUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for index, frame in enumerate(frames[:3], start=1):
        (STREAM_OUTPUT / f"stage7_{stamp}_{index}.jpg").write_bytes(frame)
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(STREAM_OUTPUT)],
        cwd=ROOT,
        check=False,
    ).returncode == 0
    require("Save 3 stream frames under ignored output", ignored and len(frames[:3]) == 3)

    deadline = time.monotonic() + 300
    status_text = ""
    while time.monotonic() < deadline:
        response = client.get(
            f"{BASE_URL}/api/cameras/{camera_id}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Camera status request failed with HTTP {response.status_code}")
        status_text = response.json().get("status", "")
        if status_text == "error":
            errors = [
                item["message"].get("error", "")
                for item in recorder.messages
                if item["message"].get("type") == "camera_status"
                and item["message"].get("status") == "error"
            ]
            recorder.close()
            error_text = " ".join(errors)
            if device != "cpu" and "cuda" in error_text.lower():
                return recorder, frames, error_text
            raise RuntimeError("Video worker failed: " + error_text[:250])
        if status_text == "offline" and recorder.finished.wait(timeout=0.1):
            break
        time.sleep(0.2)
    require(
        "Video run reaches finished",
        status_text == "offline" and recorder.finished.is_set(),
        f"status={status_text}, finished={recorder.finished.is_set()}",
    )
    finish_entry = next(
        entry for entry in recorder.messages
        if entry["message"].get("type") == "finished"
    )
    candidates = [
        entry for entry in recorder.messages
        if entry["message"].get("type") == "event_candidate"
    ]
    first_before_finish = bool(candidates) and (
        candidates[0]["received_monotonic"] < finish_entry["received_monotonic"]
    )
    require(
        "Receive live alert before run finishes",
        first_before_finish,
        (
            f"first={candidates[0]['received_at']}; "
            f"finished={finish_entry['received_at']}"
        ) if first_before_finish else "no candidate arrived before finished",
    )
    recorder.offline.wait(timeout=2)
    return recorder, frames, ""


def main() -> int:
    python_path = Path(sys.executable).resolve()
    expected_python = (ROOT / ".venv" / "Scripts" / "python.exe").resolve()
    require(
        "Run with project virtual environment",
        python_path == expected_python,
        str(python_path),
    )
    password = os.environ.get("S7_SMOKE_PASSWORD", "")
    require(
        "Throwaway password provided through environment",
        len(password) >= 8,
        "S7_SMOKE_PASSWORD must contain at least 8 characters",
    )
    require("Test video exists", VIDEO_PATH.is_file())
    require("Camera zone config exists", ZONE_PATH.is_file())

    device = "cuda:0"
    backend = None
    recorder = None
    temp_context = tempfile.TemporaryDirectory(prefix="traffic-ai-stage7-")
    temp_root = Path(temp_context.name)
    storage_dir = temp_root / "storage"
    log_path = temp_root / "uvicorn.log"
    os.environ["S7_SMOKE_SECRET_KEY"] = uuid.uuid4().hex + uuid.uuid4().hex

    try:
        device, cli_events_path = _run_cli_baseline(device, temp_root / "cli")
        os.environ["STORAGE_DIR"] = str(storage_dir)
        os.environ["SECRET_KEY"] = os.environ["S7_SMOKE_SECRET_KEY"]
        from backend.app.core.security import get_password_hash
        from backend.app.db.json_repo import JsonFileRepository
        from backend.app.models.user import User

        bootstrap_name = "s7-bootstrap"
        repository = JsonFileRepository(data_dir=storage_dir / "data")
        repository.save_user(User(
            id="s7-bootstrap-user",
            username=bootstrap_name,
            hashed_password=get_password_hash(password),
            role="admin",
            is_active=True,
        ))
        report("Create isolated temporary test user", True, "password supplied only via S7_SMOKE_PASSWORD")

        backend = _start_backend(storage_dir, log_path, device)
        _wait_for_backend(backend)
        report("Start backend on port 8000", True, f"PID {backend.pid}; device attempt {device}")

        with httpx.Client(timeout=30) as client:
            _api(client, "GET", "/api/health")
            bootstrap_login = _api(
                client,
                "POST",
                "/api/auth/login",
                expected=200,
                json={"username": bootstrap_name, "password": password},
            ).json()
            bootstrap_token = bootstrap_login["access_token"]
            user_name = f"s7-{uuid.uuid4().hex[:8]}"
            _api(
                client,
                "POST",
                "/api/users",
                token=bootstrap_token,
                expected=201,
                json={"username": user_name, "password": password, "role": "admin"},
            )
            token = _api(
                client,
                "POST",
                "/api/auth/login",
                expected=200,
                json={"username": user_name, "password": password},
            ).json()["access_token"]
            report("Create and API-login as throwaway test user", True, user_name)

            camera_id = f"s7-{uuid.uuid4().hex[:8]}"
            zone_data = json.loads(ZONE_PATH.read_text(encoding="utf-8"))
            zone = zone_data.get("zone", [[0.0, 0.9], [1.0, 0.9]])
            if zone and isinstance(zone[0], (list, tuple)):
                zone = [coordinate for point in zone for coordinate in point]
            _api(
                client,
                "POST",
                "/api/cameras",
                token=token,
                expected=201,
                json={
                    "camera_id": camera_id,
                    "name": "Stage 7 API Smoke",
                    "location": "temporary",
                    "source_type": "file",
                    "checks": ["helmet"],
                    "camera_view": zone_data.get("camera_view", "unknown"),
                    "motorcycle_view": zone_data.get("motorcycle_view", "approaching"),
                },
            )
            with VIDEO_PATH.open("rb") as source_video:
                upload = _api(
                    client,
                    "POST",
                    f"/api/cameras/{camera_id}/video",
                    token=token,
                    expected=200,
                    files={"file": (VIDEO_PATH.name, source_video, "video/mp4")},
                )
            require("Upload helmet_test.mp4 through API", upload.json()["source_type"] == "file")
            zone_response = _api(
                client,
                "PUT",
                f"/api/cameras/{camera_id}/zone",
                token=token,
                json={"points": zone},
            )
            require("Set zone from helmet_test.json through API", zone_response.json()["zone"] == zone)

            recorder, frames, cuda_error = _run_first_video(
                client,
                camera_id,
                token,
                device,
            )
            if cuda_error:
                report("CUDA attempt failed; retry on CPU", True, cuda_error[:180])
                _api(client, "POST", f"/api/cameras/{camera_id}/stop", token=token)
                recorder.close()
                _stop_backend(backend)
                device, cli_events_path = _run_cli_baseline(
                    "cpu",
                    temp_root / "cli_cpu",
                )
                backend = _start_backend(storage_dir, log_path, "cpu")
                _wait_for_backend(backend)
                report("Restart backend in CPU-only mode", True, f"PID {backend.pid}")
                recorder, frames, cpu_error = _run_first_video(
                    client,
                    camera_id,
                    token,
                    device,
                )
                require("CPU fallback completes real run", not cpu_error)
            else:
                report("CUDA inference completes real run", True, "device cuda:0")
            require("WebSocket records run messages", bool(recorder.messages))
            for entry in recorder.messages:
                message = entry["message"]
                print(
                    f"WS {entry['received_at']} {message.get('type')} "
                    f"{message.get('status', message.get('camera_id', ''))}",
                    flush=True,
                )
            finished_entry = next(
                entry for entry in recorder.messages
                if entry["message"].get("type") == "finished"
            )
            report(
                "Record WebSocket timestamps",
                True,
                f"finished at {finished_entry['received_at']}",
            )
            recorder.close()

            stored_path = storage_dir / "data" / "vehicle_events.json"
            stored_events = json.loads(stored_path.read_text(encoding="utf-8"))
            api_results = sorted(item["result"] for item in stored_events
                                 if item.get("camera_id") == camera_id)
            cli_events = json.loads(cli_events_path.read_text(encoding="utf-8"))
            cli_results = sorted(_map_cli_result(item) for item in cli_events)
            same_run = len(api_results) == len(cli_results) and Counter(api_results) == Counter(cli_results)
            report(
                "Backend events match CLI count and results",
                same_run,
                f"API={api_results}; CLI={cli_results}",
            )

            camera_two_id = f"s7-{uuid.uuid4().hex[:8]}"
            _api(
                client,
                "POST",
                "/api/cameras",
                token=token,
                expected=201,
                json={
                    "camera_id": camera_two_id,
                    "name": "Stage 7 Conflict Test",
                    "source_type": "file",
                    "source_path": str(VIDEO_PATH),
                    "checks": ["helmet"],
                },
            )
            _api(client, "POST", f"/api/cameras/{camera_id}/start", token=token)
            worker = _wait_for_worker(backend.pid)
            worker_pid = worker.pid
            rss_before = worker.memory_info().rss
            stop_started = time.monotonic()
            _api(client, "POST", f"/api/cameras/{camera_id}/stop", token=token)
            stop_seconds = time.monotonic() - stop_started
            try:
                rss_after = psutil.Process(worker_pid).memory_info().rss
            except psutil.NoSuchProcess:
                rss_after = 0
            exited = not psutil.pid_exists(worker_pid)
            require(
                "Stop second run and release worker memory",
                exited and stop_seconds <= 4.5 and rss_after < rss_before,
                f"worker PID {worker_pid}; stop {stop_seconds:.2f}s; RSS "
                f"{rss_before / 1024 / 1024:.1f} -> {rss_after / 1024 / 1024:.1f} MiB",
            )

            _api(client, "POST", f"/api/cameras/{camera_id}/start", token=token)
            conflict = _api(
                client,
                "POST",
                f"/api/cameras/{camera_two_id}/start",
                token=token,
                expected=409,
            )
            require("Second camera is rejected while a worker is active", conflict.status_code == 409)
            _api(client, "POST", f"/api/cameras/{camera_id}/stop", token=token)
            _api(client, "DELETE", f"/api/cameras/{camera_two_id}", token=token, expected=204)
            _api(client, "DELETE", f"/api/cameras/{camera_id}", token=token, expected=204)

        _stop_backend(backend)
        backend = None
        log_files = list((storage_dir / "logs").glob("*")) if (storage_dir / "logs").exists() else []
        log_text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_files)
        server_log = log_path.read_text(encoding="utf-8", errors="replace")
        token_absent = token not in log_text and token not in server_log
        access_redacted = "token=REDACTED" in server_log
        report("No JWT appears in storage/logs or server output", token_absent)
        report("Uvicorn access log redacts stream JWT", access_redacted)
        print(f"DEVICE: {device}", flush=True)
        print(f"STREAM_FRAMES: {len(frames)} fetched; 3 saved to {STREAM_OUTPUT}", flush=True)
        passed = all(passed for _, passed, _ in CHECKS)
        print(f"RESULT: {'PASS' if passed else 'FAIL'} ({len(CHECKS)} checks)", flush=True)
        return 0 if passed else 1
    except Exception as exc:
        message = re.sub(r"(?i)(token=)[^&\s'\"]+", r"\1REDACTED", str(exc))
        if password:
            message = message.replace(password, "***")
        if "token" in locals():
            message = message.replace(token, "REDACTED")
        report("Smoke run completes", False, f"{type(exc).__name__}: {message}")
        print(f"RESULT: FAIL ({len(CHECKS)} checks)", flush=True)
        return 1
    finally:
        if recorder is not None:
            recorder.close()
        if backend is not None:
            _stop_backend(
                backend,
                locals().get("camera_id"),
                locals().get("token"),
            )
        temp_context.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
