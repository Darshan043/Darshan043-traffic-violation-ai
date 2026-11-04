"""Standalone Stage 6 violation pipeline orchestration."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from ai_engine.config import EngineConfig, load_config
from ai_engine.helmet_pipeline import process_motorcycles
from ai_engine.seatbelt_pipeline import process_cars

PipelineMode = Literal["helmet", "seatbelt", "both"]


def run_pipeline(
    source: str | Path,
    config: EngineConfig | None = None,
    *,
    mode: PipelineMode = "both",
    on_event: Callable[[dict[str, Any]], None] | None = None,
    on_frame: Callable[[str, int, Any], None] | None = None,
    on_transfer: Callable[[dict[str, Any]], None] | None = None,
    on_crossing: Callable[[dict[str, Any]], None] | None = None,
    on_track: Callable[[dict[str, Any]], None] | None = None,
    helmet_detector=None,
    seatbelt_detector=None,
) -> list[dict[str, Any]]:
    """Run the selected Stage 6 detectors over a video file or stream.

    The existing helmet and seatbelt processors retain ownership of their
    tracking, zone, voting, duplicate handling, overlays, and evidence logic.
    When both checks are requested, each processor runs independently over the
    source and reports its own annotated frames through `on_frame`.
    """
    if mode not in ("helmet", "seatbelt", "both"):
        raise ValueError("mode must be 'helmet', 'seatbelt', or 'both'")
    if config is None:
        config = load_config()
    if on_event is None:
        on_event = lambda event: None

    source_text = str(source)
    if not source_text.lower().startswith(("rtsp://", "http://", "https://")):
        if not Path(source_text).is_file():
            raise FileNotFoundError(f"Video file not found: {source_text}")

    events: list[dict[str, Any]] = []
    modes = ("helmet", "seatbelt") if mode == "both" else (mode,)
    for selected_mode in modes:
        run_config = load_config({
            "camera": {
                **config.camera.__dict__,
                "check_helmet": selected_mode == "helmet",
                "check_seatbelt": selected_mode == "seatbelt",
            },
            "thresholds": config.thresholds.__dict__,
            "paths": {
                "vehicle_model": config.paths.vehicle_model,
                "helmet_model": config.paths.helmet_model,
                "seatbelt_model": config.paths.seatbelt_model,
                "tracker": config.paths.tracker,
                "evidence_dir": config.paths.evidence_dir,
            },
            "accumulator_max_age": config.accumulator_max_age,
            "lost_grace_frames": config.lost_grace_frames,
            "start_sec": config.start_sec,
            "end_sec": config.end_sec,
        })

        def frame_callback(frame_idx: int, frame, selected=selected_mode) -> None:
            if on_frame is not None:
                on_frame(selected, frame_idx, frame)

        if selected_mode == "helmet":
            selected_events = process_motorcycles(
                source_text,
                run_config,
                on_event,
                detector=helmet_detector,
                on_frame=frame_callback if on_frame is not None else None,
                on_transfer=on_transfer,
                on_crossing=on_crossing,
                on_track=on_track,
            )
        else:
            selected_events = process_cars(
                source_text,
                run_config,
                on_event,
                detector=seatbelt_detector,
                on_frame=frame_callback if on_frame is not None else None,
                on_transfer=on_transfer,
                on_crossing=on_crossing,
                on_track=on_track,
            )
        events.extend(selected_events)

    return sorted(events, key=lambda event: (event.get("frame_idx", 0), event.get("vehicle_class", "")))
