import pytest

from ai_engine.association import Box
from ai_engine.seatbelt import (
    SeatbeltDetection,
    car_driver_crop,
    seatbelt_result,
)


CAR = Box(100, 50, 500, 350)


def detection(label="seatbelt", confidence=0.9, box=Box(250, 80, 320, 160)):
    return SeatbeltDetection(box, label, confidence)


def test_right_driver_crop_is_upper_right_half():
    assert car_driver_crop(CAR, "right") == Box(300, 50, 500, 215)


def test_left_driver_crop_is_upper_left_half():
    assert car_driver_crop(CAR, "left") == Box(100, 50, 300, 215)


def test_too_small_car_has_no_driver_crop():
    assert car_driver_crop(Box(0, 0, 200, 119), "right") is None


def test_unknown_driver_side_is_rejected():
    with pytest.raises(ValueError):
        car_driver_crop(CAR, "center")


def test_seatbelt_detection_inside_driver_crop_is_ok():
    result = seatbelt_result([detection()], Box(200, 50, 400, 215))
    assert (result.label, result.confidence, result.reason) == ("seatbelt", 0.9, "OK")


def test_no_seatbelt_detection_inside_driver_crop_is_ok():
    result = seatbelt_result([detection("no_seatbelt", 0.82)], Box(200, 50, 400, 215))
    assert (result.label, result.confidence, result.reason) == ("no_seatbelt", 0.82, "OK")


def test_wrong_side_detection_is_ignored():
    passenger_detection = detection(box=Box(20, 80, 80, 150))
    result = seatbelt_result([passenger_detection], Box(100, 50, 200, 215))
    assert (result.label, result.reason) == ("unclear", "LOW_CONF")


def test_low_confidence_is_unclear():
    result = seatbelt_result([detection(confidence=0.2)], Box(200, 50, 400, 215))
    assert (result.label, result.confidence, result.reason) == ("unclear", 0.2, "LOW_CONF")


def test_absent_driver_is_unclear():
    result = seatbelt_result([detection()], Box(200, 50, 400, 215), driver_present=False)
    assert (result.label, result.reason) == ("unclear", "NO_DRIVER")


def test_missing_or_zero_size_crop_is_too_small():
    assert seatbelt_result([], None).reason == "TOO_SMALL"
    assert seatbelt_result([], Box(2, 2, 2, 10)).reason == "TOO_SMALL"
