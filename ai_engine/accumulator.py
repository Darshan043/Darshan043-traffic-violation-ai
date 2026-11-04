"""Per-track memory of helmet/seatbelt observations.

The decision function needs several frames, not one. This store keeps those
answers, the latest position, and one 'best' still image (highest-confidence
OK observation) for later evidence saving.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from ai_engine.association import Box


def _distance(anchor_a: tuple[float, float] | None, anchor_b: tuple[float, float] | None) -> float:
    if anchor_a is None or anchor_b is None:
        return float("inf")
    return math.hypot(anchor_a[0] - anchor_b[0], anchor_a[1] - anchor_b[1])


def soft_duplicate_event(
    *,
    camera_id: str,
    vehicle_class: int | str,
    frame_idx: int,
    anchor: tuple[float, float],
    previous_result: str | None,
    recent_events: list[dict],
    time_gap: int = 10,
    position_gap: float = 80.0,
) -> bool:
    """Suppress a repeated decision for the same vehicle near the same place.

    A second event is considered a soft duplicate when it matches the same camera,
    vehicle class, has a nearby anchor within a short time window, and the prior
    result is the same. This prevents double-counting the same violation when the
    tracker briefly blinks or the zone crossing is re-evaluated.
    """
    if previous_result is None:
        return False
    for event in recent_events:
        if str(event.get("camera_id")) != str(camera_id):
            continue
        if str(event.get("vehicle_class")) != str(vehicle_class):
            continue
        if abs(int(event.get("frame_idx", 0)) - frame_idx) > time_gap:
            continue
        if event.get("decision") != previous_result:
            continue
        prior_anchor = event.get("anchor")
        if _distance(prior_anchor, anchor) <= position_gap:
            return True
    return False


def track_switch_match(
    *,
    camera_id: str,
    vehicle_class: int | str,
    frame_idx: int,
    anchor: tuple[float, float],
    recent_tracks: list[dict],
    time_gap: int = 12,
    position_gap: float = 80.0,
) -> dict | None:
    """Return the nearest prior track state when a new tracker ID likely replaced an old one."""
    for recent in recent_tracks:
        if str(recent.get("camera_id")) != str(camera_id):
            continue
        if str(recent.get("vehicle_class")) != str(vehicle_class):
            continue
        if abs(int(recent.get("frame_idx", 0)) - frame_idx) > time_gap:
            continue
        if _distance(recent.get("anchor"), anchor) <= position_gap:
            return recent
    return None


@dataclass
class TrackMemory:
    track_id: int
    cls: int
    observations: list[object] = field(default_factory=list)
    last_anchor: tuple[float, float] | None = None
    last_box: Box | None = None
    first_seen: int = 0
    last_seen: int = 0
    best_frame: object | None = None
    best_box: Box | None = None
    best_context: object | None = None
    best_score: float = -1.0
    finalized: bool = False
    last_label: str | None = None

    def update_position(self, anchor: tuple[float, float], frame_idx: int, box: Box | None = None) -> None:
        self.last_anchor = anchor
        self.last_seen = frame_idx
        if box is not None:
            self.last_box = box

    def add_observation(
        self,
        observation: object,
        frame: object,
        box: Box,
        *,
        context: object | None = None,
    ) -> None:
        self.observations.append(observation)
        self.last_box = box
        self.last_label = str(getattr(observation, "label", None))
        reason = str(getattr(observation, "reason", "OK"))
        confidence = float(getattr(observation, "confidence", 0.0))
        # Keep a review frame even when every detector result is unclear.
        score = confidence if reason == "OK" else 0.0
        if score > self.best_score and frame is not None:
            self.best_score = score
            self.best_frame = frame.copy()
            self.best_box = box
            self.best_context = context


class Accumulator:
    def __init__(self, max_age: int = 120) -> None:
        if max_age < 0:
            raise ValueError("max_age must not be negative")
        self.max_age = max_age
        self._tracks: dict[int, TrackMemory] = {}
        self._recent_events: list[dict] = []
        self._recent_tracks: list[dict] = []

    def get(self, track_id: int, cls: int, frame_idx: int = 0) -> TrackMemory:
        memory = self._tracks.get(track_id)
        if memory is None:
            memory = TrackMemory(track_id=track_id, cls=cls, first_seen=frame_idx, last_seen=frame_idx)
            self._tracks[track_id] = memory
        return memory

    def __contains__(self, track_id: int) -> bool:
        return track_id in self._tracks

    def items(self) -> list[TrackMemory]:
        return list(self._tracks.values())

    def remember_event(
        self,
        *,
        camera_id: str,
        vehicle_class: int | str,
        track_id: int,
        frame_idx: int,
        anchor: tuple[float, float],
        decision: str,
    ) -> None:
        self._recent_events.append(
            {
                "camera_id": camera_id,
                "vehicle_class": vehicle_class,
                "track_id": track_id,
                "frame_idx": frame_idx,
                "anchor": anchor,
                "decision": decision,
            }
        )
        self._recent_events = self._recent_events[-80:]

    def remember_track(
        self,
        *,
        camera_id: str,
        vehicle_class: int | str,
        track_id: int,
        frame_idx: int,
        anchor: tuple[float, float],
    ) -> dict | None:
        current = {"camera_id": camera_id, "vehicle_class": vehicle_class, "track_id": track_id,
                   "frame_idx": frame_idx, "anchor": anchor}
        self._recent_tracks.append(current)
        self._recent_tracks = self._recent_tracks[-80:]
        return track_switch_match(
            camera_id=camera_id,
            vehicle_class=vehicle_class,
            frame_idx=frame_idx,
            anchor=anchor,
            recent_tracks=self._recent_tracks[:-1],
        )

    def transfer_track(
        self,
        *,
        camera_id: str,
        vehicle_class: int,
        track_id: int,
        frame_idx: int,
        anchor: tuple[float, float],
        active_track_ids: set[int],
        time_gap: int = 12,
        position_gap: float = 80.0,
    ) -> int | None:
        """Move unfinished observations to a replacement ID when a match is unambiguous."""
        if track_id in self._tracks:
            return None
        candidates = []
        for old_id, memory in self._tracks.items():
            age = frame_idx - memory.last_seen
            distance = _distance(memory.last_anchor, anchor)
            if (
                old_id not in active_track_ids
                and memory.cls == vehicle_class
                and 1 <= age <= time_gap
                and distance <= position_gap
            ):
                candidates.append((distance, old_id, memory))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: candidate[0])
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 15.0:
            return None

        _, old_id, memory = candidates[0]
        del self._tracks[old_id]
        memory.track_id = track_id
        memory.update_position(anchor, frame_idx)
        self._tracks[track_id] = memory
        return old_id

    def soft_duplicate(
        self,
        *,
        camera_id: str,
        vehicle_class: int | str,
        frame_idx: int,
        anchor: tuple[float, float],
        previous_result: str | None,
    ) -> bool:
        return soft_duplicate_event(
            camera_id=camera_id,
            vehicle_class=vehicle_class,
            frame_idx=frame_idx,
            anchor=anchor,
            previous_result=previous_result,
            recent_events=self._recent_events,
        )

    def cleanup_old(self, frame_idx: int) -> list[int]:
        removed = [
            track_id
            for track_id, memory in self._tracks.items()
            if frame_idx - memory.last_seen > self.max_age
        ]
        for track_id in removed:
            del self._tracks[track_id]
        return removed
