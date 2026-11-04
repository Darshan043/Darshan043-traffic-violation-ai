import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from ai_engine.association import Box, HelmetResult
from ai_engine.config import load_config
from ai_engine.detector import HelmetAnalysis
from ai_engine.helmet_pipeline import process_motorcycles
from ai_engine.tracking import Track


def make_video(path, frames=4):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v VideoWriter codec is unavailable")
    for _ in range(frames):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()


class FakeHelmetDetector:
    def __init__(self, label="no_helmet", reason="OK"):
        self.label = label
        self.reason = reason
        self.index = 0

    def track_vehicles(self, frame):
        centers = [10, 25, 40, 45]
        center = centers[self.index]
        self.index += 1
        box = Box(center - 10, 5, center + 10, 25)
        return [Track(42, 3, box, .9, (center, box.y2))]

    def helmet_observation(self, frame, track):
        return HelmetAnalysis(track, HelmetResult(self.label, .9 if self.reason == "OK" else 0.0,
                                                   self.reason),
                              Box(1, 1, 5, 5), (Box(1, 1, 5, 5),), (), (),
                              Box(0, 0, 64, 48))


def test_motorcycle_pipeline_emits_once_when_track_crosses_zone(tmp_path):
    video = tmp_path / "crossing.mp4"
    make_video(video)
    config = load_config({
        "camera": {
            "zone": [(32, 0), (32, 48)],
            "observe_distance": 1000,
            "min_motorcycle_width": 1,
        },
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })
    received = []
    frames = []
    events = process_motorcycles(str(video), config, received.append,
                                 detector=FakeHelmetDetector(),
                                 on_frame=lambda index, frame: frames.append(index))
    assert len(frames) == 4
    assert events == received
    assert len(events) == 1
    assert events[0]["decision"] == "VIOLATION"
    assert events[0]["reason"] == "CLEAR_VIOLATION"
    assert events[0]["observations"] == 3
    saved = events[0]["evidence"]
    assert Path(saved["directory"]).is_dir()
    assert all(Path(saved[key]).is_file()
               for key in ("full_frame", "vehicle_crop", "driver_rider_crop", "metadata"))


def test_needs_review_event_saves_all_evidence_and_metadata(tmp_path):
    video = tmp_path / "unclear.mp4"
    make_video(video)
    config = load_config({
        "camera": {"zone": [(32, 0), (32, 48)], "observe_distance": 1000,
                   "min_motorcycle_width": 1},
        "paths": {"evidence_dir": str(tmp_path / "evidence")},
    })
    events = process_motorcycles(
        str(video), config, lambda event: None,
        detector=FakeHelmetDetector(label="unclear", reason="NO_HEAD"),
    )
    assert len(events) == 1
    event = events[0]
    assert event["decision"] == "NEEDS_REVIEW"
    evidence = event["evidence"]
    assert all(Path(evidence[key]).is_file()
               for key in ("full_frame", "vehicle_crop", "driver_rider_crop", "metadata"))
    metadata = json.loads(Path(evidence["metadata"]).read_text(encoding="utf-8"))
    assert metadata["decision"] == "NEEDS_REVIEW"
    assert metadata["reason"] == "UNCLEAR_OBSERVATIONS"
    assert metadata["zone"]["type"] == "line"
    image = cv2.imread(evidence["driver_rider_crop"])
    assert image is not None and image.size > 0


def test_normalized_zone_is_scaled_to_actual_video_dimensions(tmp_path):
    video = tmp_path / "normalized.mp4"
    make_video(video, frames=1)
    config = load_config({"camera": {"zone": [(0, .5), (1, .5)],
                                     "observe_distance": 1000}})
    detector = FakeHelmetDetector()
    frames = []
    process_motorcycles(str(video), config, lambda event: None, detector=detector,
                        on_frame=lambda index, frame: frames.append(frame))
    # Overlay line is expected at y=24 on the 64x48 frame, not y=0/1 pixels.
    assert len(frames) == 1
    assert np.count_nonzero(np.all(frames[0][23:26, :, :] == (255, 255, 0), axis=2)) > 0
