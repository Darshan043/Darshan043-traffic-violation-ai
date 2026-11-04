"""Dictionary-loaded settings for the Stage 6 engine.

Values start as a plain Python dict so the same layout can later be stored in
MongoDB without changing the dataclasses. Paths default to this project's
existing model and tracker files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ai_engine.decision import DecisionThresholds

ROOT = Path(__file__).resolve().parents[2]


def _as_path(value: str | Path, default: Path) -> Path:
    if value is None:
        return default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _as_points(value: object) -> list[tuple[float, float]]:
    if value is None:
        return [(0.0, 0.60), (1.0, 0.60)]
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
        numbers = [float(item) for item in parts]
        value = numbers
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("zone must be a list of points or a comma-separated x,y list")
    if isinstance(value[0], (int, float, str)):
        numbers = [float(item) for item in value]
        if len(numbers) % 2:
            raise ValueError("zone coordinate list must contain x,y pairs")
        points = list(zip(numbers[::2], numbers[1::2]))
    else:
        points = [(float(x), float(y)) for x, y in value]
    if len(points) < 2:
        raise ValueError("zone needs a line (2 points) or a polygon (3+ points)")
    return points


@dataclass
class CameraConfig:
    id: str = "cam1"
    check_helmet: bool = True
    check_seatbelt: bool = False
    camera_view: str = "unknown"
    motorcycle_view: str = "approaching"
    driver_side: str = "right"
    min_car_height: float = 120.0
    frame_skip: int = 1
    zone: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.60), (1.0, 0.60)])
    lost_near_distance: float = 40.0
    observe_distance: float = 250.0
    observe_every: int = 1
    min_motorcycle_width: float = 60.0
    vehicle_conf: float = 0.30
    helmet_conf: float = 0.40
    seatbelt_conf: float = 0.40
    imgsz: int = 640


@dataclass
class PathConfig:
    vehicle_model: Path = ROOT / "models" / "pretrained" / "yolo26n.pt"
    helmet_model: Path = ROOT / "models" / "helmet" / "helmet_v1.pt"
    seatbelt_model: Path = ROOT / "models" / "seatbelt" / "seatbelt_v1.pt"
    tracker: Path = ROOT / "ai_engine" / "config" / "botsort_conf_test.yaml"
    evidence_dir: Path = ROOT / "storage" / "evidence"


@dataclass
class EngineConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    thresholds: DecisionThresholds = field(default_factory=DecisionThresholds)
    paths: PathConfig = field(default_factory=PathConfig)
    accumulator_max_age: int = 120
    lost_grace_frames: int = 15
    transfer_time_gap: int = 15
    transfer_position_gap: float = 80.0
    start_sec: float = 0.0
    end_sec: float | None = None


def load_config(data: dict | None = None) -> EngineConfig:
    """Build an EngineConfig from a nested dictionary. Missing keys keep defaults."""
    raw = data or {}
    camera_raw = raw.get("camera", raw)
    configured_view = str(camera_raw.get("camera_view", "unknown"))
    legacy_motorcycle_view = configured_view if configured_view in ("approaching", "receding") else None
    camera_view = "unknown" if legacy_motorcycle_view else configured_view
    motorcycle_view = str(camera_raw.get("motorcycle_view", legacy_motorcycle_view or "approaching"))
    path_raw = raw.get("paths", {})
    threshold_raw = raw.get("thresholds", {})
    camera = CameraConfig(
        id=str(camera_raw.get("id", camera_raw.get("camera_id", "cam1"))),
        check_helmet=bool(camera_raw.get("check_helmet", True)),
        check_seatbelt=bool(camera_raw.get("check_seatbelt", False)) and camera_view == "front",
        camera_view=camera_view,
        motorcycle_view=motorcycle_view,
        driver_side=str(camera_raw.get("driver_side", "right")),
        min_car_height=float(camera_raw.get("min_car_height", 120)),
        frame_skip=int(camera_raw.get("frame_skip", camera_raw.get("skip", 1))),
        zone=_as_points(camera_raw.get("zone", raw.get("zone"))),
        lost_near_distance=float(camera_raw.get("lost_near_distance", 40)),
        observe_distance=float(camera_raw.get("observe_distance", 250)),
        observe_every=int(camera_raw.get("observe_every", 1)),
        min_motorcycle_width=float(camera_raw.get("min_motorcycle_width", 60)),
        vehicle_conf=float(camera_raw.get("vehicle_conf", 0.30)),
        helmet_conf=float(camera_raw.get("helmet_conf", 0.40)),
        seatbelt_conf=float(camera_raw.get("seatbelt_conf", 0.40)),
        imgsz=int(camera_raw.get("imgsz", 640)),
    )
    if camera.frame_skip < 1:
        raise ValueError("frame_skip must be at least 1")
    if camera.observe_every < 1:
        raise ValueError("observe_every must be at least 1")
    if camera.camera_view not in ("front", "side_or_rear", "unknown"):
        raise ValueError("camera_view must be 'front', 'side_or_rear', or 'unknown'")
    if camera.motorcycle_view not in ("approaching", "receding"):
        raise ValueError("motorcycle_view must be 'approaching' or 'receding'")
    if camera.driver_side not in ("left", "right"):
        raise ValueError("driver_side must be 'left' or 'right'")
    paths = PathConfig(
        vehicle_model=_as_path(path_raw.get("vehicle_model"), PathConfig.vehicle_model),
        helmet_model=_as_path(path_raw.get("helmet_model"), PathConfig.helmet_model),
        seatbelt_model=_as_path(path_raw.get("seatbelt_model"), PathConfig.seatbelt_model),
        tracker=_as_path(path_raw.get("tracker"), PathConfig.tracker),
        evidence_dir=_as_path(path_raw.get("evidence_dir"), PathConfig.evidence_dir),
    )
    thresholds = DecisionThresholds(**{**DecisionThresholds().__dict__, **threshold_raw})
    return EngineConfig(
        camera=camera,
        thresholds=thresholds,
        paths=paths,
        accumulator_max_age=int(raw.get("accumulator_max_age", 120)),
        lost_grace_frames=int(raw.get("lost_grace_frames", 15)),
        transfer_time_gap=int(raw.get("transfer_time_gap", 15)),
        transfer_position_gap=float(raw.get("transfer_position_gap", 80.0)),
        start_sec=float(raw.get("start_sec", 0.0)),
        end_sec=None if raw.get("end_sec") is None else float(raw["end_sec"]),
    )
