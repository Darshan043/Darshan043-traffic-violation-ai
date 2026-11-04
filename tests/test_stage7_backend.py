"""Comprehensive test suite for Stage 7 FastAPI backend (no real models)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import io
import logging
import multiprocessing as mp
from pathlib import Path
import queue
import threading
import time
import cv2
from fastapi import status
from fastapi.testclient import TestClient
import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app.core.config import settings
from backend.app.core.logging_config import SensitiveDataRedactionFilter
from backend.app.core.security import create_access_token, get_password_hash
from backend.app.db.json_repo import JsonFileRepository
from backend.app.deps import _login_failures, set_repository
from backend.app.main import app
from backend.app.models.camera import Camera
from backend.app.models.event import VehicleEvent, result_from_pipeline
from backend.app.models.user import User
from backend.app.models.violation import Violation
from backend.app.services.alert_service import alert_broadcaster
from backend.app.services.engine_manager import WorkerHandle, engine_manager


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    """Isolate repository storage, reset rate limits, and ensure engine manager is stopped."""
    test_repo = JsonFileRepository(data_dir=tmp_path / "data")
    set_repository(test_repo)
    _login_failures.clear()

    # Prepopulate default admin, reviewer, and viewer users
    admin_user = User(
        id="usr_admin_1",
        username="admin",
        hashed_password=get_password_hash("adminpassword123"),
        role="admin",
        is_active=True,
    )
    reviewer_user = User(
        id="usr_reviewer_1",
        username="reviewer",
        hashed_password=get_password_hash("reviewerpassword123"),
        role="reviewer",
        is_active=True,
    )
    viewer_user = User(
        id="usr_viewer_1",
        username="viewer",
        hashed_password=get_password_hash("viewerpassword123"),
        role="viewer",
        is_active=True,
    )
    test_repo.save_user(admin_user)
    test_repo.save_user(reviewer_user)
    test_repo.save_user(viewer_user)

    # Monkeypatch evidence and upload dirs to tmp_path
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "storage"))

    yield test_repo

    # Cleanup any active worker
    if engine_manager.active_worker and engine_manager.active_worker.process.is_alive():
        engine_manager.active_worker.stop_event.set()
        engine_manager.active_worker.process.terminate()
        engine_manager.active_worker = None


@pytest.fixture
def client():
    return TestClient(app)


def _token_for(user: User) -> str:
    return create_access_token({"sub": user.id, "role": user.role})


# ==========================================
# 1. AUTHENTICATION & RATE LIMIT TESTS
# ==========================================

def test_login_success(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "adminpassword123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["role"] == "admin"


def test_login_invalid_password(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrongpassword"})
    assert res.status_code == 401
    assert res.json()["error"] == "UNAUTHORIZED"


def test_login_nonexistent_user(client):
    res = client.post("/api/auth/login", json={"username": "doesnotexist", "password": "password"})
    assert res.status_code == 401
    assert res.json()["error"] == "UNAUTHORIZED"


def test_login_rate_limit(client):
    # 5 failed attempts allowed, 6th triggers 429
    for _ in range(5):
        res = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
        assert res.status_code == 401

    res = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    assert res.status_code == 429
    assert res.json()["error"] == "TOO_MANY_REQUESTS"


def test_auth_me_valid_token(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["username"] == "admin"


def test_auth_me_missing_token_401(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert res.json()["error"] == "UNAUTHORIZED"


def test_auth_me_invalid_token_401(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.jwt.token"})
    assert res.status_code == 401
    assert res.json()["error"] == "UNAUTHORIZED"


# ==========================================
# 2. ROLE ENFORCEMENT & USER MANAGEMENT
# ==========================================

def test_role_enforcement_viewer_forbidden_on_admin(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)
    res = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert res.json()["error"] == "FORBIDDEN"


def test_role_enforcement_reviewer_forbidden_on_admin(client, clean_state):
    reviewer = clean_state.get_user_by_username("reviewer")
    token = _token_for(reviewer)
    res = client.post(
        "/api/users",
        json={"username": "newuser", "password": "password123", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_admin_create_user_and_list(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)
    res = client.post(
        "/api/users",
        json={"username": "analyst1", "password": "securepass123", "role": "reviewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == "analyst1"
    assert data["role"] == "reviewer"

    list_res = client.get("/api/users", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == 200
    usernames = [u["username"] for u in list_res.json()]
    assert "analyst1" in usernames


def test_admin_create_user_duplicate_username_400(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)
    res = client.post(
        "/api/users",
        json={"username": "admin", "password": "anotherpassword", "role": "viewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "BAD_REQUEST"


def test_admin_update_user(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(admin)
    res = client.put(
        f"/api/users/{viewer.id}",
        json={"role": "reviewer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["role"] == "reviewer"


def test_admin_cannot_disable_self(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)
    res = client.put(
        f"/api/users/{admin.id}",
        json={"is_active": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert "cannot disable themselves" in res.json()["message"]

    del_res = client.delete(f"/api/users/{admin.id}", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 400


def test_admin_delete_user_disables_user(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(admin)
    res = client.delete(f"/api/users/{viewer.id}", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["is_active"] is False


# ==========================================
# 3. CAMERA CRUD & RTSP PASSWORD PROTECTION
# ==========================================

def test_camera_crud_and_rtsp_protection(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam_data = {
        "camera_id": "cam_junction_1",
        "name": "Main Junction North",
        "location": "Sector 4",
        "source_type": "rtsp",
        "source_path": "rtsp://operator:supersecretpassword@192.168.1.100:554/stream1",
        "driver_side": "right",
        "camera_view": "front",
        "motorcycle_view": "approaching",
        "checks": ["helmet", "seatbelt"],
        "zone": [0.1, 0.8, 0.9, 0.8],
    }
    create_res = client.post("/api/cameras", json=cam_data, headers={"Authorization": f"Bearer {token}"})
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["camera_id"] == "cam_junction_1"
    # Never return RTSP password!
    assert "supersecretpassword" not in created["source_path"]
    assert "rtsp://operator:***@192.168.1.100:554/stream1" in created["source_path"]

    get_res = client.get("/api/cameras/cam_junction_1", headers={"Authorization": f"Bearer {token}"})
    assert get_res.status_code == 200
    assert "supersecretpassword" not in get_res.json()["source_path"]

    list_res = client.get("/api/cameras", headers={"Authorization": f"Bearer {token}"})
    assert list_res.status_code == 200
    for cam in list_res.json():
        assert "supersecretpassword" not in cam["source_path"]

    up_res = client.put(
        "/api/cameras/cam_junction_1",
        json={"name": "Main Junction Renovated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up_res.status_code == 200
    assert up_res.json()["name"] == "Main Junction Renovated"

    stat_res = client.get("/api/cameras/cam_junction_1/status", headers={"Authorization": f"Bearer {token}"})
    assert stat_res.status_code == 200
    assert stat_res.json()["status"] == "offline"

    del_res = client.delete("/api/cameras/cam_junction_1", headers={"Authorization": f"Bearer {token}"})
    assert del_res.status_code == 204


# ==========================================
# 4. VIDEO UPLOAD VALIDATION
# ==========================================

def test_upload_video_success(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_upload_test", name="Upload Cam")
    clean_state.save_camera(cam)

    file_content = b"\x00\x00\x00\x18ftypmp42" + b"dummy mp4 payload"
    res = client.post(
        "/api/cameras/cam_upload_test/video",
        files={"file": ("traffic_demo.mp4", file_content, "video/mp4")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["source_type"] == "file"
    assert "traffic_demo.mp4" in data["source_path"] or "cam_upload_test" in data["source_path"]


def test_upload_video_bad_extension_400(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_bad_ext", name="Ext Cam")
    clean_state.save_camera(cam)

    res = client.post(
        "/api/cameras/cam_bad_ext/video",
        files={"file": ("malicious.exe", b"MZ...", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert res.json()["error"] == "BAD_REQUEST"


def test_upload_video_path_traversal_trick_400(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_trick", name="Trick Cam")
    clean_state.save_camera(cam)

    res = client.post(
        "/api/cameras/cam_trick/video",
        files={"file": ("../../etc/passwd.mp4", b"data", "video/mp4")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert "path traversal" in res.json()["message"].lower()


# ==========================================
# 5. ZONE SAVE & VALIDATION
# ==========================================

def test_camera_zone_save_valid(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_zone", name="Zone Cam")
    clean_state.save_camera(cam)

    poly = [0.1, 0.2, 0.8, 0.2, 0.8, 0.9, 0.1, 0.9]
    res = client.put(
        "/api/cameras/cam_zone/zone",
        json={"points": poly},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["zone"] == poly


def test_camera_zone_validation_rejects_odd_or_small_points(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_zone_err", name="Err Cam")
    clean_state.save_camera(cam)

    # Odd count
    res1 = client.put(
        "/api/cameras/cam_zone_err/zone",
        json={"points": [0.1, 0.2, 0.3]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res1.status_code == 422

    # Fewer than 2 points (4 numbers)
    res2 = client.put(
        "/api/cameras/cam_zone_err/zone",
        json={"points": [0.1, 0.2]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res2.status_code == 422


def test_camera_zone_validation_rejects_unnormalized_points(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam = Camera(camera_id="cam_zone_norm", name="Norm Cam")
    clean_state.save_camera(cam)

    res = client.put(
        "/api/cameras/cam_zone_norm/zone",
        json={"points": [10.0, 20.0, 100.0, 200.0]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


# ==========================================
# 6. CAMERA SNAPSHOT ENDPOINT
# ==========================================

def test_camera_snapshot_returns_jpeg(client, clean_state, tmp_path):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    # Create dummy single-frame video
    vid_path = tmp_path / "snap.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(vid_path), fourcc, 25.0, (64, 48))
    writer.write(np.full((48, 64, 3), 120, dtype=np.uint8))
    writer.release()

    cam = Camera(camera_id="cam_snap", name="Snap Cam", source_path=str(vid_path))
    clean_state.save_camera(cam)

    res = client.get("/api/cameras/cam_snap/snapshot", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content.startswith(b"\xff\xd8")


# ==========================================
# 7. VIOLATIONS, REVIEW & CSV EXPORT
# ==========================================

def test_violations_filtering_and_review(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    v1 = Violation(
        event_id="ev_001",
        camera_id="cam1",
        track_id=10,
        violation_type="helmet",
        ai_result="no_helmet",
        detection_confidence=0.94,
        reason_code="NO_HELMET",
        review_status="UNREVIEWED",
        created_at="2026-11-04T10:00:00Z",
    )
    v2 = Violation(
        event_id="ev_002",
        camera_id="cam2",
        track_id=20,
        violation_type="seatbelt",
        ai_result="no_seatbelt",
        detection_confidence=0.88,
        reason_code="NO_SEATBELT",
        review_status="UNREVIEWED",
        created_at="2026-11-04T11:00:00Z",
    )
    clean_state.save_violation(v1)
    clean_state.save_violation(v2)

    # Filter by violation_type
    res_h = client.get("/api/violations?type=helmet", headers={"Authorization": f"Bearer {token}"})
    assert res_h.status_code == 200
    assert len(res_h.json()["items"]) == 1
    assert res_h.json()["items"][0]["event_id"] == "ev_001"

    # Human review: final_decision="DISMISSED", ai_result MUST REMAIN "no_helmet"
    review_res = client.put(
        "/api/violations/ev_001/review",
        json={"final_decision": "DISMISSED", "review_note": "Turban identified on closer inspection"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert review_res.status_code == 200
    rev_data = review_res.json()
    assert rev_data["review_status"] == "REVIEWED"
    assert rev_data["final_decision"] == "DISMISSED"
    assert rev_data["reviewed_by"] == "admin"
    assert rev_data["ai_result"] == "no_helmet"  # UNCHANGED!


def test_violations_export_csv(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    v = Violation(
        event_id="ev_csv_1",
        camera_id="cam_csv",
        track_id=5,
        violation_type="helmet",
        ai_result="no_helmet",
        detection_confidence=0.91,
        reason_code="NO_HELMET",
        review_status="UNREVIEWED",
    )
    clean_state.save_violation(v)

    res = client.get("/api/violations/export", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    text = res.text
    assert "event_id,camera_id,track_id" in text
    assert "ev_csv_1" in text
    assert "cam_csv" in text


# ==========================================
# 8. STATS COMPLIANCE FORMULA
# ==========================================

def test_stats_summary_formula(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    for i in range(8):
        clean_state.save_vehicle_event(VehicleEvent(
            event_id=f"c_{i}", camera_id="cam1", track_id=i, vehicle_type="car",
            violation_type="seatbelt", decision="COMPLIANCE", ai_result="seatbelt",
        ))
    for i in range(2):
        clean_state.save_vehicle_event(VehicleEvent(
            event_id=f"v_{i}", camera_id="cam1", track_id=10+i, vehicle_type="car",
            violation_type="seatbelt", decision="VIOLATION", ai_result="no_seatbelt",
        ))
    for i in range(5):
        clean_state.save_vehicle_event(VehicleEvent(
            event_id=f"nr_{i}", camera_id="cam1", track_id=20+i, vehicle_type="car",
            violation_type="seatbelt", decision="NEEDS_REVIEW", ai_result="unclear",
        ))

    res = client.get("/api/stats/summary", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["total_vehicles"] == 15
    assert data["compliant_vehicles"] == 8
    assert data["violations"] == 2
    assert data["needs_review"] == 5
    assert data["compliance_percentage"] == 80.0


def test_pipeline_result_mapping_uses_repository_labels():
    cases = (
        ("COMPLIANCE", "helmet", "HELMET"),
        ("VIOLATION", "no_helmet", "NO_HELMET"),
        ("COMPLIANCE", "seatbelt", "SEATBELT"),
        ("VIOLATION", "no_seatbelt", "NO_SEATBELT"),
        ("NEEDS_REVIEW", "unclear", "NEEDS_REVIEW"),
        ("NOT_CHECKED", "unclear", "NOT_CHECKED"),
    )

    for decision, ai_result, expected in cases:
        event = VehicleEvent(
            event_id=f"{decision}_{ai_result}",
            camera_id="cam_labels",
            track_id=1,
            vehicle_type="motorcycle",
            violation_type="helmet",
            decision=decision,
            ai_result=ai_result,
        )
        assert event.result == expected
        assert event.model_dump()["result"] == expected
        assert result_from_pipeline(decision, ai_result) == expected


def test_no_helmet_pipeline_event_is_stored_as_a_violation(clean_state, monkeypatch):
    broadcasts = []

    def close_scheduled_coroutine(coroutine, _):
        broadcasts.append(True)
        coroutine.close()

    monkeypatch.setattr(
        "backend.app.services.engine_manager.asyncio.run_coroutine_threadsafe",
        close_scheduled_coroutine,
    )
    engine_manager._record_event(
        {
            "event_id": "ev_no_helmet",
            "camera_id": "cam_labels",
            "track_id": 7,
            "vehicle_type": "motorcycle",
            "violation_type": "helmet",
            "decision": "VIOLATION",
            "ai_result": "no_helmet",
            "confidence": 0.94,
            "reason": "NO_HELMET",
        },
        clean_state,
        None,
    )

    stored = clean_state.list_vehicle_events("cam_labels")
    assert len(stored) == 1
    assert stored[0].result == "NO_HELMET"
    assert clean_state.get_violation("ev_no_helmet") is not None
    assert broadcasts


def test_review_events_are_excluded_from_compliance_percentage(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    for event_id, decision, ai_result in (
        ("helmet_ok", "COMPLIANCE", "helmet"),
        ("helmet_violation", "VIOLATION", "no_helmet"),
        ("helmet_review", "NEEDS_REVIEW", "unclear"),
    ):
        clean_state.save_vehicle_event(VehicleEvent(
            event_id=event_id,
            camera_id="cam_labels",
            track_id=1,
            vehicle_type="motorcycle",
            violation_type="helmet",
            decision=decision,
            ai_result=ai_result,
        ))

    response = client.get(
        "/api/stats/summary",
        headers={"Authorization": f"Bearer {_token_for(viewer)}"},
    )

    assert response.status_code == 200
    assert response.json()["compliant_vehicles"] == 1
    assert response.json()["violations"] == 1
    assert response.json()["needs_review"] == 1
    assert response.json()["compliance_percentage"] == 50.0


def test_stats_daily_and_cameras(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    clean_state.save_camera(Camera(camera_id="cam_stat", name="Stat Camera"))
    clean_state.save_vehicle_event(VehicleEvent(
        event_id="e_stat", camera_id="cam_stat", track_id=1, vehicle_type="motorcycle",
        violation_type="helmet", decision="COMPLIANCE", ai_result="helmet",
        created_at="2026-11-04T12:00:00Z",
    ))

    daily_res = client.get("/api/stats/daily", headers={"Authorization": f"Bearer {token}"})
    assert daily_res.status_code == 200
    assert len(daily_res.json()) >= 1
    assert daily_res.json()[0]["date"] == "2026-11-04"

    cam_res = client.get("/api/stats/cameras", headers={"Authorization": f"Bearer {token}"})
    assert cam_res.status_code == 200
    assert len(cam_res.json()) >= 1
    assert cam_res.json()[0]["camera_id"] == "cam_stat"


# ==========================================
# 9. SENSITIVE DATA LOG REDACTION
# ==========================================

def test_sensitive_token_redaction_in_logs():
    redactor = SensitiveDataRedactionFilter()

    raw_url = "GET /api/stream/cam1?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret HTTP/1.1"
    clean_url = redactor.redact(raw_url)
    assert "token=REDACTED" in clean_url
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in clean_url

    raw_rtsp = "Connecting to rtsp://admin:superpassword@10.0.0.1:554/live"
    clean_rtsp = redactor.redact(raw_rtsp)
    assert "rtsp://admin:***@10.0.0.1:554/live" in clean_rtsp
    assert "superpassword" not in clean_rtsp

    raw_json = '{"username": "admin", "password": "supersecretpassword"}'
    clean_json = redactor.redact(raw_json)
    assert '"password": "***"' in clean_json
    assert "supersecretpassword" not in clean_json


# ==========================================
# 10. STREAM & EVIDENCE PROTECTED ROUTES
# ==========================================

def test_stream_returns_no_signal_placeholder(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    cam = Camera(camera_id="cam_stream_demo", name="Stream Cam")
    clean_state.save_camera(cam)

    with client.stream("GET", f"/api/stream/cam_stream_demo?token={token}") as res:
        assert res.status_code == 200
        assert "multipart/x-mixed-replace" in res.headers["content-type"]
        first_chunk = next(res.iter_bytes())
        assert b"--frame" in first_chunk


def test_stream_missing_or_bad_token_401(client, clean_state):
    cam = Camera(camera_id="cam_stream_demo2", name="Stream Cam")
    clean_state.save_camera(cam)

    res1 = client.get("/api/stream/cam_stream_demo2")
    assert res1.status_code == 422

    res2 = client.get("/api/stream/cam_stream_demo2?token=badtoken")
    assert res2.status_code == 401


def test_evidence_access_and_path_traversal_blocked(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    evidence_dir = settings.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)
    dummy_img = evidence_dir / "crop1.jpg"
    dummy_img.write_bytes(b"\xff\xd8\xff\xe0" + b"dummy jpeg data")

    res = client.get(f"/evidence/crop1.jpg?token={token}")
    assert res.status_code == 200
    assert res.content.startswith(b"\xff\xd8")

    res_hack = client.get(f"/evidence/../../secret.txt?token={token}")
    assert res_hack.status_code in (400, 404)


# ==========================================
# 11. WEBSOCKET ALERTS ENDPOINT
# ==========================================

def test_websocket_rejects_bad_token(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/alerts?token=invalid_token") as ws:
            pass


def test_websocket_accepts_good_token(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)

    with client.websocket_connect(f"/ws/alerts?token={token}") as ws:
        # Connected successfully
        assert ws is not None


def test_websocket_receives_fake_engine_events_before_run_finishes(client, clean_state):
    viewer = clean_state.get_user_by_username("viewer")
    token = _token_for(viewer)
    camera_id = "cam_live_alert"
    clean_state.save_camera(Camera(camera_id=camera_id, name="Live Alert Camera"))
    event_queue = queue.Queue()

    class FakeProcess:
        exitcode = 0

        def __init__(self):
            self.finished = threading.Event()

        def is_alive(self):
            return not self.finished.is_set()

        def join(self, timeout=None):
            self.finished.wait(timeout)

    process = FakeProcess()
    emitted_at = {}
    run_finished_at = []

    def fake_engine():
        for frame_idx in range(30):
            if frame_idx not in (10, 20):
                continue
            emitted_at[frame_idx] = time.monotonic()
            event_queue.put({
                "type": "event_candidate",
                "data": {
                    "event_id": f"ev_frame_{frame_idx}",
                    "camera_id": camera_id,
                    "track_id": 1,
                    "vehicle_type": "motorcycle",
                    "violation_type": "helmet",
                    "decision": "VIOLATION",
                    "ai_result": "no_helmet",
                    "confidence": 0.9,
                    "reason": "NO_HELMET",
                    "frame_idx": frame_idx,
                },
            })
            if frame_idx == 10:
                time.sleep(0.5)
        time.sleep(0.5)
        run_finished_at.append(time.monotonic())
        event_queue.put({"type": "finished", "camera_id": camera_id})
        process.finished.set()

    with client:
        with client.websocket_connect(f"/ws/alerts?token={token}") as websocket:
            loop = client.portal.call(asyncio.get_running_loop)
            worker_handle = WorkerHandle(
                camera_id,
                process,
                queue.Queue(),
                event_queue,
                threading.Event(),
            )
            listener = threading.Thread(
                target=engine_manager._event_listener,
                args=(worker_handle, clean_state, loop),
            )
            engine = threading.Thread(target=fake_engine)
            listener.start()
            engine.start()

            alerts = []
            finished_received_at = None
            while finished_received_at is None:
                message = websocket.receive_json()
                received_at = time.monotonic()
                if message.get("type") == "violation":
                    alerts.append((message["event"]["event_id"], received_at))
                elif message.get("type") == "event_candidate":
                    alerts.append((message["event"]["event_id"], received_at))
                elif message.get("type") == "finished":
                    finished_received_at = received_at

            engine.join(timeout=5)
            listener.join(timeout=5)

    assert not engine.is_alive()
    assert not listener.is_alive()
    assert [alert[0] for alert in alerts] == ["ev_frame_10", "ev_frame_20"]
    assert alerts[0][1] < run_finished_at[0]
    assert run_finished_at[0] <= finished_received_at
    assert set(emitted_at) == {10, 20}


# ==========================================
# 12. ENGINE MANAGER START, STOP & CONFLICTS
# ==========================================

def test_engine_manager_second_start_returns_409(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    cam1 = Camera(camera_id="cam_run_1", name="Cam 1", source_path="dummy.mp4")
    cam2 = Camera(camera_id="cam_run_2", name="Cam 2", source_path="dummy.mp4")
    clean_state.save_camera(cam1)
    clean_state.save_camera(cam2)

    # Mock active worker
    class FakeProcess:
        def is_alive(self):
            return True
        def terminate(self):
            pass
        def join(self, timeout=None):
            pass

    engine_manager.active_worker = type("MockWorker", (), {
        "camera_id": "cam_run_1",
        "process": FakeProcess(),
        "frame_queue": None,
        "event_queue": None,
        "stop_event": None,
    })()

    try:
        res = client.post("/api/cameras/cam_run_2/start", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 409
        assert "Only 1 AI worker may run at a time" in res.json()["message"]
    finally:
        engine_manager.active_worker = None


def test_camera_start_and_stop_lifecycle(client, clean_state, tmp_path, monkeypatch):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    # Synthetic video
    vid = tmp_path / "life.mp4"
    vid.write_bytes(b"\x00" * 100)

    cam = Camera(camera_id="cam_lifecycle", name="Lifecycle Cam", source_path=str(vid))
    clean_state.save_camera(cam)

    # Start camera: mock the process so no real worker spawns
    class FakeProc:
        def __init__(self):
            self.alive = True
            self.exitcode = 0
        def is_alive(self):
            return self.alive
        def start(self):
            pass
        def terminate(self):
            self.alive = False
        def join(self, timeout=None):
            self.alive = False

    import queue as pyqueue
    class FakeCtx:
        def Queue(self, *a, **kw):
            return pyqueue.Queue()
        def Event(self):
            return type("Evt", (), {"set": lambda self: None, "is_set": lambda self: False})()
        def Process(self, **kwargs):
            return FakeProc()

    monkeypatch.setattr(mp, "get_context", lambda *a: FakeCtx())

    start_res = client.post("/api/cameras/cam_lifecycle/start", headers={"Authorization": f"Bearer {token}"})
    assert start_res.status_code == 200
    assert start_res.json()["status"] == "processing"

    cam_in_db = clean_state.get_camera("cam_lifecycle")
    assert cam_in_db.status == "processing"

    stop_res = client.post("/api/cameras/cam_lifecycle/stop", headers={"Authorization": f"Bearer {token}"})
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "offline"

    cam_in_db = clean_state.get_camera("cam_lifecycle")
    assert cam_in_db.status == "offline"


def test_engine_manager_crashing_worker_sets_status_error(clean_state):
    cam = Camera(camera_id="cam_crash", name="Crash Cam", status="processing")
    clean_state.save_camera(cam)

    class FakeQueue:
        def __init__(self):
            self.messages = [{"type": "error", "error": "CUDA out of memory"}]
        def get(self, timeout=None):
            if self.messages:
                return self.messages.pop(0)
            raise Exception("empty")
        def empty(self):
            return len(self.messages) == 0

    class FakeProc:
        def __init__(self):
            self.exitcode = 1
        def is_alive(self):
            return False
        def join(self, timeout=None):
            pass

    fake_worker = type("MockWorker", (), {
        "camera_id": "cam_crash",
        "process": FakeProc(),
        "event_queue": FakeQueue(),
        "stop_event": type("Evt", (), {"is_set": lambda self: False})(),
    })()

    loop = asyncio.new_event_loop()
    engine_manager._event_listener(fake_worker, clean_state, loop)
    loop.run_until_complete(asyncio.sleep(0.05))
    loop.close()

    updated = clean_state.get_camera("cam_crash")
    assert updated.status == "error"


# ==========================================
# 13. SETTINGS & HEALTH
# ==========================================

def test_system_settings_get_and_put(client, clean_state):
    admin = clean_state.get_user_by_username("admin")
    token = _token_for(admin)

    res = client.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "helmet_min_confidence" in data

    update_res = client.put(
        "/api/settings",
        json={"helmet_min_confidence": 0.55, "max_workers": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["helmet_min_confidence"] == 0.55


def test_public_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
