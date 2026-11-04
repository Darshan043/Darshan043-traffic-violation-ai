"""Tests for Stage 7 live engine modifications (Part 1)."""
from __future__ import annotations

import threading
from typing import Any
import numpy as np
import pytest

from ai_engine.association import Box, HeadDetection, HelmetResult
from ai_engine.config import load_config
from ai_engine.detector import HelmetAnalysis
from ai_engine.seatbelt import SeatbeltDetection, SeatbeltResult
from ai_engine.seatbelt_pipeline import SeatbeltAnalysis
from ai_engine.tracking import Track
from pipeline import IncrementalDuplicateSuppressor, run_pipeline


class _FakeHelmetDetector:
    def __init__(self) -> None:
        self.index = 0

    def track_vehicles(self, frame):
        centers = [10, 25, 40, 45, 50, 55]
        center = centers[min(self.index, len(centers) - 1)]
        self.index += 1
        box = Box(center - 10, 5, center + 10, 25)
        return [Track(42, 3, box, 0.9, (center, box.y2))]

    def helmet_observation(self, frame, track):
        driver = Box(20, 2, 30, 20)
        head = HeadDetection(Box(23, 3, 27, 8), "no_helmet", 0.9)
        return HelmetAnalysis(
            track,
            HelmetResult("no_helmet", 0.9, "OK"),
            driver,
            (driver,),
            (driver,),
            (head,),
            Box(0, 0, 64, 48),
        )


class _FakeSeatbeltDetector:
    def __init__(self) -> None:
        self.index = 0

    def track_cars(self, frame):
        centers = [10, 25, 40, 45, 50, 55]
        center = centers[min(self.index, len(centers) - 1)]
        self.index += 1
        box = Box(center - 10, 5, center + 10, 25)
        return [Track(7, 2, box, 0.9, (center, box.y2))]

    def seatbelt_observation(self, frame, track):
        crop = Box(25, 5, 35, 15)
        return SeatbeltAnalysis(
            track,
            SeatbeltResult("no_seatbelt", 0.9, "OK", 300),
            crop,
            crop,
            (SeatbeltDetection(Box(2, 2, 7, 8), "no_seatbelt", 0.9),),
        )


def _create_synthetic_video(path, num_frames=4, width=64, height=48):
    import cv2
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 25.0, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), 100, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_incremental_duplicate_suppressor():
    suppressor = IncrementalDuplicateSuppressor(time_window_sec=2.0, iou_threshold=0.5)

    ev1 = {
        "event_id": "cam1_f10_t1_helmet",
        "camera_id": "cam1",
        "vehicle_type": "motorcycle",
        "timestamp_sec": 1.0,
        "vehicle_box": [100.0, 100.0, 200.0, 200.0],
    }
    kept, p1 = suppressor.process(ev1)
    assert kept is True
    assert p1["event_id"] == "cam1_f10_t1_helmet"

    # Duplicate: same cam, type, time 1.5s, overlapping box
    ev2 = {
        "event_id": "cam1_f15_t2_helmet",
        "camera_id": "cam1",
        "vehicle_type": "motorcycle",
        "timestamp_sec": 1.5,
        "vehicle_box": [105.0, 105.0, 205.0, 205.0],
    }
    kept, p2 = suppressor.process(ev2)
    assert kept is False
    assert p2["suppressed_by"] == "cam1_f10_t1_helmet"
    assert p2["suppression_reason"] == "SAME_CAMERA_TYPE_TIME_AND_BOX_IOU"
    assert len(suppressor.kept) == 1
    assert len(suppressor.suppressed) == 1


def test_pipeline_live_events_and_annotated_frame(tmp_path):
    video = tmp_path / "test_live.mp4"
    _create_synthetic_video(video, num_frames=4, width=64, height=48)

    config = load_config({
        "camera": {
            "id": "cam_live",
            "zone": [30, 0, 30, 48],
            "camera_view": "front",
            "check_helmet": True,
            "check_seatbelt": False,
            "min_motorcycle_width": 1,
            "min_car_height": 1,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })

    live_events = []
    annotated_frames = []

    events = run_pipeline(
        video,
        config,
        mode="helmet",
        live=True,
        on_event=live_events.append,
        on_annotated_frame=lambda jpeg, idx: annotated_frames.append((idx, jpeg)),
        helmet_detector=_FakeHelmetDetector(),
    )

    assert len(live_events) == len(events)
    assert len(annotated_frames) > 0
    first_idx, first_jpeg = annotated_frames[0]
    assert isinstance(first_jpeg, bytes)
    assert first_jpeg.startswith(b"\xff\xd8")


def test_pipeline_stop_event(tmp_path):
    video = tmp_path / "test_stop.mp4"
    _create_synthetic_video(video, num_frames=10, width=64, height=48)

    config = load_config({
        "camera": {
            "id": "cam_stop",
            "zone": [30, 0, 30, 48],
            "camera_view": "front",
            "min_motorcycle_width": 1,
            "min_car_height": 1,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })

    stop_event = threading.Event()
    stop_event.set()  # Stop immediately

    frames_seen = []
    events = run_pipeline(
        video,
        config,
        mode="helmet",
        stop_event=stop_event,
        on_frame=lambda m, idx, f: frames_seen.append(idx),
        helmet_detector=_FakeHelmetDetector(),
    )

    assert len(frames_seen) == 0
    assert len(events) == 0
