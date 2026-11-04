"""Violation record and review models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

ReviewStatus = Literal["UNREVIEWED", "REVIEWED"]
FinalDecision = Literal["VIOLATION", "COMPLIANCE", "DISMISSED"]


class EvidencePaths(BaseModel):
    composite: str | None = None
    full_frame: str | None = None
    vehicle_crop: str | None = None
    driver_rider_crop: str | None = None
    metadata: str | None = None


class Violation(BaseModel):
    event_id: str
    camera_id: str
    track_id: int
    violation_type: str  # helmet | seatbelt
    ai_result: str       # no_helmet | no_seatbelt | unclear (UNCHANGED on human review)
    detection_confidence: float = 0.0
    reason_code: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus = "UNREVIEWED"
    final_decision: FinalDecision | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ViolationReviewRequest(BaseModel):
    final_decision: FinalDecision
    review_note: str | None = None


class ViolationResponse(BaseModel):
    event_id: str
    camera_id: str
    track_id: int
    violation_type: str
    ai_result: str
    detection_confidence: float
    reason_code: str
    evidence: dict[str, Any]
    review_status: ReviewStatus
    final_decision: FinalDecision | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    created_at: str
