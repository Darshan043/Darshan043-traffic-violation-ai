import pytest

from ai_engine.association import Box, HeadDetection, driver_helmet_result, riders_for_motorcycle
from scripts.s3_helmet_demo import crop_box_to_frame


MOTO = Box(0, 100, 200, 200)


def head_for(person, label="helmet", conf=.9):
    return HeadDetection(Box(person.x1 + 10, person.y1 + 5, person.x1 + 30, person.y1 + 25), label, conf)


def test_one_rider_with_helmet():
    rider = Box(20, 50, 80, 160)
    assert driver_helmet_result(MOTO, [rider], [head_for(rider)], "approaching").label == "helmet"


def test_one_rider_without_helmet():
    rider = Box(20, 50, 80, 160)
    result = driver_helmet_result(MOTO, [rider], [head_for(rider, "no_helmet", .82)], "approaching")
    assert (result.label, result.confidence) == ("no_helmet", .82)


@pytest.mark.parametrize("view", ["approaching", "receding"])
def test_helmeted_passenger_does_not_rescue_bareheaded_driver(view):
    upper, lower = Box(20, 50, 75, 130), Box(90, 65, 150, 185)
    driver = lower if view == "approaching" else upper
    passenger = upper if view == "approaching" else lower
    result = driver_helmet_result(MOTO, [upper, lower], [head_for(passenger), head_for(driver, "no_helmet")], view)
    assert result.label == "no_helmet"


def test_two_riders_with_almost_equal_height_are_unclear():
    a, b = Box(10, 60, 60, 160), Box(80, 61, 130, 165)
    result = driver_helmet_result(MOTO, [a, b], [head_for(a), head_for(b)], "approaching")
    assert (result.label, result.reason) == ("unclear", "DRIVER_UNCLEAR")


def test_no_head_found_is_unclear():
    rider = Box(20, 50, 80, 160)
    assert driver_helmet_result(MOTO, [rider], [], "approaching").reason == "NO_HEAD"


def test_no_person_is_unclear():
    assert driver_helmet_result(MOTO, [], [], "approaching").reason == "NO_RIDER"


def test_head_on_passenger_only_is_unclear():
    upper, lower = Box(20, 50, 75, 130), Box(90, 65, 150, 185)
    driver = lower  # approaching
    result = driver_helmet_result(MOTO, [upper, lower], [head_for(upper)], "approaching")
    assert (result.label, result.reason) == ("unclear", "NO_HEAD")


def test_motorcycle_rider_requires_at_least_half_person_inside_expanded_box():
    moto = Box(0, 100, 200, 200)  # expanded y range is 40..200
    exactly_half_inside = Box(10, 20, 30, 60)  # 20/40 px vertically inside
    less_than_half_inside = Box(50, 21, 70, 58)  # 18/37 px vertically inside
    assert riders_for_motorcycle(moto, [exactly_half_inside, less_than_half_inside]) == [exactly_half_inside]


def test_crop_head_box_is_scaled_and_offset_to_full_frame():
    crop_box = Box(20, 10, 60, 30)
    assert crop_box_to_frame(crop_box, crop_x=100, crop_y=50, scale=2) == Box(110, 55, 130, 65)
