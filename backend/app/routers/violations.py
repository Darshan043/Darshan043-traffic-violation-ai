"""Violation records, review actions, and CSV export."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.app.db.repository import Repository
from backend.app.deps import get_repository, require_role
from backend.app.models.user import User
from backend.app.models.violation import (
    Violation,
    ViolationResponse,
    ViolationReviewRequest,
)

router = APIRouter(prefix="/api/violations", tags=["violations"])


@router.get("")
def list_violations(
    type: str | None = Query(None, description="Violation type: helmet or seatbelt"),
    result: str | None = Query(None, description="AI result or decision filter"),
    camera: str | None = Query(None, description="Camera ID"),
    date_from: str | None = Query(None, description="ISO datetime start"),
    date_to: str | None = Query(None, description="ISO datetime end"),
    track_id: int | None = Query(None, description="Track ID"),
    review_status: str | None = Query(None, description="UNREVIEWED or REVIEWED"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> dict[str, Any]:
    items, total = repo.list_violations(
        violation_type=type,
        ai_result=result,
        camera_id=camera,
        date_from=date_from,
        date_to=date_to,
        track_id=track_id,
        review_status=review_status,
        page=page,
        limit=limit,
    )
    return {
        "items": [v.model_dump() for v in items],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.get("/export")
def export_violations_csv(
    type: str | None = None,
    result: str | None = None,
    camera: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    track_id: int | None = None,
    review_status: str | None = None,
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> StreamingResponse:
    items = repo.iter_violations(
        violation_type=type,
        ai_result=result,
        camera_id=camera,
        date_from=date_from,
        date_to=date_to,
        track_id=track_id,
        review_status=review_status,
    )

    def iter_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "event_id",
            "camera_id",
            "track_id",
            "violation_type",
            "ai_result",
            "detection_confidence",
            "reason_code",
            "review_status",
            "final_decision",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
        ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for v in items:
            writer.writerow([
                v.event_id,
                v.camera_id,
                v.track_id,
                v.violation_type,
                v.ai_result,
                f"{v.detection_confidence:.3f}",
                v.reason_code,
                v.review_status,
                v.final_decision or "",
                v.reviewed_by or "",
                v.reviewed_at or "",
                v.review_note or "",
                v.created_at,
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    return StreamingResponse(
        iter_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="violations.csv"'},
    )


@router.get("/{event_id}", response_model=ViolationResponse)
def get_violation(
    event_id: str,
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> ViolationResponse:
    violation = repo.get_violation(event_id)
    if violation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found")
    return ViolationResponse(**violation.model_dump())


@router.put("/{event_id}/review", response_model=ViolationResponse)
def review_violation(
    event_id: str,
    payload: ViolationReviewRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    repo: Repository = Depends(get_repository),
) -> ViolationResponse:
    violation = repo.get_violation(event_id)
    if violation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found")

    # Important: ai_result stays UNCHANGED
    updates = {
        "review_status": "REVIEWED",
        "final_decision": payload.final_decision,
        "reviewed_by": current_user.username,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "review_note": payload.review_note,
    }
    updated = repo.update_violation(event_id, updates)
    assert updated is not None
    return ViolationResponse(**updated.model_dump())
