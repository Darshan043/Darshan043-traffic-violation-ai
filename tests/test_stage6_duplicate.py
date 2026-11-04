from ai_engine.accumulator import soft_duplicate_event, track_switch_match
from ai_engine.zone import Zone


def test_soft_duplicate_event_blocks_same_vehicle_repeat():
    recent = [{
        "camera_id": "cam1",
        "vehicle_class": 2,
        "frame_idx": 50,
        "anchor": (130.0, 180.0),
        "decision": "VIOLATION",
    }]
    assert soft_duplicate_event(
        camera_id="cam1",
        vehicle_class=2,
        frame_idx=55,
        anchor=(135.0, 185.0),
        previous_result="VIOLATION",
        recent_events=recent,
        time_gap=10,
        position_gap=80.0,
    ) is True


def test_track_switch_match_reuses_nearby_anchor_for_new_id():
    recent = [{
        "camera_id": "cam1",
        "vehicle_class": 3,
        "track_id": 10,
        "frame_idx": 44,
        "anchor": (120.0, 170.0),
    }]
    match = track_switch_match(
        camera_id="cam1",
        vehicle_class=3,
        frame_idx=52,
        anchor=(128.0, 172.0),
        recent_tracks=recent,
        time_gap=12,
        position_gap=50.0,
    )
    assert match is not None
    assert match["track_id"] == 10


def test_lost_track_near_zone_only_fires_once():
    zone = Zone([(100, 100), (200, 100), (200, 200), (100, 200)], lost_near_distance=40)
    assert zone.crossed(99, (90, 150)) is False
    assert zone.lost(99) is True
    assert zone.lost(99) is False
