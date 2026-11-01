import pytest

from ai_engine.association import Box, HeadDetection, driver_helmet_result


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
