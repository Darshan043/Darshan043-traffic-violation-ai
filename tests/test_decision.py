from dataclasses import dataclass

import pytest

from ai_engine.association import HelmetResult
from ai_engine.decision import DecisionThresholds, decide, kind_of
from ai_engine.seatbelt import SeatbeltResult


@dataclass(frozen=True)
class FakeObs:
    label: str
    confidence: float
    reason: str = "OK"


def helmets(*pairs: tuple[str, float]) -> list[FakeObs]:
    return [FakeObs(label, confidence) for label, confidence in pairs]


def test_clear_helmet_detection_is_compliance():
    observations = helmets(("helmet", 0.90), ("helmet", 0.88), ("helmet", 0.92), ("helmet", 0.85))
    assert decide(observations, "helmet") == ("COMPLIANCE", "CLEAR_COMPLIANCE")


def test_clear_no_helmet_detection_is_violation():
    observations = helmets(
        ("no_helmet", 0.91),
        ("no_helmet", 0.87),
        ("no_helmet", 0.93),
        ("no_helmet", 0.89),
    )
    assert decide(observations, "helmet") == ("VIOLATION", "CLEAR_VIOLATION")


def test_conflicting_observations_need_review():
    observations = helmets(
        ("helmet", 0.90),
        ("no_helmet", 0.88),
        ("helmet", 0.86),
        ("no_helmet", 0.84),
    )
    assert decide(observations, "helmet") == ("NEEDS_REVIEW", "CONFLICTING_OBSERVATIONS")


def test_too_few_observations_need_review():
    observations = helmets(("no_helmet", 0.99), ("no_helmet", 0.98))
    assert decide(observations, "helmet") == ("NEEDS_REVIEW", "TOO_FEW_OBSERVATIONS")


def test_unclear_or_low_quality_observations_need_review():
    unclear = [
        HelmetResult("unclear", 0.0, "NO_HEAD"),
        HelmetResult("unclear", 0.0, "NO_RIDER"),
        HelmetResult("unclear", 0.0, "DRIVER_UNCLEAR"),
        HelmetResult("helmet", 0.92, "OK"),
    ]
    assert decide(unclear, "helmet") == ("NEEDS_REVIEW", "UNCLEAR_OBSERVATIONS")

    low_confidence = helmets(("no_helmet", 0.20), ("no_helmet", 0.22), ("no_helmet", 0.18))
    assert decide(low_confidence, "helmet") == ("NEEDS_REVIEW", "LOW_CONFIDENCE")


def test_clear_seatbelt_detection_is_compliance():
    observations = [
        SeatbeltResult("seatbelt", 0.91, "OK"),
        SeatbeltResult("seatbelt", 0.88, "OK"),
        SeatbeltResult("seatbelt", 0.86, "OK"),
        SeatbeltResult("seatbelt", 0.90, "OK"),
    ]
    assert decide(observations, "seatbelt") == ("COMPLIANCE", "CLEAR_COMPLIANCE")


def test_clear_no_seatbelt_detection_is_violation():
    observations = [
        SeatbeltResult("no_seatbelt", 0.84, "OK"),
        SeatbeltResult("no_seatbelt", 0.88, "OK"),
        SeatbeltResult("no_seatbelt", 0.90, "OK"),
        SeatbeltResult("no_seatbelt", 0.87, "OK"),
    ]
    assert decide(observations, "seatbelt") == ("VIOLATION", "CLEAR_VIOLATION")


def test_violation_threshold_is_higher_than_compliance():
    # 3 of 5 frames = 0.60. That is enough for compliance, but not for a violation.
    mixed_helmet = helmets(
        ("helmet", 0.90),
        ("helmet", 0.88),
        ("helmet", 0.86),
        ("unclear", 0.0),
        ("unclear", 0.0),
    )
    mixed_no_helmet = helmets(
        ("no_helmet", 0.90),
        ("no_helmet", 0.88),
        ("no_helmet", 0.86),
        ("unclear", 0.0),
        ("unclear", 0.0),
    )
    assert decide(mixed_helmet, "helmet") == ("COMPLIANCE", "CLEAR_COMPLIANCE")
    assert decide(mixed_no_helmet, "helmet") == ("NEEDS_REVIEW", "UNCLEAR_OBSERVATIONS")


def test_kind_of_maps_coco_ids_and_names():
    assert kind_of(3) == "helmet"
    assert kind_of("motorcycle") == "helmet"
    assert kind_of(2) == "seatbelt"
    assert kind_of("car") == "seatbelt"


def test_kind_of_rejects_unsupported_classes():
    with pytest.raises(ValueError):
        kind_of(5)


def test_invalid_thresholds_are_rejected():
    bad = DecisionThresholds(violation_threshold=0.50, compliance_threshold=0.60)
    with pytest.raises(ValueError):
        decide(helmets(("helmet", 0.9), ("helmet", 0.9), ("helmet", 0.9)), "helmet", bad)
