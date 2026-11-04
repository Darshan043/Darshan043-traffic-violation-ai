"""Write reviewable images and metadata for every emitted violation event."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from uuid import uuid4

import cv2

from ai_engine.association import Box
from ai_engine.zone import Zone


def _clip_box(box: Box, width: int, height: int) -> tuple[int, int, int, int] | None:
    left = max(0, min(width, int(box.x1)))
    top = max(0, min(height, int(box.y1)))
    right = max(0, min(width, int(box.x2)))
    bottom = max(0, min(height, int(box.y2)))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _box_values(box: Box | None) -> list[float] | None:
    if box is None:
        return None
    return [float(box.x1), float(box.y1), float(box.x2), float(box.y2)]


class EvidenceWriter:
    """Save one uniquely named evidence directory per event under a dated path."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def save_event(
        self,
        event: dict,
        frame,
        vehicle_box: Box,
        zone: Zone,
        *,
        analysis=None,
    ) -> dict[str, str]:
        height, width = frame.shape[:2]
        camera = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(event.get("camera_id", "camera")))
        event_key = (f"{camera}_f{int(event['frame_idx']):06d}_"
                     f"t{int(event['track_id'])}_{uuid4().hex[:8]}")
        output_dir = self.root / datetime.now().strftime("%Y-%m-%d") / camera / event_key
        output_dir.mkdir(parents=True, exist_ok=False)

        is_seatbelt = event.get("violation_type") == "seatbelt"
        driver_box = analysis.driver if analysis and hasattr(analysis, "driver") else None
        riders = list(analysis.riders) if analysis and hasattr(analysis, "riders") else []
        heads = list(analysis.heads) if analysis and hasattr(analysis, "heads") else []
        motorcycle = analysis.track.box if analysis and hasattr(analysis, "track") else vehicle_box
        driver_crop_box = (
            analysis.driver_crop
            if is_seatbelt and analysis and analysis.driver_crop is not None
            else driver_box or (riders[0] if riders else None)
        )
        if driver_crop_box is None:
            driver_crop_box = (
                analysis.crop_box
                if analysis and hasattr(analysis, "crop_box")
                else Box(vehicle_box.x1, vehicle_box.y1 - .60 * vehicle_box.height,
                         vehicle_box.x2, vehicle_box.y2)
            )

        annotated = frame.copy()
        points = [(int(x), int(y)) for x, y in zone.vertices]
        if zone.is_line:
            cv2.line(annotated, points[0], points[1], (255, 255, 0), 3)
        else:
            import numpy as np
            cv2.polylines(annotated, [np.asarray(points, dtype="int32")], True,
                          (255, 255, 0), 3)

        decision = str(event.get("decision", "NEEDS_REVIEW"))
        color = {"VIOLATION": (0, 0, 255), "COMPLIANCE": (0, 200, 0),
                 "NEEDS_REVIEW": (0, 220, 255)}.get(decision, (0, 220, 255))
        vehicle_label = "car" if is_seatbelt else "motorcycle"
        self._draw_box(annotated, motorcycle, (255, 150, 20), vehicle_label)
        if analysis and not is_seatbelt:
            for rider in riders:
                self._draw_box(annotated, rider, (0, 200, 0), "rider")
            if driver_box:
                self._draw_box(annotated, driver_box, color, "driver")
            for head in heads:
                self._draw_box(annotated, head.box, color, head.label)
        if is_seatbelt and analysis:
            crop = analysis.driver_crop
            if crop is not None:
                self._draw_box(annotated, crop, color, "driver-side crop")
                for detection in analysis.detections:
                    local = detection.box
                    self._draw_box(
                        annotated,
                        Box(local.x1 + crop.x1, local.y1 + crop.y1,
                            local.x2 + crop.x1, local.y2 + crop.y1),
                        color,
                        f"{detection.label} {detection.confidence:.2f}",
                    )
        cv2.putText(annotated,
                    f"{decision} | {event.get('reason', 'UNKNOWN')} | track {event['track_id']}",
                    (12, 28), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)

        paths = {
            "full_frame": output_dir / "full_frame.jpg",
            "vehicle_crop": output_dir / "vehicle_crop.jpg",
            "driver_rider_crop": output_dir / "driver_rider_crop.jpg",
            "metadata": output_dir / "metadata.json",
        }
        self._write_image(paths["full_frame"], annotated)
        self._write_crop(paths["vehicle_crop"], frame, motorcycle)
        self._write_crop(paths["driver_rider_crop"], frame, driver_crop_box)

        metadata = {
            "event": event,
            "decision": decision,
            "reason": event.get("reason"),
            "zone": {"type": "line" if zone.is_line else "polygon",
                     "vertices": [[float(x), float(y)] for x, y in zone.vertices]},
            "boxes": {
                "vehicle": _box_values(motorcycle),
                "riders": [_box_values(box) for box in riders],
                "driver": _box_values(driver_box),
                "driver_side_crop": (
                    _box_values(analysis.driver_crop)
                    if is_seatbelt and analysis
                    else None
                ),
                "heads": ([{"box": _box_values(head.box), "label": head.label,
                            "confidence": float(head.confidence)} for head in heads]),
                "seatbelt_detections": (
                    [
                        {
                            "box": _box_values(Box(
                                detection.box.x1 + analysis.driver_crop.x1,
                                detection.box.y1 + analysis.driver_crop.y1,
                                detection.box.x2 + analysis.driver_crop.x1,
                                detection.box.y2 + analysis.driver_crop.y1,
                            )),
                            "label": detection.label,
                            "confidence": float(detection.confidence),
                        }
                        for detection in analysis.detections
                    ]
                    if is_seatbelt and analysis
                    else []
                ),
                "driver_rider_crop_source": (
                    "driver_side_crop" if is_seatbelt and analysis and analysis.driver_crop
                    else "driver" if driver_box else "rider" if riders else "expanded_motorcycle_area"
                ),
            },
            "image_paths": {key: path.name for key, path in paths.items() if key != "metadata"},
        }
        paths["metadata"].write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        result = {key: str(path) for key, path in paths.items()}
        result["directory"] = str(output_dir)
        return result

    @staticmethod
    def _draw_box(image, box: Box, color: tuple[int, int, int], label: str) -> None:
        clipped = _clip_box(box, image.shape[1], image.shape[0])
        if clipped is None:
            return
        left, top, right, bottom = clipped
        cv2.rectangle(image, (left, top), (right, bottom), color, 2)
        cv2.putText(image, label, (left, max(14, top - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, .48, color, 1)

    @classmethod
    def _write_crop(cls, path: Path, frame, box: Box) -> None:
        clipped = _clip_box(box, frame.shape[1], frame.shape[0])
        if clipped is None:
            raise ValueError(f"Cannot save an empty evidence crop for box {box}")
        left, top, right, bottom = clipped
        cls._write_image(path, frame[top:bottom, left:right])

    @staticmethod
    def _write_image(path: Path, image) -> None:
        if image is None or image.size == 0 or not cv2.imwrite(str(path), image):
            raise OSError(f"Could not write evidence image: {path}")
