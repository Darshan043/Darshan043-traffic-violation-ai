"""Short deterministic video-level tests for the Stage 5 CLI plumbing."""
import csv
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import scripts.s5_track as s5_track


class Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value

    def tolist(self):
        return self.value


def detection(track_id, cls, conf, coords):
    return SimpleNamespace(id=None if track_id is None else Scalar(track_id), cls=Scalar(cls),
                            conf=Scalar(conf), xyxy=[Scalar(list(coords))])


class FakeModel:
    names = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def __init__(self, frames):
        self.frames = frames
        self.calls = []

    def track(self, frame, **kwargs):
        self.calls.append(kwargs)
        items = self.frames[min(len(self.calls)-1, len(self.frames)-1)]
        return [SimpleNamespace(boxes=items, names=self.names)]


def write_clip(path, frame_count=4):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48))
    if not writer.isOpened():
        pytest.skip("mp4v VideoWriter codec is unavailable")
    for index in range(frame_count):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        cv2.rectangle(frame, (index, 10), (30+index, 35), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def run_cli(monkeypatch, tmp_path, fake_model, *, empty=False):
    video = tmp_path / "input.mp4"
    model_file = tmp_path / "dummy.pt"
    output_video = tmp_path / "annotated.mp4"
    output_csv = tmp_path / "tracks.csv"
    write_clip(video)
    model_file.write_bytes(b"test fixture")
    monkeypatch.setattr(s5_track, "YOLO", lambda _: fake_model)
    monkeypatch.setattr("sys.argv", ["s5_track.py", "--video", str(video), "--model", str(model_file),
                                      "--end-sec", "0.4", "--save", "--no-show", "--out", str(output_video),
                                      "--csv", str(output_csv)])
    s5_track.main()
    return output_video, output_csv


def test_short_video_initializes_tracker_and_writes_video_and_csv(monkeypatch, tmp_path, capsys):
    frames = [
        [detection(10, 2, .9, [2, 5, 20, 35]), detection(20, 3, .8, [25, 5, 50, 40]),
         detection(None, 5, .7, [0, 0, 12, 12])],
        [detection(10, 2, .85, [3, 5, 21, 35]), detection(20, 3, .75, [26, 5, 51, 40])],
        [],
        [detection(10, 2, .8, [5, 5, 23, 35]), detection(20, 3, .7, [27, 5, 52, 40])],
    ]
    fake = FakeModel(frames)
    video, csv_path = run_cli(monkeypatch, tmp_path, fake)
    assert video.is_file() and video.stat().st_size > 0
    with video.open("rb") as _:
        pass
    capture = cv2.VideoCapture(str(video))
    assert int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) == 4
    capture.release()
    rows = list(csv.DictReader(csv_path.open()))
    assert {row["track_id"] for row in rows} == {"10", "20"}
    assert {row["class"] for row in rows} == {"car", "motorcycle"}
    assert {row["frames_seen"] for row in rows} == {"3"}
    assert all(row["first_frame"] == "0" and row["last_frame"] == "3" for row in rows)
    assert next(row for row in rows if row["track_id"] == "10")["mean_conf"] == "0.85000"
    assert all(call["persist"] is True and call["classes"] == [2, 3, 5, 7] for call in fake.calls)
    assert "single_frame_tracks=0" in capsys.readouterr().out


def test_empty_detections_write_empty_csv_and_finish_without_division_error(monkeypatch, tmp_path, capsys):
    fake = FakeModel([[], [], [], []])
    video, csv_path = run_cli(monkeypatch, tmp_path, fake, empty=True)
    assert video.is_file() and video.stat().st_size > 0
    assert list(csv.DictReader(csv_path.open())) == []
    output = capsys.readouterr().out
    assert "unique_ids_per_class={}" in output
    assert "Mean track length=0.00; median=0.00" in output
