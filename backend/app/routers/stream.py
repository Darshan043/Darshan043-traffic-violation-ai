"""MJPEG video streaming and protected evidence file serving."""
from __future__ import annotations

import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse

from backend.app.core.config import settings
from backend.app.db.repository import Repository
from backend.app.deps import get_repository, get_user_from_token_str
from backend.app.services.engine_manager import engine_manager

router = APIRouter(tags=["stream"])


async def _mjpeg_generator(camera_id: str):
    while True:
        frame_bytes = engine_manager.get_latest_frame(camera_id)
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(frame_bytes)).encode("ascii") + b"\r\n\r\n" +
            frame_bytes + b"\r\n"
        )
        await asyncio.sleep(0.08)  # ~12 FPS stream rate without blocking


@router.get("/api/stream/{camera_id}")
async def get_stream(
    camera_id: str,
    token: str = Query(..., description="JWT authentication token"),
    repo: Repository = Depends(get_repository),
) -> StreamingResponse:
    user = get_user_from_token_str(token, repo)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing stream token",
        )

    cam = repo.get_camera(camera_id)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    return StreamingResponse(
        _mjpeg_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/evidence/{file_path:path}")
def get_evidence_file(
    file_path: str,
    token: str | None = Query(None),
    authorization: str | None = Header(None),
    repo: Repository = Depends(get_repository),
) -> FileResponse:
    # Check token from query param or header
    raw_token = token
    if not raw_token and authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization[7:].strip()

    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication token")

    user = get_user_from_token_str(raw_token, repo)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    # Guard against directory traversal
    base_dir = settings.evidence_dir.resolve()
    target_path = (base_dir / file_path).resolve()

    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path traversal forbidden")

    if not target_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence file not found")

    return FileResponse(str(target_path))
