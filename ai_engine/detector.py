"""Stage 6 model wrapper for motorcycle tracking and helmet observations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from ultralytics import YOLO

from ai_engine.association import (
    Box,
    HeadDetection,
    HelmetResult,
    driver_helmet_result,
    pick_driver,
    riders_for_motorcycle,
)
from ai_engine.config import EngineConfig
from ai_engine.tracking import Track, results_to_tracks


@dataclass(frozen=True)
class HelmetAnalysis:
    """One motorcycle's helmet result plus geometry for visual inspection."""

    track: Track
    result: HelmetResult
    driver: Box | None
    riders: tuple[Box, ...]
    persons: tuple[Box, ...]
    heads: tuple[HeadDetection, ...]
    crop_box: Box


def _box(values: Any) -> Box:
    return Box(*(float(value) for value in values))


def _crop_box_to_frame(box: Box, left: int, top: int, scale: float = 1.0) -> Box:
    return Box(box.x1 / scale + left, box.y1 / scale + top,
               box.x2 / scale + left, box.y2 / scale + top)


class HelmetDetector:
    """Load existing checkpoints and return tracked motorcycles and rider results."""

    def __init__(self, config: EngineConfig, vehicle_model=None, helmet_model=None) -> None:
        self.config = config
        self.vehicle_model = vehicle_model if vehicle_model is not None else YOLO(str(config.paths.vehicle_model))
        self.helmet_model = helmet_model if helmet_model is not None else YOLO(str(config.paths.helmet_model))
        self._person_frame = None
        self._person_cache: list[Box] = []
        vehicle_names = self.vehicle_model.names
        if str(vehicle_names[0]).lower() != "person" or str(vehicle_names[3]).lower() != "motorcycle":
            raise ValueError("Vehicle weights must use COCO class 0=person and 3=motorcycle")
        names = self.helmet_model.names
        normalized = {str(name).lower().replace(" ", "_") for name in names.values()}
        if not {"helmet", "no_helmet"}.issubset(normalized):
            raise ValueError(f"Helmet model must contain helmet and no_helmet classes; got {names}")

    def track_vehicles(self, frame) -> list[Track]:
        """Track motorcycles only; IDs come from BoT-SORT and are never fabricated."""
        result = self.vehicle_model.track(
            frame,
            persist=True,
            tracker=str(self.config.paths.tracker),
            classes=[3],
            conf=self.config.camera.vehicle_conf,
            imgsz=self.config.camera.imgsz,
            verbose=False,
        )[0]
        self._person_frame = None
        self._person_cache = []
        return [track for track in results_to_tracks(result) if track.cls == 3]

    def helmet_observation(self, frame, track: Track) -> HelmetAnalysis:
        """Inspect a tracked motorcycle crop, associating only the driver's head."""
        frame_h, frame_w = frame.shape[:2]
        moto = track.box
        if moto.width < self.config.camera.min_motorcycle_width:
            result = HelmetResult("unclear", 0.0, "TOO_SMALL")
            return HelmetAnalysis(track, result, None, (), (), (), Box(0, 0, 0, 0))
        left = max(0, int(moto.x1))
        top = max(0, int(moto.y1 - .60 * moto.height))
        right = min(frame_w, int(moto.x2))
        bottom = min(frame_h, int(moto.y2))
        crop_box = Box(left, top, right, bottom)
        if right <= left or bottom <= top:
            result = HelmetResult("unclear", 0.0, "NO_RIDER")
            return HelmetAnalysis(track, result, None, (), (), (), crop_box)
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            result = HelmetResult("unclear", 0.0, "NO_RIDER")
            return HelmetAnalysis(track, result, None, (), (), (), crop_box)

        # Find people in the whole image and again in an enlarged rider crop.
        # The second pass helps when riders occupy only a small number of pixels.
        if self._person_frame is not frame:
            person_result = self.vehicle_model.predict(
                frame, classes=[0], conf=self.config.camera.vehicle_conf,
                imgsz=self.config.camera.imgsz, verbose=False,
            )[0]
            self._person_cache = []
            if person_result.boxes is not None:
                self._person_cache.extend(_box(item.xyxy[0].tolist()) for item in person_result.boxes)
            self._person_frame = frame
        persons = list(self._person_cache)

        up_scale = max(1.0, 640.0 / max(crop.shape[0], crop.shape[1]))
        if up_scale > 1.0:
            enlarged = cv2.resize(crop, None, fx=up_scale, fy=up_scale,
                                  interpolation=cv2.INTER_CUBIC)
            local_result = self.vehicle_model.predict(
                enlarged, classes=[0], conf=self.config.camera.vehicle_conf,
                imgsz=self.config.camera.imgsz, verbose=False,
            )[0]
            if local_result.boxes is not None:
                for item in local_result.boxes:
                    candidate = _crop_box_to_frame(_box(item.xyxy[0].tolist()), left, top, up_scale)
                    # Suppress duplicate full-frame/crop person detections.
                    if not any(_iou(candidate, old) > .5 for old in persons):
                        persons.append(candidate)

        helmet_result = self.helmet_model.predict(
            crop, conf=self.config.camera.helmet_conf,
            imgsz=self.config.camera.imgsz, verbose=False,
        )[0]
        heads: list[HeadDetection] = []
        if helmet_result.boxes is not None:
            for item in helmet_result.boxes:
                class_id = int(item.cls.item())
                label = str(self.helmet_model.names[class_id]).lower().replace(" ", "_")
                if label in ("helmet", "no_helmet"):
                    heads.append(HeadDetection(
                        _crop_box_to_frame(_box(item.xyxy[0].tolist()), left, top),
                        label, float(item.conf.item()),
                    ))

        decision = driver_helmet_result(moto, persons, heads, self.config.camera.camera_view)
        # Keep driver geometry for overlays; this uses exactly the same rider rule.
        riders = riders_for_motorcycle(moto, persons)
        driver = pick_driver(riders, self.config.camera.camera_view)
        return HelmetAnalysis(track, decision, driver, tuple(riders), tuple(persons),
                              tuple(heads), crop_box)


def _iou(first: Box, second: Box) -> float:
    width = max(0.0, min(first.x2, second.x2) - max(first.x1, second.x1))
    height = max(0.0, min(first.y2, second.y2) - max(first.y1, second.y1))
    intersection = width * height
    union = first.area + second.area - intersection
    return intersection / union if union > 0 else 0.0
