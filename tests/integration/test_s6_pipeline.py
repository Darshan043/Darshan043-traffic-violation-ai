import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from ai_engine.association import Box, HeadDetection, HelmetResult
from ai_engine.config import load_config
from ai_engine.detector import HelmetAnalysis
from ai_engine.seatbelt import SeatbeltDetection, SeatbeltResult
from ai_engine.seatbelt_pipeline import SeatbeltAnalysis
from ai_engine.tracking import Track
from pipeline import run_pipeline


def _make_video(path: Path, frame_count: int = 4) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v VideoWriter codec is unavailable")
    for _ in range(frame_count):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()


class _FakeHelmetDetector:
    def __init__(self) -> None:
        self.index = 0

    def track_vehicles(self, frame):
        centers = [10, 25, 40, 45]
        center = centers[self.index]
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
        centers = [10, 25, 40, 45]
        center = centers[self.index]
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


def test_standalone_pipeline_runs_both_checks_and_saves_events_and_evidence(tmp_path):
    video = tmp_path / "combined.mp4"
    _make_video(video)
    config = load_config({
        "camera": {
            "zone": [(32, 0), (32, 48)],
            "observe_distance": 1000,
            "min_motorcycle_width": 1,
            "min_car_height": 1,
            "camera_view": "front",
            "check_seatbelt": True,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })
    frames = []
    events = run_pipeline(
        video,
        config,
        mode="both",
        helmet_detector=_FakeHelmetDetector(),
        seatbelt_detector=_FakeSeatbeltDetector(),
        on_frame=lambda mode, frame_idx, frame: frames.append((mode, frame_idx)),
    )

    assert {event["violation_type"] for event in events} == {"helmet", "seatbelt"}
    assert all(event["decision"] == "VIOLATION" for event in events)
    assert {mode for mode, _ in frames} == {"helmet", "seatbelt"}
    for event in events:
        evidence = event["evidence"]
        assert Path(evidence["metadata"]).is_file()
        metadata = json.loads(Path(evidence["metadata"]).read_text(encoding="utf-8"))
        assert metadata["event"]["violation_type"] == event["violation_type"]
        if event["violation_type"] == "seatbelt":
            assert metadata["boxes"]["driver_rider_crop_source"] == "driver_side_crop"
            assert metadata["boxes"]["driver_side_crop"] == [25.0, 5.0, 35.0, 15.0]
            assert metadata["boxes"]["seatbelt_detections"][0]["box"] == [27.0, 7.0, 32.0, 13.0]
            crop = cv2.imread(evidence["driver_rider_crop"])
            assert crop is not None and crop.shape[:2] == (10, 10)


def test_pipeline_rejects_missing_local_video(tmp_path):
    with pytest.raises(FileNotFoundError, match="Video file not found"):
        run_pipeline(tmp_path / "missing.mp4", mode="helmet")
