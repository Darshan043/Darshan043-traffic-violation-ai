"""Geometry-only rider, driver, and helmet association helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def centre(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class HeadDetection:
    box: Box
    label: Literal["helmet", "no_helmet"]
    confidence: float


@dataclass(frozen=True)
class HelmetResult:
    label: Literal["helmet", "no_helmet", "unclear"]
    confidence: float
    reason: Literal["OK", "NO_RIDER", "DRIVER_UNCLEAR", "NO_HEAD", "TOO_SMALL"]


def riders_for_motorcycle(moto_box: Box, person_boxes: Iterable[Box]) -> list[Box]:
    expanded = Box(moto_box.x1, moto_box.y1 - .60 * moto_box.height, moto_box.x2, moto_box.y2)
    riders = []
    for person in person_boxes:
        if person.area <= 0:
            continue
        ix = max(0.0, min(person.x2, expanded.x2) - max(person.x1, expanded.x1))
        iy = max(0.0, min(person.y2, expanded.y2) - max(person.y1, expanded.y1))
        if ix * iy / person.area >= .50:
            riders.append(person)
    return riders


def pick_driver(riders: Iterable[Box], camera_view: Literal["approaching", "receding"]) -> Box | None:
    riders = list(riders)
    if len(riders) == 1:
        return riders[0]
    if not riders:
        return None
    if camera_view not in ("approaching", "receding"):
        raise ValueError("camera_view must be 'approaching' or 'receding'")
    ordered = sorted(riders, key=lambda b: b.y2, reverse=(camera_view == "approaching"))
    if abs(ordered[0].y2 - ordered[1].y2) < .08 * max(ordered[0].height, 1.0):
        return None
    return ordered[0]


def link_head_to_person(head_boxes: Iterable[HeadDetection | Box], person_box: Box) -> list[HeadDetection | Box]:
    linked = []
    cutoff = person_box.y1 + .35 * person_box.height
    for head in head_boxes:
        box = head.box if isinstance(head, HeadDetection) else head
        cx, cy = box.centre
        if person_box.x1 <= cx <= person_box.x2 and person_box.y1 <= cy <= cutoff:
            linked.append(head)
    return linked


def driver_helmet_result(
    moto_box: Box,
    persons: Iterable[Box],
    heads: Iterable[HeadDetection],
    camera_view: Literal["approaching", "receding"],
) -> HelmetResult:
    riders = riders_for_motorcycle(moto_box, persons)
    if not riders:
        return HelmetResult("unclear", 0.0, "NO_RIDER")
    driver = pick_driver(riders, camera_view)
    if driver is None:
        return HelmetResult("unclear", 0.0, "DRIVER_UNCLEAR")
    driver_heads = [h for h in link_head_to_person(heads, driver) if isinstance(h, HeadDetection)]
    if not driver_heads:
        return HelmetResult("unclear", 0.0, "NO_HEAD")
    # Use the most confident head result assigned to the driver only.
    selected = max(driver_heads, key=lambda h: h.confidence)
    return HelmetResult(selected.label, selected.confidence, "OK")
