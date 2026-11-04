"""Standalone Stage 6 and Stage 7 violation pipeline orchestration."""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import time
from typing import Any, Literal

import cv2

from ai_engine.config import EngineConfig, load_config
from ai_engine.helmet_pipeline import process_motorcycles
from ai_engine.seatbelt_pipeline import process_cars

PipelineMode = Literal["helmet", "seatbelt", "both"]


def _event_iou(first: list[float] | None, second: list[float] | None) -> float:
    if not first or not second:
        return 0.0
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_b = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


def suppress_duplicate_events(
    events: list[dict[str, Any]],
    *,
    time_window_sec: float = 2.0,
    iou_threshold: float = 0.5,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the more-observed event when same-view vehicle boxes overlap in time."""
    ranked = sorted(events, key=lambda e: (-int(e.get("observations", 0)), int(e.get("frame_idx", 0))))
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for event in ranked:
        match = next(
            (
                prior for prior in kept
                if str(prior.get("camera_id")) == str(event.get("camera_id"))
                and prior.get("vehicle_type") == event.get("vehicle_type")
                and abs(float(prior.get("timestamp_sec", 0)) -
                        float(event.get("timestamp_sec", 0))) <= time_window_sec
                and _event_iou(prior.get("vehicle_box"), event.get("vehicle_box")) > iou_threshold
            ),
            None,
        )
        if match is None:
            kept.append(event)
        else:
            suppressed.append({**event, "suppressed_by": match.get("event_id"),
                               "suppression_reason": "SAME_CAMERA_TYPE_TIME_AND_BOX_IOU"})
    return sorted(kept, key=lambda e: int(e.get("frame_idx", 0))), suppressed


class IncrementalDuplicateSuppressor:
    """Check events incrementally as they arrive against already emitted events."""

    def __init__(self, time_window_sec: float = 2.0, iou_threshold: float = 0.5) -> None:
        self.time_window_sec = time_window_sec
        self.iou_threshold = iou_threshold
        self.kept: list[dict[str, Any]] = []
        self.suppressed: list[dict[str, Any]] = []

    def process(self, event: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        match = next(
            (
                prior for prior in self.kept
                if str(prior.get("camera_id")) == str(event.get("camera_id"))
                and prior.get("vehicle_type") == event.get("vehicle_type")
                and abs(float(prior.get("timestamp_sec", 0)) -
                        float(event.get("timestamp_sec", 0))) <= self.time_window_sec
                and _event_iou(prior.get("vehicle_box"), event.get("vehicle_box")) > self.iou_threshold
            ),
            None,
        )
        if match is None:
            self.kept.append(event)
            return True, event
        else:
            suppressed_event = {
                **event,
                "suppressed_by": match.get("event_id"),
                "suppression_reason": "SAME_CAMERA_TYPE_TIME_AND_BOX_IOU",
            }
            self.suppressed.append(suppressed_event)
            return False, suppressed_event


def _config_for_source(config: EngineConfig, source: str | Path) -> EngineConfig:
    source_text = str(source)
    if source_text.lower().startswith(("rtsp://", "http://", "https://")):
        return config
    source_path = Path(source_text)
    camera_path = (Path(__file__).resolve().parent / "ai_engine" / "config" /
                   "cameras" / f"{source_path.stem}.json")
    if not camera_path.is_file():
        return config
    camera_data = json.loads(camera_path.read_text(encoding="utf-8"))
    camera_data = camera_data.get("camera", camera_data)
    return load_config({
        "camera": {**config.camera.__dict__, **camera_data},
        "thresholds": config.thresholds.__dict__,
        "paths": config.paths.__dict__,
        "accumulator_max_age": config.accumulator_max_age,
        "lost_grace_frames": config.lost_grace_frames,
        "transfer_time_gap": config.transfer_time_gap,
        "transfer_position_gap": config.transfer_position_gap,
        "start_sec": config.start_sec,
        "end_sec": config.end_sec,
    })


def run_pipeline(
    source: str | Path,
    config: EngineConfig | None = None,
    *,
    mode: PipelineMode = "both",
    on_event: Callable[[dict[str, Any]], None] | None = None,
    on_frame: Callable[[str, int, Any], None] | None = None,
    on_annotated_frame: Callable[[bytes, int], None] | None = None,
    on_transfer: Callable[[dict[str, Any]], None] | None = None,
    on_crossing: Callable[[dict[str, Any]], None] | None = None,
    on_track: Callable[[dict[str, Any]], None] | None = None,
    on_suppressed: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
    live: bool = False,
    max_annotated_fps: float = 10.0,
    helmet_detector=None,
    seatbelt_detector=None,
) -> list[dict[str, Any]]:
    """Run enabled Stage 6 checks over a file or stream with live/offline suppression."""
    if mode not in ("helmet", "seatbelt", "both"):
        raise ValueError("mode must be 'helmet', 'seatbelt', or 'both'")
    if config is None:
        config = load_config()
    config = _config_for_source(config, source)

    source_text = str(source)
    if not source_text.lower().startswith(("rtsp://", "http://", "https://")):
        if not Path(source_text).is_file():
            raise FileNotFoundError(f"Video file not found: {source_text}")

    modes = ("helmet", "seatbelt") if mode == "both" else (mode,)
    if "seatbelt" in modes and not config.camera.check_seatbelt:
        print(f"Seatbelt classification disabled: camera_view={config.camera.camera_view!r}; "
              "car tracking remains active.")

    events: list[dict[str, Any]] = []
    live_events: list[dict[str, Any]] = []
    last_annotated_time = 0.0
    min_frame_interval = 1.0 / max(0.1, max_annotated_fps)

    def live_event_handler(event: dict[str, Any]) -> None:
        live_events.append(event)
        if on_event is not None:
            on_event(event)

    for selected_mode in modes:
        if stop_event is not None and stop_event.is_set():
            break

        run_config = load_config({
            "camera": {
                **config.camera.__dict__,
                "check_helmet": selected_mode == "helmet",
                "check_seatbelt": selected_mode == "seatbelt" and config.camera.camera_view == "front",
            },
            "thresholds": config.thresholds.__dict__,
            "paths": config.paths.__dict__,
            "accumulator_max_age": config.accumulator_max_age,
            "lost_grace_frames": config.lost_grace_frames,
            "transfer_time_gap": config.transfer_time_gap,
            "transfer_position_gap": config.transfer_position_gap,
            "start_sec": config.start_sec,
            "end_sec": config.end_sec,
        })

        def frame_callback(frame_idx: int, frame, selected=selected_mode) -> None:
            nonlocal last_annotated_time
            if on_frame is not None:
                on_frame(selected, frame_idx, frame)

            if on_annotated_frame is not None:
                now = time.monotonic()
                if (now - last_annotated_time) >= min_frame_interval or last_annotated_time == 0.0:
                    display_frame = frame.copy()
                    # Show which pass the stream is in
                    pass_text = f"PASS: {selected.upper()}"
                    cv2.putText(
                        display_frame,
                        pass_text,
                        (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 255),
                        2,
                    )
                    h, w = display_frame.shape[:2]
                    target_w = 960
                    target_h = max(1, int(h * target_w / w))
                    resized = cv2.resize(display_frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    success, buffer = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if success:
                        on_annotated_frame(buffer.tobytes(), frame_idx)
                        last_annotated_time = now

        target_event_sink = live_event_handler if live else events.append

        if selected_mode == "helmet":
            selected_events = process_motorcycles(
                source_text, run_config, target_event_sink, detector=helmet_detector,
                on_frame=frame_callback if (on_frame is not None or on_annotated_frame is not None) else None,
                on_transfer=on_transfer, on_crossing=on_crossing, on_track=on_track,
                stop_event=stop_event,
            )
        else:
            selected_events = process_cars(
                source_text, run_config, target_event_sink, detector=seatbelt_detector,
                on_frame=frame_callback if (on_frame is not None or on_annotated_frame is not None) else None,
                on_transfer=on_transfer, on_crossing=on_crossing, on_track=on_track,
                stop_event=stop_event,
            )

        if not live and len(events) < len(selected_events):
            events.extend(selected_events[len(events):])

    if live:
        kept, suppressed = suppress_duplicate_events(live_events)
        if on_suppressed is not None:
            for event in suppressed:
                on_suppressed(event)
        return kept

    kept, suppressed = suppress_duplicate_events(events)
    if on_event is not None:
        for event in kept:
            on_event(event)
    if on_suppressed is not None:
        for event in suppressed:
            on_suppressed(event)
    return sorted(kept, key=lambda event: (event.get("frame_idx", 0), event.get("vehicle_class", "")))
