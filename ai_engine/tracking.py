"""Small tracking data structures shared by Stage 5 and later stages."""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any

from ai_engine.association import Box


@dataclass(frozen=True)
class Track:
    id: int
    cls: int
    box: Box
    conf: float
    anchor: tuple[float, float]


def results_to_tracks(result: Any) -> list[Track]:
    """Convert one Ultralytics tracking result; detections without IDs are ignored."""
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    tracks = []
    for detection in boxes:
        track_id = getattr(detection, "id", None)
        if track_id is None:
            continue
        if hasattr(track_id, "item"):
            track_id = track_id.item()
        coords = detection.xyxy[0].tolist()
        box = Box(*(float(value) for value in coords))
        cls_value = detection.cls.item() if hasattr(detection.cls, "item") else detection.cls[0]
        conf_value = detection.conf.item() if hasattr(detection.conf, "item") else detection.conf[0]
        tracks.append(Track(int(track_id), int(cls_value), box, float(conf_value),
                            ((box.x1 + box.x2) / 2, box.y2)))
    return tracks


class TrackStore:
    """Keep short anchor histories and per-ID lifetime/class statistics."""

    def __init__(self, history_size: int = 60):
        if history_size < 1:
            raise ValueError("history_size must be positive")
        self.history: dict[int, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self.first_seen: dict[int, int] = {}
        self.last_seen: dict[int, int] = {}
        self.class_votes: dict[int, Counter[int]] = defaultdict(Counter)
        self.tracks: dict[int, Track] = {}

    def update(self, frame_idx: int, tracks: list[Track]) -> None:
        for track in tracks:
            self.tracks[track.id] = track
            self.first_seen.setdefault(track.id, frame_idx)
            self.last_seen[track.id] = frame_idx
            self.class_votes[track.id][track.cls] += 1
            self.history[track.id].append(track.anchor)

    def cleanup(self, frame_idx: int, max_age: int = 120) -> list[int]:
        if max_age < 0:
            raise ValueError("max_age must not be negative")
        removed = [track_id for track_id, last in self.last_seen.items()
                   if frame_idx - last > max_age]
        for track_id in removed:
            self.tracks.pop(track_id, None)
            self.history.pop(track_id, None)
            self.first_seen.pop(track_id, None)
            self.last_seen.pop(track_id, None)
            self.class_votes.pop(track_id, None)
        return removed

    def class_vote(self, track_id: int) -> int | None:
        votes = self.class_votes.get(track_id)
        return votes.most_common(1)[0][0] if votes else None
