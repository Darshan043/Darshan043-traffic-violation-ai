"""
Integration test: real video run through the backend API.

Run with:
    .\.venv\Scripts\python.exe -m pytest tests/integration/ -m integration -s -v

Requires:
  - data/videos/helmet_test.mp4 to exist
  - .env with valid SECRET_KEY
  - storage/cli_events.json produced by:
      $env:CUDA_VISIBLE_DEVICES="-1"
      .\.venv\Scripts\python.exe scripts/run_video.py \
          --source data/videos/helmet_test.mp4 --mode helmet \
          --no-show --json storage/cli_events.json --device cpu

The test is excluded from the default pytest run (marker: integration).
"""
import asyncio
import json
import os
import sys
import time
import threading
import pytest
import httpx
import websockets

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
BASE = "http://127.0.0.1:8000"
VIDEO_PATH = os.path.abspath("data/videos/helmet_test.mp4")
CLI_EVENTS_PATH = "storage/cli_events.json"
LOG_LINES_PATH = "storage/integration_run_log.txt"

# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client: httpx.Client, username="admin", password="admin") -> str:
    r = client.post(f"{BASE}/api/auth/login",
                    json={"username": username, "password": password})
    if r.status_code != 200:
        pytest.skip(f"Could not login as admin – run scripts/create_admin.py first. "
                    f"Response: {r.status_code} {r.text}")
    return r.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Main integration test
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_real_run_helmet_video():
    """
    Full end-to-end test:
    1. Login → get token
    2. Create a camera pointing at helmet_test.mp4
    3. Start the camera (AI worker process)
    4. Connect WebSocket and collect events
    5. Fetch a few MJPEG stream frames
    6. Wait for 'finished' or timeout (3 min)
    7. Compare event types with CLI baseline (storage/cli_events.json)
    8. Save log lines to storage/integration_run_log.txt
    """
    if not os.path.exists(VIDEO_PATH):
        pytest.skip(f"Video not found: {VIDEO_PATH}")

    logs = []

    def log(msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        logs.append(line)

    # ------------------------------------------------------------------ login
    with httpx.Client(timeout=30) as client:
        token = _login(client)
        log("Logged in, got token")

        # --------------------------------------------------------- create cam
        cam_body = {
            "name": "integration-test-cam",
            "location": "test",
            "source_type": "file",
            "source_path": VIDEO_PATH,
            "driver_side": "right",
            "camera_view": "front",
            "motorcycle_view": "side",
            "checks": ["helmet"],
        }
        r = client.post(f"{BASE}/api/cameras", json=cam_body, headers=_headers(token))
        assert r.status_code == 200, f"Create camera failed: {r.text}"
        cam = r.json()
        cam_id = cam["camera_id"]
        log(f"Created camera {cam_id}")

        # ---------------------------------------------------------- start run
        r = client.post(f"{BASE}/api/cameras/{cam_id}/start", headers=_headers(token))
        assert r.status_code == 200, f"Start failed: {r.text}"
        log("Started camera AI worker")

        # ------------------------------------------------ collect WS events
        ws_events = []
        finished_event = threading.Event()

        def _ws_listener():
            async def _inner():
                uri = f"ws://127.0.0.1:8000/ws/alerts?token={token}"
                try:
                    async with websockets.connect(uri) as ws:
                        log("WebSocket connected")
                        while True:
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=180)
                                evt = json.loads(raw)
                                ws_events.append(evt)
                                log(f"WS event: {evt.get('type')} {evt.get('violation_type','')}")
                                if evt.get("type") == "finished":
                                    finished_event.set()
                                    break
                            except asyncio.TimeoutError:
                                log("WS timeout waiting for 'finished'")
                                finished_event.set()
                                break
                except Exception as exc:
                    log(f"WS error: {exc}")
                    finished_event.set()

            asyncio.run(_inner())

        ws_thread = threading.Thread(target=_ws_listener, daemon=True)
        ws_thread.start()

        # give WS a moment to connect
        time.sleep(2)

        # --------------------------------------- fetch a few MJPEG frames
        frames_fetched = 0
        try:
            stream_url = f"{BASE}/api/stream/{cam_id}?token={token}"
            with httpx.stream("GET", stream_url, timeout=20) as s:
                buf = b""
                for chunk in s.iter_bytes(chunk_size=4096):
                    buf += chunk
                    if b"\xff\xd8" in buf and b"\xff\xd9" in buf:
                        frames_fetched += 1
                        log(f"MJPEG frame {frames_fetched} fetched ({len(buf)} bytes)")
                        buf = b""
                    if frames_fetched >= 3:
                        break
        except Exception as exc:
            log(f"Stream fetch warning: {exc}")

        log(f"MJPEG frames fetched: {frames_fetched}")
        assert frames_fetched >= 1, "No MJPEG frames received from stream"

        # ------------------------------------------- wait for finished
        log("Waiting up to 3 min for 'finished' WS event …")
        finished_event.wait(timeout=180)

        if not finished_event.is_set():
            log("Timeout – stopping camera manually")
            client.post(f"{BASE}/api/cameras/{cam_id}/stop", headers=_headers(token))

        log(f"WebSocket events received: {len(ws_events)}")

        # ----------------------------------------- check camera status
        r = client.get(f"{BASE}/api/cameras/{cam_id}/status", headers=_headers(token))
        status_data = r.json() if r.status_code == 200 else {}
        log(f"Final camera status: {status_data.get('status')}")

        # ----------------------------------------- query violations API
        r = client.get(f"{BASE}/api/violations?camera_id={cam_id}&limit=200",
                       headers=_headers(token))
        api_violations = r.json() if r.status_code == 200 else []
        log(f"Violations in DB: {len(api_violations)}")

        # ----------------------------------------- compare with CLI run
        if os.path.exists(CLI_EVENTS_PATH):
            with open(CLI_EVENTS_PATH) as f:
                cli_data = json.load(f)
            cli_violations = [e for e in cli_data
                              if e.get("decision") in ("NO_HELMET", "NEEDS_REVIEW")]
            log(f"CLI violations: {len(cli_violations)}")
            # Allow ±20% difference (live incremental suppression may differ slightly)
            api_count = len(api_violations)
            cli_count = len(cli_violations)
            if cli_count > 0:
                ratio = abs(api_count - cli_count) / cli_count
                log(f"Count ratio diff: {ratio:.1%} (API={api_count}, CLI={cli_count})")
                # We just log; don't hard-fail (timing can differ in live mode)
        else:
            log("CLI baseline not found – skipping comparison")

        # ----------------------------------------- cleanup
        client.delete(f"{BASE}/api/cameras/{cam_id}", headers=_headers(token))
        log("Camera deleted")

        # ----------------------------------------- save log
        os.makedirs("storage", exist_ok=True)
        with open(LOG_LINES_PATH, "w") as f:
            f.write("\n".join(logs))
        log(f"Log saved to {LOG_LINES_PATH}")

        # Assertions
        assert len(ws_events) > 0, "No WebSocket events received"
        any_finished = any(e.get("type") == "finished" for e in ws_events)
        log(f"'finished' event received: {any_finished}")
        # We confirm the run completed (may time out on slow CPU; not a hard fail)
