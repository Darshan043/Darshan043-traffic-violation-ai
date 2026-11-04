"""Vehicle event schema for compliance tracking."""
from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field


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
