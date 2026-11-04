from ai_engine.config import load_config
from ai_engine.seatbelt import SeatbeltResult, guard_no_seatbelt_result
from pipeline import _config_for_source, suppress_duplicate_events
from scripts.zone_report import crossed_horizontal, summarize_candidate


def test_seatbelt_is_disabled_for_non_front_or_unknown_camera():
    assert load_config({"camera": {"camera_view": "side_or_rear", "check_seatbelt": True}}).camera.check_seatbelt is False
    assert load_config({"camera": {"camera_view": "unknown", "check_seatbelt": True}}).camera.check_seatbelt is False
    assert load_config({"camera": {"camera_view": "front", "check_seatbelt": True}}).camera.check_seatbelt is True


def test_pipeline_loads_video_specific_camera_config():
    config = _config_for_source(load_config(), "data/videos/test_road.mp4")
    assert config.camera.id == "test_road"
    assert config.camera.camera_view == "side_or_rear"
    assert config.camera.check_seatbelt is False
    assert config.camera.zone == [(0.0, 0.8), (1.0, 0.8)]


def test_no_seatbelt_guard_rejects_small_front_crop():
    result = guard_no_seatbelt_result(
        SeatbeltResult("no_seatbelt", .95, "OK"),
        camera_view="front",
        crop_height=199,
    )
    assert (result.label, result.reason) == ("unclear", "UNVERIFIABLE_VIEW")


def test_no_seatbelt_guard_rejects_low_confidence_front_crop():
    result = guard_no_seatbelt_result(
        SeatbeltResult("no_seatbelt", .69, "OK"),
        camera_view="front",
        crop_height=240,
    )
    assert (result.label, result.reason) == ("unclear", "UNVERIFIABLE_VIEW")


def test_no_seatbelt_guard_accepts_confident_large_front_crop():
    result = guard_no_seatbelt_result(
        SeatbeltResult("no_seatbelt", .80, "OK"),
        camera_view="front",
        crop_height=220,
    )
    assert (result.label, result.reason, result.crop_height) == ("no_seatbelt", "OK", 220)


def test_duplicate_suppression_keeps_event_with_more_observations():
    common = {
        "camera_id": "cam",
        "vehicle_type": "motorcycle",
        "timestamp_sec": 1.0,
        "vehicle_box": [0, 0, 100, 100],
    }
    events = [
        {**common, "event_id": "short", "frame_idx": 10, "observations": 4},
        {**common, "event_id": "long", "frame_idx": 20, "observations": 12},
    ]
    kept, suppressed = suppress_duplicate_events(events)
    assert [event["event_id"] for event in kept] == ["long"]
    assert suppressed[0]["event_id"] == "short"
    assert suppressed[0]["suppressed_by"] == "long"


def test_duplicate_suppression_requires_all_matching_conditions():
    base = {
        "camera_id": "cam",
        "vehicle_type": "car",
        "timestamp_sec": 1.0,
        "vehicle_box": [0, 0, 100, 100],
        "observations": 5,
    }
    events = [
        {**base, "event_id": "camera", "frame_idx": 1},
        {**base, "event_id": "other-camera", "camera_id": "other", "frame_idx": 2},
        {**base, "event_id": "time", "timestamp_sec": 4.0, "frame_idx": 3},
        {**base, "event_id": "box", "vehicle_box": [300, 300, 400, 400], "frame_idx": 4},
    ]
    kept, suppressed = suppress_duplicate_events(events)
    assert len(kept) == 4
    assert suppressed == []


def test_horizontal_crossing_and_line_summary():
    assert crossed_horizontal(40, 60, 50)
    assert crossed_horizontal(60, 40, 50)
    assert not crossed_horizontal(20, 40, 50)
    records = {
        1: {"points": [(10, 40, 100), (10, 60, 140)]},
        2: {"points": [(10, 30, 200), (10, 60, 220)]},
        3: {"points": [(10, 30, 80), (10, 40, 90)]},
    }
    report = summarize_candidate(records, .5, 100)
    assert report["vehicles_crossing"] == 2
    assert report["median_crossing_height_px"] == 180
    assert report["crossing_vehicles_at_least_120px"] == 2
