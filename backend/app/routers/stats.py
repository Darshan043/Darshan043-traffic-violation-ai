"""Statistics endpoints: summary, daily trends, and camera compliance."""
from __future__ import annotations

from collections import defaultdict
from fastapi import APIRouter, Depends

from backend.app.db.repository import Repository
from backend.app.deps import get_repository, require_role
from backend.app.models.stats import CameraStat, DailyStat, StatsSummary
from backend.app.models.user import User

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _calculate_compliance_percentage(compliant: int, violations: int) -> float:
    denominator = compliant + violations
    if denominator == 0:
        return 100.0
    return round((compliant / denominator) * 100.0, 2)


@router.get("/summary", response_model=StatsSummary)
def get_stats_summary(
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> StatsSummary:
    aggregate = getattr(repo, "get_stats_summary", None)
    if aggregate is not None:
        return StatsSummary(**aggregate())

    events = repo.list_vehicle_events()
    violations_list, _ = repo.list_violations(limit=100000)

    total_vehicles = len(events)
    compliant_vehicles = sum(1 for e in events if e.result in ("HELMET", "SEATBELT"))
    violations_count = sum(1 for e in events if e.result in ("NO_HELMET", "NO_SEATBELT"))
    needs_review = sum(1 for e in events if e.result == "NEEDS_REVIEW")

    reviewed_count = sum(1 for v in violations_list if v.review_status == "REVIEWED")
    unreviewed_count = sum(1 for v in violations_list if v.review_status == "UNREVIEWED")

    pct = _calculate_compliance_percentage(compliant_vehicles, violations_count)

    return StatsSummary(
        total_vehicles=total_vehicles,
        compliant_vehicles=compliant_vehicles,
        violations=violations_count,
        needs_review=needs_review,
        compliance_percentage=pct,
        reviewed_count=reviewed_count,
        unreviewed_count=unreviewed_count,
        helmet_compliance_percentage=_calculate_compliance_percentage(
            sum(1 for e in events if e.result == "HELMET"),
            sum(1 for e in events if e.result == "NO_HELMET"),
        ),
        seatbelt_compliance_percentage=_calculate_compliance_percentage(
            sum(1 for e in events if e.result == "SEATBELT"),
            sum(1 for e in events if e.result == "NO_SEATBELT"),
        ),
        review_count=needs_review,
    )


@router.get("/daily", response_model=list[DailyStat])
def get_daily_stats(
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> list[DailyStat]:
    aggregate = getattr(repo, "get_stats_daily", None)
    if aggregate is not None:
        return [DailyStat(**row) for row in aggregate()]

    events = repo.list_vehicle_events()
    daily_groups: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "compliant": 0, "violations": 0, "needs_review": 0})

    for e in events:
        day = e.created_at[:10] if len(e.created_at) >= 10 else "unknown"
        daily_groups[day]["total"] += 1
        if e.result in ("HELMET", "SEATBELT"):
            daily_groups[day]["compliant"] += 1
        elif e.result in ("NO_HELMET", "NO_SEATBELT"):
            daily_groups[day]["violations"] += 1
        elif e.result == "NEEDS_REVIEW":
            daily_groups[day]["needs_review"] += 1

    stats = []
    for day in sorted(daily_groups.keys(), reverse=True):
        grp = daily_groups[day]
        stats.append(DailyStat(
            date=day,
            total_vehicles=grp["total"],
            compliant_vehicles=grp["compliant"],
            violations=grp["violations"],
            needs_review=grp["needs_review"],
            compliance_percentage=_calculate_compliance_percentage(grp["compliant"], grp["violations"]),
        ))
    return stats


@router.get("/cameras", response_model=list[CameraStat])
def get_camera_stats(
    _: User = Depends(require_role("admin", "reviewer", "viewer")),
    repo: Repository = Depends(get_repository),
) -> list[CameraStat]:
    aggregate = getattr(repo, "get_stats_per_camera", None)
    if aggregate is not None:
        return [CameraStat(**row) for row in aggregate()]

    events = repo.list_vehicle_events()
    cameras = {c.camera_id: c.name for c in repo.list_cameras()}

    cam_groups: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "compliant": 0, "violations": 0, "needs_review": 0})
    for e in events:
        cid = e.camera_id
        cam_groups[cid]["total"] += 1
        if e.result in ("HELMET", "SEATBELT"):
            cam_groups[cid]["compliant"] += 1
        elif e.result in ("NO_HELMET", "NO_SEATBELT"):
            cam_groups[cid]["violations"] += 1
        elif e.result == "NEEDS_REVIEW":
            cam_groups[cid]["needs_review"] += 1

    stats = []
    for cid, grp in cam_groups.items():
        name = cameras.get(cid, cid)
        stats.append(CameraStat(
            camera_id=cid,
            camera_name=name,
            total_vehicles=grp["total"],
            compliant_vehicles=grp["compliant"],
            violations=grp["violations"],
            needs_review=grp["needs_review"],
            compliance_percentage=_calculate_compliance_percentage(grp["compliant"], grp["violations"]),
        ))
    return stats
