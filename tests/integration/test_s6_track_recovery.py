from pathlib import Path

import cv2
import numpy as np
import pytest

from ai_engine.accumulator import Accumulator
from ai_engine.association import Box, HeadDetection, HelmetResult
from ai_engine.config import load_config
from ai_engine.detector import HelmetAnalysis
from ai_engine.helmet_pipeline import process_motorcycles
from ai_engine.seatbelt import SeatbeltResult
from ai_engine.seatbelt_pipeline import SeatbeltAnalysis, process_cars
from ai_engine.tracking import Track


def _make_video(path: Path, frame_count: int = 5) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v VideoWriter codec is unavailable")
    for _ in range(frame_count):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()


def test_accumulator_transfers_observations_to_unambiguous_replacement_id():
    memory = Accumulator()
    old = memory.get(10, 3, 0)
    old.observations.append(HelmetResult("no_helmet", 0.9, "OK"))
    old.last_anchor = (100.0, 100.0)
    old.last_seen = 5

    replaced = memory.transfer_track(
        camera_id="cam1",
        vehicle_class=3,
        track_id=20,
        frame_idx=7,
        anchor=(110.0, 100.0),
        active_track_ids={20},
        time_gap=4,
        position_gap=30,
    )

    assert replaced == 10
    assert 10 not in memory
    assert memory.get(20, 3).observations == [old.observations[0]]
    assert memory.get(20, 3).last_anchor == (110.0, 100.0)


@pytest.mark.parametrize(
    "candidate",
    [
        {"track_id": 11, "cls": 2, "last_anchor": (100.0, 100.0), "last_seen": 5},
        {"track_id": 11, "cls": 3, "last_anchor": (500.0, 500.0), "last_seen": 5},
        {"track_id": 11, "cls": 3, "last_anchor": (100.0, 100.0), "last_seen": 0},
    ],
)
def test_accumulator_rejects_wrong_class_far_or_stale_replacement(candidate):
    memory = Accumulator()
    old = memory.get(candidate["track_id"], candidate["cls"], 0)
    old.last_anchor = candidate["last_anchor"]
    old.last_seen = candidate["last_seen"]

    assert memory.transfer_track(
        camera_id="cam1",
        vehicle_class=3,
        track_id=20,
        frame_idx=7,
        anchor=(105.0, 100.0),
        active_track_ids={20},
        time_gap=4,
        position_gap=30,
    ) is None
    assert candidate["track_id"] in memory
    assert 20 not in memory


def test_accumulator_rejects_ambiguous_replacement_match():
    memory = Accumulator()
    for track_id, anchor in ((10, (100.0, 100.0)), (11, (102.0, 100.0))):
        candidate = memory.get(track_id, 3, 0)
        candidate.last_anchor = anchor
        candidate.last_seen = 5

    assert memory.transfer_track(
        camera_id="cam1",
        vehicle_class=3,
        track_id=20,
        frame_idx=7,
        anchor=(101.0, 100.0),
        active_track_ids={20},
        time_gap=4,
        position_gap=30,
    ) is None
    assert 10 in memory and 11 in memory and 20 not in memory


class _ScriptedDetector:
    def __init__(self, mode: str, sequence: list[tuple[int, float] | None]):
        self.mode = mode
        self.sequence = sequence
        self.frame_index = 0

    def _tracks(self):
        item = self.sequence[self.frame_index]
        self.frame_index += 1
        if item is None:
            return []
        track_id, center = item
        box = Box(center - 8, 8, center + 8, 32)
        return [Track(track_id, 3 if self.mode == "helmet" else 2, box, 0.9, (center, 32))]

    def track_vehicles(self, frame):
        return self._tracks()

    def track_cars(self, frame):
        return self._tracks()

    def helmet_observation(self, frame, track):
        person = Box(track.box.x1, 0, track.box.x2, 24)
        head = HeadDetection(Box(track.box.x1 + 2, 2, track.box.x2 - 2, 8), "no_helmet", 0.9)
        return HelmetAnalysis(
            track, HelmetResult("no_helmet", 0.9, "OK"), person,
            (person,), (person,), (head,), track.box,
        )

    def seatbelt_observation(self, frame, track):
        return SeatbeltAnalysis(
            track, SeatbeltResult("no_seatbelt", 0.9, "OK"),
            Box(track.box.x1, track.box.y1, track.box.x2, track.box.y1 + 12),
            track.box, (),
        )


def _run(mode: str, video: Path, evidence: Path, sequence: list[tuple[int, float] | None],
         *, grace: int):
    config = load_config({
        "camera": {
            "zone": [(32, 0), (32, 48)],
            "observe_distance": 1000,
            "min_motorcycle_width": 1,
            "min_car_height": 1,
            "lost_near_distance": 20,
            "check_helmet": mode == "helmet",
            "check_seatbelt": mode == "seatbelt",
        },
        "paths": {"evidence_dir": str(evidence)},
        "lost_grace_frames": grace,
    })
    detector = _ScriptedDetector(mode, sequence)
    processor = process_motorcycles if mode == "helmet" else process_cars
    return processor(str(video), config, lambda event: None, detector=detector)


@pytest.mark.parametrize("mode", ["helmet", "seatbelt"])
def test_id_switch_transfers_observations_and_emits_only_one_event(mode, tmp_path):
    video = tmp_path / f"{mode}_switch.mp4"
    _make_video(video, frame_count=4)
    events = _run(
        mode, video, tmp_path / f"{mode}_evidence",
        [(10, 10), (10, 20), (20, 40), (20, 45)],
        grace=3,
    )

    assert len(events) == 1
    assert events[0]["track_id"] == 20
    assert events[0]["observations"] == 3


@pytest.mark.parametrize("mode", ["helmet", "seatbelt"])
def test_temporary_disappearance_does_not_finalize_before_grace(mode, tmp_path):
    video = tmp_path / f"{mode}_temporary_loss.mp4"
    _make_video(video, frame_count=5)
    events = _run(
        mode, video, tmp_path / f"{mode}_temporary_evidence",
        [(10, 10), (10, 20), None, (10, 40), (10, 45)],
        grace=3,
    )

    assert len(events) == 1
    assert events[0]["decision"] == "VIOLATION"
    assert events[0]["observations"] == 3


@pytest.mark.parametrize("mode", ["helmet", "seatbelt"])
def test_permanent_near_zone_loss_finalizes_only_after_grace(mode, tmp_path):
    video = tmp_path / f"{mode}_permanent_loss.mp4"
    _make_video(video, frame_count=4)
    events = _run(
        mode, video, tmp_path / f"{mode}_permanent_evidence",
        [(10, 10), (10, 20), None, None],
        grace=2,
    )

    assert len(events) == 1
    assert events[0]["decision"] == "NEEDS_REVIEW"
    assert events[0]["frame_idx"] == 3
