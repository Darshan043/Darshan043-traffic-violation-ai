"""Extract the Indian driver-side upper crop from detected cars in a video."""
from __future__ import annotations

import argparse
import heapq
from pathlib import Path
import sys

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.association import Box
from ai_engine.seatbelt import car_driver_crop

DEFAULT_OUTPUT = ROOT / "data" / "car_crops"
DEFAULT_MODEL = ROOT / "models" / "pretrained" / "yolo26n.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "data" / "videos" / "test_road.mp4")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip", type=int, default=1, help="Detect every Nth frame.")
    parser.add_argument("--min-height", type=int, default=120)
    parser.add_argument("--conf", type=float, default=0.30, help="Use the same detection confidence with and without tracking.")
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float)
    parser.add_argument("--driver-side", choices=("left", "right"), default="right")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--use-tracker", action="store_true", help="Keep only the best crops per track ID")
    parser.add_argument("--per-track", type=int, default=3)
    parser.add_argument("--min-frame-gap", type=int, default=15,
                        help="Minimum separation between selected crops from one track")
    parser.add_argument("--tracker", type=Path, default=ROOT / "ai_engine" / "config" / "botsort_traffic.yaml")
    args = parser.parse_args()
    if args.skip < 1:
        parser.error("--skip must be positive.")
    if args.per_track < 1:
        parser.error("--per-track must be positive.")
    if args.min_frame_gap < 0:
        parser.error("--min-frame-gap must not be negative.")
    if args.start_sec < 0 or (args.end_sec is not None and args.end_sec <= args.start_sec):
        parser.error("--end-sec must be greater than --start-sec")
    if not args.video.is_file():
        raise FileNotFoundError(f"Video does not exist: {args.video}")
    if not args.model.is_file():
        raise FileNotFoundError(f"Vehicle model does not exist: {args.model}")
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"Could not open video: {args.video}")
    model = YOLO(str(args.model))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(args.start_sec * fps)
    end_frame = int(args.end_sec * fps) if args.end_sec is not None else None
    args.out.mkdir(parents=True, exist_ok=True)
    frame_number = cars_seen = crops_saved = small_cars = 0
    candidates: dict[int, list[tuple[float, int, object]]] = {}
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number < start_frame:
                frame_number += 1
                continue
            if end_frame is not None and frame_number >= end_frame:
                break
            if frame_number % args.skip == 0:
                if args.use_tracker:
                    result = model.track(frame, persist=True, tracker=str(args.tracker), classes=[2],
                                         conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
                else:
                    result = model.predict(frame, classes=[2], conf=args.conf,
                                            imgsz=args.imgsz, verbose=False)[0]
                if result.boxes is not None:
                    for index, box in enumerate(result.boxes):
                        track_id = None
                        if args.use_tracker:
                            if box.id is None:
                                continue
                            track_id = int(box.id.item())
                        cars_seen += 1
                        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                        crop_box = car_driver_crop(
                            Box(x1, y1, x2, y2),
                            args.driver_side,
                            min_height=args.min_height,
                        )
                        if crop_box is None:
                            small_cars += 1
                            continue
                        left, top, right, bottom = (
                            max(0, int(crop_box.x1)),
                            max(0, int(crop_box.y1)),
                            min(frame.shape[1], int(crop_box.x2)),
                            min(frame.shape[0], int(crop_box.y2)),
                        )
                        crop = frame[top:bottom, left:right]
                        if crop.size == 0:
                            continue
                        if args.use_tracker:
                            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
                            area = crop.shape[0] * crop.shape[1]
                            score = (area ** 0.5) * sharpness
                            bucket = candidates.setdefault(track_id, [])
                            item = (score, frame_number, crop.copy())
                            pool_size = max(args.per_track * 10, 50)
                            if len(bucket) < pool_size:
                                heapq.heappush(bucket, item)
                            elif score > bucket[0][0]:
                                heapq.heapreplace(bucket, item)
                        else:
                            output = args.out / f"frame_{frame_number:06d}_car_{index:02d}.jpg"
                            if not cv2.imwrite(str(output), crop):
                                raise OSError(f"Could not save crop: {output}")
                            crops_saved += 1
            frame_number += 1
    finally:
        capture.release()
    if args.use_tracker:
        for track_id, bucket in sorted(candidates.items()):
            selected = []
            for candidate in sorted(bucket, reverse=True):
                _, source_frame, _ = candidate
                if all(abs(source_frame - prior[1]) >= args.min_frame_gap for prior in selected):
                    selected.append(candidate)
                if len(selected) >= args.per_track:
                    break
            for rank, (_, source_frame, crop) in enumerate(selected, 1):
                output = args.out / f"track_{track_id:06d}_rank_{rank}_frame_{source_frame:06d}.jpg"
                if not cv2.imwrite(str(output), crop):
                    raise OSError(f"Could not save crop: {output}")
                crops_saved += 1
    print(f"Frames read: {frame_number}")
    print(f"Cars seen: {cars_seen}")
    print(f"Cars below minimum height: {small_cars}")
    print(f"Crops saved: {crops_saved} to {args.out}")
    if args.use_tracker:
        print(f"Tracks with crops: {len(candidates)}; maximum crops per track: {args.per_track}")


if __name__ == "__main__":
    main()
