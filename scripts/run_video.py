"""Run the standalone Stage 6 helmet and/or seatbelt pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.config import load_config
from pipeline import run_pipeline


def parse_zone(text: str) -> list[float]:
    try:
        numbers = [float(item.strip()) for item in text.replace(";", ",").split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError("zone coordinates must be numbers") from error
    if len(numbers) < 4 or len(numbers) % 2:
        raise argparse.ArgumentTypeError("zone must contain comma-separated x,y pairs")
    return numbers


def _is_url(source: str) -> bool:
    return source.lower().startswith(("rtsp://", "http://", "https://"))


def _video_stem(source: str) -> str:
    if _is_url(source):
        return "stream"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(source).stem) or "video"


def _source_fps(source: str, override: float | None) -> float:
    if override is not None:
        return override
    if _is_url(source):
        return 25.0
    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        capture.release()
        raise OSError(f"Could not open video to read FPS: {source}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    capture.release()
    return fps if fps > 0 else 25.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", "--video", dest="source",
        default=str(ROOT / "data" / "videos" / "helmet_test.mp4"),
        help="Video file path or RTSP/HTTP stream URL.",
    )
    parser.add_argument("--mode", choices=("helmet", "seatbelt", "both"), default="both")
    parser.add_argument(
        "--zone",
        type=parse_zone,
        default=[0.0, 0.90, 1.0, 0.90],
        help="Zone/crossing line as x,y pairs. Values in 0-1 are normalised.",
    )
    parser.add_argument("--camera-id", default="cam1")
    parser.add_argument("--camera-view", choices=("front", "side_or_rear", "unknown"), default="unknown")
    parser.add_argument("--motorcycle-view", choices=("approaching", "receding"), default="approaching")
    parser.add_argument("--driver-side", choices=("left", "right"), default="right")
    parser.add_argument("--skip", type=int, default=1)
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float)
    parser.add_argument("--observe-distance", type=float, default=400.0)
    parser.add_argument("--observe-every", type=int, default=1)
    parser.add_argument("--min-car-height", type=float, default=120.0)
    parser.add_argument("--vehicle-conf", type=float, default=0.30)
    parser.add_argument("--helmet-conf", type=float, default=0.40)
    parser.add_argument("--seatbelt-conf", type=float, default=0.40)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--save", action="store_true", help="Save annotated video output.")
    parser.add_argument("--no-show", action="store_true", help="Do not open a display window.")
    parser.add_argument("--out", type=Path, help="Annotated output video path.")
    parser.add_argument("--fps", type=float, help="Output video FPS override.")
    parser.add_argument("--json", type=Path, help="JSON event output path.")
    parser.add_argument("--vehicle-model", type=Path)
    parser.add_argument("--helmet-model", type=Path)
    parser.add_argument("--seatbelt-model", type=Path)
    parser.add_argument("--tracker", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--device", help="Computation device (e.g. 'cpu', '0').")
    args = parser.parse_args(argv)

    if args.skip < 1:
        parser.error("--skip must be at least 1")
    if args.observe_every < 1:
        parser.error("--observe-every must be at least 1")
    if args.scale <= 0:
        parser.error("--scale must be greater than 0")
    if args.fps is not None and args.fps <= 0:
        parser.error("--fps must be greater than 0")
    if not _is_url(args.source) and not Path(args.source).is_file():
        parser.error(f"video file does not exist: {args.source}")

    paths = {}
    for argument, key in (
        (args.vehicle_model, "vehicle_model"),
        (args.helmet_model, "helmet_model"),
        (args.seatbelt_model, "seatbelt_model"),
        (args.tracker, "tracker"),
        (args.evidence_dir, "evidence_dir"),
    ):
        if argument is not None:
            paths[key] = argument

    config = load_config({
        "camera": {
            "id": args.camera_id,
            "camera_view": args.camera_view,
            "motorcycle_view": args.motorcycle_view,
            "driver_side": args.driver_side,
            "frame_skip": args.skip,
            "zone": args.zone,
            "observe_distance": args.observe_distance,
            "observe_every": args.observe_every,
            "min_car_height": args.min_car_height,
            "vehicle_conf": args.vehicle_conf,
            "helmet_conf": args.helmet_conf,
            "seatbelt_conf": args.seatbelt_conf,
            "imgsz": args.imgsz,
            "device": args.device,
            "check_helmet": args.mode in ("helmet", "both"),
            "check_seatbelt": args.mode in ("seatbelt", "both"),
        },
        "paths": paths,
        "start_sec": args.start_sec,
        "end_sec": args.end_sec,
    })

    output_requested = args.save or args.out is not None
    fps = _source_fps(args.source, args.fps) if output_requested else 25.0
    stem = _video_stem(args.source)
    json_path = args.json or ROOT / "data" / "output" / f"s6_{stem}_{args.mode}_events.json"
    output_paths: dict[str, Path] = {}
    if output_requested:
        if args.mode == "both":
            base = args.out or ROOT / "data" / "output" / f"s6_{stem}_annotated.mp4"
            output_paths = {
                "helmet": base.with_name(f"{base.stem}_helmet{base.suffix or '.mp4'}"),
                "seatbelt": base.with_name(f"{base.stem}_seatbelt{base.suffix or '.mp4'}"),
            }
        else:
            output_paths[args.mode] = args.out or ROOT / "data" / "output" / f"s6_{stem}_{args.mode}.mp4"

    writers: dict[str, cv2.VideoWriter] = {}

    def on_frame(mode: str, frame_idx: int, frame) -> None:
        height, width = frame.shape[:2]
        size = (max(1, int(width * args.scale)), max(1, int(height * args.scale)))
        shown = cv2.resize(frame, size)
        if output_requested:
            writer = writers.get(mode)
            if writer is None:
                output_path = output_paths[mode]
                output_path.parent.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(
                    str(output_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    fps,
                    size,
                )
                if not writer.isOpened():
                    writer.release()
                    raise OSError(f"Could not create output video: {output_path}")
                writers[mode] = writer
            writer.write(shown)
        if not args.no_show:
            cv2.imshow(f"Stage 6 {mode}", shown)
            cv2.waitKey(1)

    try:
        print(
            f"Stage 6: source={args.source}; mode={args.mode}; camera={args.camera_id}; "
            f"zone={args.zone}; skip={args.skip}"
        )
        events = run_pipeline(
            args.source,
            config,
            mode=args.mode,
            on_frame=on_frame,
        )
    finally:
        for writer in writers.values():
            writer.release()
        if not args.no_show:
            cv2.destroyAllWindows()

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
    print(f"Events: {len(events)}")
    for event in events:
        print(
            f"EVENT camera={event['camera_id']} track={event['track_id']} "
            f"class={event['vehicle_class']} type={event['violation_type']} "
            f"decision={event['decision']} reason={event['reason']} "
            f"frame={event['frame_idx']} observations={event['observations']}"
        )
    print(f"Events JSON: {json_path}")
    for mode, output_path in output_paths.items():
        if output_path.exists():
            print(f"Annotated {mode} video: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
