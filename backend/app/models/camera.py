"""Camera schemas and RTSP credential protection."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator


CameraSourceType = Literal["file", "rtsp"]
CameraStatus = Literal["offline", "online", "processing", "error"]
DriverSide = Literal["left", "right"]
CameraView = Literal["front", "side_or_rear", "unknown"]
MotorcycleView = Literal["approaching", "receding"]


def sanitize_source_path(path: str) -> str:
    """Mask RTSP passwords so they are never returned via the API or logged."""
    if not path:
        return path
    return re.sub(r"(rtsp://[^:]+:)[^@]+(@)", r"\1***\2", path, flags=re.IGNORECASE)


class Camera(BaseModel):
    camera_id: str
    name: str
    location: str = ""
    source_type: CameraSourceType = "file"
    source_path: str = ""
    enabled: bool = True
    status: CameraStatus = "offline"
    driver_side: DriverSide = "right"
    camera_view: CameraView = "unknown"
    motorcycle_view: MotorcycleView = "approaching"
    checks: list[str] = Field(default_factory=lambda: ["helmet", "seatbelt"])
    zone: list[float] = Field(default_factory=lambda: [0.0, 0.9, 1.0, 0.9])
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CameraCreate(BaseModel):
    camera_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    location: str = ""
    source_type: CameraSourceType = "file"
    source_path: str = ""
    enabled: bool = True
    driver_side: DriverSide = "right"
    camera_view: CameraView = "unknown"
    motorcycle_view: MotorcycleView = "approaching"
    checks: list[str] = Field(default_factory=lambda: ["helmet", "seatbelt"])
    zone: list[float] = Field(default_factory=lambda: [0.0, 0.9, 1.0, 0.9])


class CameraUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    source_type: CameraSourceType | None = None
    source_path: str | None = None
    enabled: bool | None = None
    status: CameraStatus | None = None
    driver_side: DriverSide | None = None
    camera_view: CameraView | None = None
    motorcycle_view: MotorcycleView | None = None
    checks: list[str] | None = None
    zone: list[float] | None = None


class CameraResponse(BaseModel):
    camera_id: str
    name: str
    location: str
    source_type: CameraSourceType
    source_path: str
    enabled: bool
    status: CameraStatus
    driver_side: DriverSide
    camera_view: CameraView
    motorcycle_view: MotorcycleView
    checks: list[str]
    zone: list[float]
    created_at: str
    updated_at: str

    @classmethod
    def from_camera(cls, camera: Camera) -> "CameraResponse":
        data = camera.model_dump()
        data["source_path"] = sanitize_source_path(data["source_path"])
        return cls(**data)


class ZoneUpdate(BaseModel):
    points: list[float]

    @field_validator("points")
    @classmethod
    def validate_zone_points(cls, pts: list[float]) -> list[float]:
        if len(pts) < 4:
            raise ValueError("Zone requires at least 2 points (4 numbers [x1, y1, x2, y2]) for a line")
        if len(pts) % 2 != 0:
            raise ValueError("Zone coordinates must be even number of x,y pairs")
        for val in pts:
            if not (0.0 <= float(val) <= 1.0):
                raise ValueError("Zone coordinates must be normalised numbers between 0.0 and 1.0")
        return [float(v) for v in pts]
