"""Per-track zone crossing for polygons and tripwire lines.

The engine should decide once, when a vehicle crosses the interesting part of
the camera view, not on every frame the vehicle is still there.

Each track ID has its own small memory:
- last anchor point (bottom-centre of the vehicle box)
- whether that point was inside the polygon
- whether this ID has already fired

`crossed()` is True only the first time that ID completes a crossing.
`lost()` applies the lost-near-the-zone rule: if the tracker drops the vehicle
while it is still close to the zone, and this ID has not fired yet, fire once.
That avoids missing a vehicle that vanished on the line, without firing again
for the same ID.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


Point = tuple[float, float]


@dataclass
class _TrackState:
    last_anchor: Point | None = None
    inside: bool = False
    fired: bool = False


def _is_finite_point(point: Point) -> bool:
    return math.isfinite(point[0]) and math.isfinite(point[1])


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])


def _on_segment(a: Point, b: Point, c: Point, eps: float = 1e-9) -> bool:
    return (
        min(a[0], b[0]) - eps <= c[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= c[1] <= max(a[1], b[1]) + eps
    )


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point) -> bool:
    """Return True if the two finite line segments touch or cross."""
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    if (o1 > 0 > o2 or o1 < 0 < o2) and (o3 > 0 > o4 or o3 < 0 < o4):
        return True
    if abs(o1) <= 1e-9 and _on_segment(a1, a2, b1):
        return True
    if abs(o2) <= 1e-9 and _on_segment(a1, a2, b2):
        return True
    if abs(o3) <= 1e-9 and _on_segment(b1, b2, a1):
        return True
    if abs(o4) <= 1e-9 and _on_segment(b1, b2, a2):
        return True
    return False


def point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    """Ray-casting test. Boundary points count as inside."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if segments_intersect((xi, yi), (xj, yj), point, point):
            return True
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 0.0) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def point_to_segment_distance(point: Point, start: Point, end: Point) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def min_distance_to_edges(point: Point, vertices: list[Point]) -> float:
    if len(vertices) == 2:
        return point_to_segment_distance(point, vertices[0], vertices[1])
    best = math.inf
    for i, start in enumerate(vertices):
        end = vertices[(i + 1) % len(vertices)]
        best = min(best, point_to_segment_distance(point, start, end))
    return best


def looks_normalised(vertices: list[Point]) -> bool:
    return all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in vertices)


class Zone:
    """Polygon (3+ points) or tripwire line (exactly 2 points)."""

    def __init__(
        self,
        vertices: list[Point],
        *,
        lost_near_distance: float = 40.0,
        frame_size: tuple[int, int] | None = None,
    ) -> None:
        if len(vertices) < 2:
            raise ValueError("A zone needs a line (2 points) or a polygon (3+ points)")
        if lost_near_distance < 0:
            raise ValueError("lost_near_distance must not be negative")
        cleaned = [(float(x), float(y)) for x, y in vertices]
        if not all(_is_finite_point(point) for point in cleaned):
            raise ValueError("Zone vertices must be finite numbers")
        if frame_size is not None:
            width, height = frame_size
            if width <= 0 or height <= 0:
                raise ValueError("frame_size width and height must be positive")
            if looks_normalised(cleaned):
                cleaned = [(x * width, y * height) for x, y in cleaned]
        self.vertices = cleaned
        self.lost_near_distance = float(lost_near_distance)
        self.is_line = len(cleaned) == 2
        self._state: dict[int, _TrackState] = {}

    def _inside(self, point: Point) -> bool:
        if self.is_line:
            return False
        return point_in_polygon(point, self.vertices)

    def distance(self, point: Point) -> float:
        """0 when the point is inside a polygon, otherwise distance to the edge/line."""
        if not self.is_line and self._inside(point):
            return 0.0
        return min_distance_to_edges(point, self.vertices)

    def _path_crosses(self, previous: Point, current: Point) -> bool:
        if self.is_line:
            return segments_intersect(previous, current, self.vertices[0], self.vertices[1])
        if self._inside(previous) != self._inside(current):
            return True
        for i, start in enumerate(self.vertices):
            end = self.vertices[(i + 1) % len(self.vertices)]
            if segments_intersect(previous, current, start, end):
                return True
        return False

    def _mark_fired(self, state: _TrackState) -> bool:
        state.fired = True
        return True

    def crossed(self, track_id: int, anchor: Point) -> bool:
        """Update this track and return True only on its first relevant crossing."""
        if not _is_finite_point(anchor):
            raise ValueError("anchor must be a finite (x, y) point")
        state = self._state.setdefault(track_id, _TrackState())
        inside = self._inside(anchor)
        previous = state.last_anchor
        state.last_anchor = anchor
        state.inside = inside

        if state.fired:
            return False
        if previous is None:
            # A vehicle that first appears already inside a polygon is in the
            # decision region, so this counts as the one crossing for that ID.
            if inside:
                return self._mark_fired(state)
            return False
        if self._path_crosses(previous, anchor):
            return self._mark_fired(state)
        return False

    def lost(self, track_id: int) -> bool:
        """Fire once if this ID vanished near the zone and has not already fired."""
        state = self._state.get(track_id)
        if state is None or state.fired or state.last_anchor is None:
            return False
        if self.distance(state.last_anchor) <= self.lost_near_distance:
            return self._mark_fired(state)
        return False

    def forget(self, track_id: int) -> None:
        self._state.pop(track_id, None)

    def transfer(self, old_track_id: int, new_track_id: int) -> bool:
        """Move crossing history to a replacement tracker ID if the target is unused."""
        if old_track_id == new_track_id or new_track_id in self._state:
            return False
        state = self._state.pop(old_track_id, None)
        if state is None:
            return False
        self._state[new_track_id] = state
        return True

    def forget_missing(self, active_ids: set[int]) -> list[int]:
        """Drop state for IDs that are no longer alive. Returns forgotten IDs."""
        stale = [track_id for track_id in self._state if track_id not in active_ids]
        for track_id in stale:
            self.forget(track_id)
        return stale
