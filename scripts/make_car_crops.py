"""Extract the Indian driver-side upper crop from detected cars in a video."""
from __future__ import annotations

import argparse
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
    parser.add_argument("--driver-side", choices=("left", "right"), default="right")
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()
    if args.skip < 1:
        parser.error("--skip must be positive.")
    if not args.video.is_file():
        raise FileNotFoundError(f"Video does not exist: {args.video}")
    if not args.model.is_file():
        raise FileNotFoundError(f"Vehicle model does not exist: {args.model}")
    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"Could not open video: {args.video}")
    model = YOLO(str(args.model))
    args.out.mkdir(parents=True, exist_ok=True)
    frame_number = cars_seen = crops_saved = small_cars = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame_number % args.skip == 0:
                result = model.predict(
                    frame, classes=[2], imgsz=args.imgsz, verbose=False
                )[0]
                if result.boxes is not None:
                    for index, box in enumerate(result.boxes):
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
                        output = args.out / f"frame_{frame_number:06d}_car_{index:02d}.jpg"
                        if not cv2.imwrite(str(output), crop):
                            raise OSError(f"Could not save crop: {output}")
                        crops_saved += 1
            frame_number += 1
    finally:
        capture.release()
    print(f"Frames read: {frame_number}")
    print(f"Cars seen: {cars_seen}")
    print(f"Cars below minimum height: {small_cars}")
    print(f"Crops saved: {crops_saved} to {args.out}")


if __name__ == "__main__":
    main()
