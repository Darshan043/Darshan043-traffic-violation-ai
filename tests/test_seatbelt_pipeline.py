import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from ai_engine.association import Box
from ai_engine.config import load_config
from ai_engine.seatbelt import SeatbeltResult
from ai_engine.seatbelt_pipeline import SeatbeltAnalysis, SeatbeltDetector, process_cars
from ai_engine.tracking import Track


def make_video(path, frames=4):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v VideoWriter codec is unavailable")
    for _ in range(frames):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()


class FakeSeatbeltDetector:
    def __init__(self, label="no_seatbelt", confidence=0.9):
        self.label = label
        self.confidence = confidence
        self.index = 0

    def track_cars(self, frame):
        centers = [10, 25, 40, 45]
        center = centers[self.index]
        self.index += 1
        box = Box(center - 10, 5, center + 10, 25)
        return [Track(42, 2, box, 0.9, (center, box.y2))]

    def seatbelt_observation(self, frame, track):
        result = SeatbeltResult(self.label, self.confidence, "OK")
        return SeatbeltAnalysis(
            track,
            result,
            Box(0, 0, 10, 10),
            Box(0, 0, 10, 10),
            (),
        )


def test_car_seatbelt_pipeline_emits_once_when_track_crosses_zone(tmp_path):
    video = tmp_path / "seatbelt_crossing.mp4"
    make_video(video)
    config = load_config({
        "camera": {
            "zone": [(32, 0), (32, 48)],
            "observe_distance": 1000,
            "min_car_height": 1,
            "check_seatbelt": True,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })
    received = []
    frames = []
    events = process_cars(
        str(video),
        config,
        received.append,
        detector=FakeSeatbeltDetector(label="no_seatbelt", confidence=0.9),
        on_frame=lambda index, frame: frames.append(index),
    )
    assert len(frames) == 4
    assert events == received
    assert len(events) == 1
    assert events[0]["decision"] == "VIOLATION"
    assert events[0]["reason"] == "CLEAR_VIOLATION"
    assert events[0]["observations"] == 3
    saved = events[0]["evidence"]
    assert Path(saved["directory"]).is_dir()
    assert all(Path(saved[key]).is_file() for key in ("full_frame", "vehicle_crop", "driver_rider_crop", "metadata"))
    metadata = json.loads(Path(saved["metadata"]).read_text(encoding="utf-8"))
    assert metadata["decision"] == "VIOLATION"


def test_car_seatbelt_pipeline_handles_unclear_low_confidence(tmp_path):
    video = tmp_path / "seatbelt_unclear.mp4"
    make_video(video)
    config = load_config({
        "camera": {
            "zone": [(32, 0), (32, 48)],
            "observe_distance": 1000,
            "min_car_height": 1,
            "check_seatbelt": True,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })
    events = process_cars(
        str(video),
        config,
        lambda event: None,
        detector=FakeSeatbeltDetector(label="unclear", confidence=0.20),
    )
    assert len(events) == 1
    assert events[0]["decision"] == "NEEDS_REVIEW"
    assert events[0]["reason"] == "UNCLEAR_OBSERVATIONS"
