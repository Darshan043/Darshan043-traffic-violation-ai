"""Vehicle event schema for compliance tracking."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, computed_field


VehicleEventResult = Literal[
    "HELMET",
    "NO_HELMET",
    "SEATBELT",
    "NO_SEATBELT",
    "NEEDS_REVIEW",
    "NOT_CHECKED",
]


def result_from_pipeline(decision: str, ai_result: str) -> VehicleEventResult:
    """Translate the pipeline decision and label into the persisted result code."""
    if decision == "NEEDS_REVIEW":
        return "NEEDS_REVIEW"
    if decision == "COMPLIANCE":
        return {
            "helmet": "HELMET",
            "seatbelt": "SEATBELT",
        }.get(ai_result, "NOT_CHECKED")
    if decision == "VIOLATION":
        return {
            "no_helmet": "NO_HELMET",
            "no_seatbelt": "NO_SEATBELT",
        }.get(ai_result, "NOT_CHECKED")
    return "NOT_CHECKED"


class VehicleEvent(BaseModel):
    event_id: str
    camera_id: str
    track_id: int
    vehicle_type: str
    violation_type: str
    decision: str  # COMPLIANCE | VIOLATION | NEEDS_REVIEW
    ai_result: str  # helmet | no_helmet | seatbelt | no_seatbelt | unclear
    confidence: float = 0.0
    reason: str = ""
    timestamp_sec: float = 0.0
    frame_idx: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @computed_field
    @property
    def result(self) -> VehicleEventResult:
        return result_from_pipeline(self.decision, self.ai_result)
