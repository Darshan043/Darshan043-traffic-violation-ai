"""Pure geometry and decision helpers for driver-side seatbelt results."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Literal

from ai_engine.association import Box

SeatbeltLabel = Literal["seatbelt", "no_seatbelt", "unclear"]
SeatbeltReason = Literal["OK", "TOO_SMALL", "NO_DRIVER", "LOW_CONF"]


@dataclass(frozen=True)
class SeatbeltDetection:
    box: Box
    label: Literal["seatbelt", "no_seatbelt"]
    confidence: float


@dataclass(frozen=True)
class SeatbeltResult:
    label: SeatbeltLabel
    confidence: float
    reason: SeatbeltReason


def car_driver_crop(
    car_box: Box,
    driver_side: Literal["left", "right"],
    min_height: float = 120,
) -> Box | None:
    """Return the upper 55% and selected side-half of a car box."""
    if driver_side not in ("left", "right"):
        raise ValueError("driver_side must be 'left' or 'right'")
    if min_height < 0:
        raise ValueError("min_height must not be negative")
    if car_box.height < min_height or car_box.width <= 0:
        return None
    mid_x = (car_box.x1 + car_box.x2) / 2
    x1, x2 = (mid_x, car_box.x2) if driver_side == "right" else (car_box.x1, mid_x)
    return Box(x1, car_box.y1, x2, car_box.y1 + 0.55 * car_box.height)


def seatbelt_result(
    detections: Iterable[SeatbeltDetection],
    driver_crop: Box | None,
    *,
    driver_present: bool = True,
    min_confidence: float = 0.40,
) -> SeatbeltResult:
    """Classify only detections whose centers fall inside the driver-side crop."""
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    if driver_crop is None or driver_crop.height <= 0 or driver_crop.width <= 0:
        return SeatbeltResult("unclear", 0.0, "TOO_SMALL")
    if not driver_present:
        return SeatbeltResult("unclear", 0.0, "NO_DRIVER")

    candidates = []
    for detection in detections:
        if detection.label not in ("seatbelt", "no_seatbelt"):
            continue
        if not math.isfinite(detection.confidence) or not 0 <= detection.confidence <= 1:
            raise ValueError("detection confidence must be a finite value between 0 and 1")
        center_x, center_y = detection.box.centre
        if (
            driver_crop.x1 <= center_x <= driver_crop.x2
            and driver_crop.y1 <= center_y <= driver_crop.y2
        ):
            candidates.append(detection)
    if not candidates:
        return SeatbeltResult("unclear", 0.0, "LOW_CONF")

    best = max(candidates, key=lambda detection: detection.confidence)
    if best.confidence < min_confidence:
        return SeatbeltResult("unclear", best.confidence, "LOW_CONF")
    return SeatbeltResult(best.label, best.confidence, "OK")
