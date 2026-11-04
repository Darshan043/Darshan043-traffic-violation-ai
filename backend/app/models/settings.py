"""System settings models."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class SystemSettings(BaseModel):
    helmet_min_confidence: float = 0.40
    seatbelt_min_confidence: float = 0.40
    seatbelt_min_car_height: float = 120.0
    duplicate_window_sec: float = 2.0
    duplicate_iou_threshold: float = 0.5
    max_workers: int = 1
    extra: dict[str, Any] = Field(default_factory=dict)
