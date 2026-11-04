"""Multi-frame voting that turns observations into one final decision.

A single frame can be wrong: a helmet can look like a cap, or a seatbelt crop can
be blurry. Voting looks at several frames of the same vehicle and only confirms a
result when the evidence is strong enough.

A confirmed violation needs a higher vote share than confirmed compliance. That is
on purpose. A false "violation" can accuse a driver incorrectly. A false
"compliance" is still not ideal, but it is less harmful than a false accusation.
Unclear or thin evidence becomes NEEDS_REVIEW instead of a confirmed violation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

DecisionLabel = Literal["VIOLATION", "COMPLIANCE", "NEEDS_REVIEW"]
ReasonCode = Literal[
    "CLEAR_VIOLATION",
    "CLEAR_COMPLIANCE",
    "TOO_FEW_OBSERVATIONS",
    "CONFLICTING_OBSERVATIONS",
    "UNCLEAR_OBSERVATIONS",
    "LOW_CONFIDENCE",
]
ViolationKind = Literal["helmet", "seatbelt"]

HELMET_VIOLATION = "no_helmet"
HELMET_COMPLIANCE = "helmet"
SEATBELT_VIOLATION = "no_seatbelt"
SEATBELT_COMPLIANCE = "seatbelt"

_COCO_MOTORCYCLE = 3
_COCO_CAR = 2


@dataclass(frozen=True)
class DecisionThresholds:
    """Numbers that control how strict the vote is.

    These live in one place so later stages can load them from a dictionary
    (and later from MongoDB) instead of scattering magic numbers in the code.
    """

    min_observations: int = 3
    min_decisive_observations: int = 3
    # Share of *all* observations that must be violation labels.
    violation_threshold: float = 0.70
    # Share of *all* observations that must be compliance labels.
    # This is lower than violation_threshold on purpose.
    compliance_threshold: float = 0.55
    min_mean_confidence: float = 0.40
    # If both sides have at least this share of decisive votes, call it a conflict.
    conflict_share: float = 0.30


DEFAULT_THRESHOLDS = DecisionThresholds()


def kind_of(vehicle_class: int | str) -> ViolationKind:
    """Map a tracked vehicle class to the check the engine should run."""
    if vehicle_class in (_COCO_MOTORCYCLE, "motorcycle", "motorbike"):
        return "helmet"
    if vehicle_class in (_COCO_CAR, "car"):
        return "seatbelt"
    raise ValueError(
        f"Unsupported vehicle class {vehicle_class!r}; expected car or motorcycle"
    )


def _labels_for(kind: ViolationKind) -> tuple[str, str]:
    if kind == "helmet":
        return HELMET_VIOLATION, HELMET_COMPLIANCE
    if kind == "seatbelt":
        return SEATBELT_VIOLATION, SEATBELT_COMPLIANCE
    raise ValueError(f"Unknown violation kind {kind!r}")


def _bucket(observation: object, violation_label: str, compliance_label: str) -> str:
    """Put one observation into violation, compliance, or unclear."""
    label = str(getattr(observation, "label", "unclear")).strip().lower().replace(" ", "_")
    reason = str(getattr(observation, "reason", "OK"))
    if reason != "OK":
        return "unclear"
    if label == violation_label:
        return "violation"
    if label == compliance_label:
        return "compliance"
    return "unclear"


def _confidence(observation: object) -> float:
    value = float(getattr(observation, "confidence", 0.0))
    if not 0.0 <= value <= 1.0:
        raise ValueError("observation confidence must be between 0 and 1")
    return value


def decide(
    observations: Sequence[object],
    kind: ViolationKind,
    thresholds: DecisionThresholds | None = None,
) -> tuple[DecisionLabel, ReasonCode]:
    """Vote across frames and return (final decision, reason code).

    `observations` may be HelmetResult, SeatbeltResult, or any object with
    `label`, `confidence`, and optional `reason` attributes.
    """
    if kind not in ("helmet", "seatbelt"):
        raise ValueError("kind must be 'helmet' or 'seatbelt'")
    cfg = thresholds or DEFAULT_THRESHOLDS
    if cfg.violation_threshold <= cfg.compliance_threshold:
        raise ValueError("violation_threshold must be higher than compliance_threshold")
    if cfg.min_observations < 1 or cfg.min_decisive_observations < 1:
        raise ValueError("observation minimums must be at least 1")

    items = list(observations)
    if len(items) < cfg.min_observations:
        return "NEEDS_REVIEW", "TOO_FEW_OBSERVATIONS"

    violation_label, compliance_label = _labels_for(kind)
    buckets = [_bucket(item, violation_label, compliance_label) for item in items]
    n_total = len(buckets)
    n_violation = buckets.count("violation")
    n_compliance = buckets.count("compliance")
    n_unclear = buckets.count("unclear")
    n_decisive = n_violation + n_compliance

    if n_decisive < cfg.min_decisive_observations:
        return "NEEDS_REVIEW", "UNCLEAR_OBSERVATIONS"

    decisive_conf = [
        _confidence(item)
        for item, bucket in zip(items, buckets)
        if bucket in ("violation", "compliance")
    ]
    mean_conf = sum(decisive_conf) / len(decisive_conf)
    if mean_conf < cfg.min_mean_confidence:
        return "NEEDS_REVIEW", "LOW_CONFIDENCE"

    violation_share = n_violation / n_total
    compliance_share = n_compliance / n_total
    if n_decisive:
        minority_share = min(n_violation, n_compliance) / n_decisive
        if minority_share >= cfg.conflict_share and n_violation and n_compliance:
            return "NEEDS_REVIEW", "CONFLICTING_OBSERVATIONS"

    if violation_share >= cfg.violation_threshold:
        return "VIOLATION", "CLEAR_VIOLATION"
    if compliance_share >= cfg.compliance_threshold:
        return "COMPLIANCE", "CLEAR_COMPLIANCE"
    if n_violation and n_compliance:
        return "NEEDS_REVIEW", "CONFLICTING_OBSERVATIONS"
    if n_unclear:
        return "NEEDS_REVIEW", "UNCLEAR_OBSERVATIONS"
    return "NEEDS_REVIEW", "CONFLICTING_OBSERVATIONS"
