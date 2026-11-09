"""Statistics and metrics models."""
from __future__ import annotations

from pydantic import BaseModel


class StatsSummary(BaseModel):
    total_vehicles: int
    compliant_vehicles: int
    violations: int
    needs_review: int
    compliance_percentage: float  # compliant / (compliant + violations) * 100, excluding NEEDS_REVIEW
    reviewed_count: int
    unreviewed_count: int
    helmet_compliance_percentage: float = 100.0
    seatbelt_compliance_percentage: float = 100.0
    review_count: int = 0


class DailyStat(BaseModel):
    date: str
    total_vehicles: int
    compliant_vehicles: int
    violations: int
    needs_review: int
    compliance_percentage: float


class CameraStat(BaseModel):
    camera_id: str
    camera_name: str
    total_vehicles: int
    compliant_vehicles: int
    violations: int
    needs_review: int
    compliance_percentage: float
