import cv2
import numpy as np

from ai_engine.association import Box
from ai_engine.helmet_pipeline import _draw as draw_helmet
from ai_engine.seatbelt_pipeline import _draw as draw_seatbelt
from ai_engine.zone import Zone


def test_helmet_overlay_draws_zone_and_track_labels():
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    zone = Zone([(10, 90), (190, 90)], lost_near_distance=40)
    analysis = type(
        "Analysis",
        (),
        {
            "track": type("Track", (), {"id": 7, "box": Box(20, 30, 80, 90), "cls": 3})(),
            "result": type("Result", (), {"label": "no_helmet", "confidence": 0.91})(),
            "driver": Box(25, 35, 75, 85),
            "riders": (),
            "persons": (),
            "heads": (),
            "crop_box": Box(20, 30, 80, 90),
        },
    )()
    drawn = draw_helmet(frame.copy(), zone, [analysis], {})
    assert drawn.shape == frame.shape
    assert np.any(drawn[..., 1] > 0)


def test_seatbelt_overlay_draws_zone_and_track_labels():
    frame = np.zeros((120, 200, 3), dtype=np.uint8)
    zone = Zone([(20, 80), (180, 80)], lost_near_distance=50)
    analysis = type(
        "Analysis",
        (),
        {
            "track": type("Track", (), {"id": 8, "box": Box(30, 40, 120, 90), "cls": 2})(),
            "result": type("Result", (), {"label": "seatbelt", "confidence": 0.88})(),
            "driver_crop": Box(40, 40, 100, 75),
            "crop_box": Box(40, 40, 100, 75),
            "detections": (),
        },
    )()
    drawn = draw_seatbelt(frame.copy(), zone, [analysis], {})
    assert drawn.shape == frame.shape
    assert np.any(drawn[..., 2] > 0)
