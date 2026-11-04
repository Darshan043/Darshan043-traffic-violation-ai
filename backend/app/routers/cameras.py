"""Camera management, video uploads, zone configuration, and snapshot router."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import uuid
import asyncio
import cv2
from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status

from backend.app.core.config import settings
from backend.app.db.repository import Repository
from backend.app.deps import get_current_user, get_repository, require_role
from backend.app.models.camera import (
    Camera,
    CameraCreate,
    CameraResponse,
    CameraUpdate,
    ZoneUpdate,
)
from backend.app.models.user import User
from backend.app.services.engine_manager import engine_manager

router = APIRouter(prefix="/api/cameras", tags=["cameras"])
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


@router.get("", response_model=list[CameraResponse])
def list_cameras(
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> list[CameraResponse]:
    cameras = repo.list_cameras()
    return [CameraResponse.from_camera(c) for c in cameras]


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> CameraResponse:
    existing = repo.get_camera(payload.camera_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Camera with ID '{payload.camera_id}' already exists",
        )

    now = datetime.now(timezone.utc).isoformat()
    camera = Camera(
        camera_id=payload.camera_id,
        name=payload.name,
        location=payload.location,
        source_type=payload.source_type,
        source_path=payload.source_path,
        enabled=payload.enabled,
        status="offline",
        driver_side=payload.driver_side,
        camera_view=payload.camera_view,
        motorcycle_view=payload.motorcycle_view,
        checks=payload.checks,
        zone=payload.zone,
        created_at=now,
        updated_at=now,
    )
    saved = repo.save_camera(camera)
    return CameraResponse.from_camera(saved)


@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(
    camera_id: str,
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> CameraResponse:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return CameraResponse.from_camera(cam)


@router.put("/{camera_id}", response_model=CameraResponse)
def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    _: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> CameraResponse:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated = repo.update_camera(camera_id, updates)
    assert updated is not None
    return CameraResponse.from_camera(updated)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: str,
    _: User = Depends(require_role("admin")),
    repo: Repository = Depends(get_repository),
) -> None:
    deleted = repo.delete_camera(camera_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")


@router.post("/{camera_id}/video", response_model=CameraResponse)
async def upload_camera_video(
    camera_id: str,
    file: UploadFile = File(...),
    _: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> CameraResponse:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    filename = file.filename or "video.mp4"
    # Reject path traversal tricks
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename: path traversal characters rejected")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: {sorted(ALLOWED_VIDEO_EXTENSIONS)}",
        )

    # Check size limit while reading
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(filename).stem)
    safe_filename = f"{camera_id}_{uuid.uuid4().hex[:8]}_{safe_stem}{ext}"
    dest_path = settings.uploads_dir / safe_filename

    total_bytes = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                f.close()
                if dest_path.is_file():
                    dest_path.unlink()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File exceeds maximum upload limit of {settings.MAX_UPLOAD_MB} MB",
                )
            f.write(chunk)

    updates = {
        "source_type": "file",
        "source_path": str(dest_path),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    updated = repo.update_camera(camera_id, updates)
    assert updated is not None
    return CameraResponse.from_camera(updated)


@router.put("/{camera_id}/zone", response_model=CameraResponse)
def update_camera_zone(
    camera_id: str,
    payload: ZoneUpdate,
    _: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> CameraResponse:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    updates = {
        "zone": payload.points,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    updated = repo.update_camera(camera_id, updates)
    assert updated is not None
    return CameraResponse.from_camera(updated)


@router.get("/{camera_id}/status")
def get_camera_status(
    camera_id: str,
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, str]:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return {"camera_id": camera_id, "status": cam.status}


@router.get("/{camera_id}/snapshot")
def get_camera_snapshot(
    camera_id: str,
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> Response:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    if not cam.source_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Camera has no source path configured",
        )

    cap = cv2.VideoCapture(cam.source_path)
    if not cap.isOpened():
        cap.release()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not open video source to capture snapshot",
        )

    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read frame from camera source",
        )

    ret, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    if not ret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to encode snapshot JPEG")

    return Response(content=buffer.tobytes(), media_type="image/jpeg")


@router.post("/{camera_id}/start")
async def start_camera_processing(
    camera_id: str,
    request: Request,
    _: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, str]:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    loop = asyncio.get_running_loop()
    try:
        engine_manager.start_camera(camera_id, cam, repo, loop)
    except RuntimeError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))

    return {"camera_id": camera_id, "status": "processing"}


@router.post("/{camera_id}/stop")
async def stop_camera_processing(
    camera_id: str,
    _: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, str]:
    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    loop = asyncio.get_running_loop()
    engine_manager.stop_camera(camera_id, repo, loop)
    return {"camera_id": camera_id, "status": "offline"}
