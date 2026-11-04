"""Run driver-side seatbelt classification on images or a road video."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

import cv2
import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.association import Box
from ai_engine.seatbelt import (
    SeatbeltDetection,
    SeatbeltResult,
    car_driver_crop,
    seatbelt_result,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
DEFAULT_SEATBELT_MODEL = ROOT / "models" / "seatbelt" / "seatbelt_v1.pt"
DEFAULT_VEHICLE_MODEL = ROOT / "models" / "pretrained" / "yolo26n.pt"
COLORS = {
    "seatbelt": (40, 220, 40),
    "no_seatbelt": (40, 50, 240),
    "unclear": (0, 220, 255),
}


def collect_images(inputs: list[Path]) -> list[Path]:
    images = []
    for path in inputs:
        if path.is_dir():
            images.extend(
                image
                for image in path.rglob("*")
                if image.is_file() and image.suffix.lower() in IMAGE_EXTENSIONS
            )
        elif path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)
        else:
            raise FileNotFoundError(f"Image file or directory not found: {path}")
    if not images:
        raise FileNotFoundError("No supported images were found.")
    return sorted(set(images))


def get_seatbelt_detections(model: YOLO, crop, imgsz: int) -> list[SeatbeltDetection]:
    result = model.predict(crop, imgsz=imgsz, verbose=False)[0]
    detections = []
    if result.boxes is None:
        return detections
    for box in result.boxes:
        class_id = int(box.cls[0].item())
        name = str(result.names[class_id]).strip().lower().replace("-", "_").replace(" ", "_")
        if name not in ("seatbelt", "no_seatbelt"):
            continue
        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
        detections.append(
            SeatbeltDetection(
                Box(x1, y1, x2, y2),
                name,
                float(box.conf[0].item()),
            )
        )
    return detections


def draw_car_result(
    frame,
    car_box: Box,
    crop_box: Box | None,
    result: SeatbeltResult,
    debug: bool,
) -> None:
    label = {
        "seatbelt": "SEATBELT",
        "no_seatbelt": "NO SEATBELT",
        "unclear": "UNCLEAR",
    }[result.label]
    text = f"{label} {result.confidence:.2f}"
    if debug:
        text += f" ({result.reason})"
    color = COLORS[result.label]
    x1, y1, x2, y2 = (int(value) for value in (car_box.x1, car_box.y1, car_box.x2, car_box.y2))
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    if crop_box is not None:
        x1, y1 = int(crop_box.x1), int(crop_box.y1)
    text_x = max(0, min(x1, frame.shape[1] - 1))
    text_y = max(20, min(y1 - 5, frame.shape[0] - 5))
    cv2.putText(
        frame,
        text,
        (text_x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )


def process_frame(
    frame,
    vehicle_model: YOLO,
    seatbelt_model: YOLO,
    *,
    driver_side: str,
    min_height: int,
    imgsz: int,
    debug_counts: Counter,
    debug: bool,
    no_seatbelt_confidence: float = 0.40,
    save_no_seatbelt_dir: Path | None = None,
    save_no_seatbelt_limit: int = 6,
):
    output = frame.copy()
    result = vehicle_model.predict(
        frame,
        classes=[2],
        imgsz=imgsz,
        verbose=False,
    )[0]
    if result.boxes is None:
        return output
    for vehicle in result.boxes:
        debug_counts["cars_seen"] += 1
        x1, y1, x2, y2 = (float(value) for value in vehicle.xyxy[0].tolist())
        car_box = Box(x1, y1, x2, y2)
        crop_box = car_driver_crop(car_box, driver_side, min_height)
        if crop_box is None:
            debug_counts["reason:TOO_SMALL"] += 1
            draw_car_result(
                output,
                car_box,
                None,
                SeatbeltResult("unclear", 0.0, "TOO_SMALL"),
                debug,
            )
            continue
        left, top, right, bottom = (
            max(0, int(crop_box.x1)),
            max(0, int(crop_box.y1)),
            min(frame.shape[1], int(crop_box.x2)),
            min(frame.shape[0], int(crop_box.y2)),
        )
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            debug_counts["reason:TOO_SMALL"] += 1
            continue
        debug_counts["crops_made"] += 1
        detections = get_seatbelt_detections(seatbelt_model, crop, imgsz)
        detections = [
            detection for detection in detections
            if detection.label != "no_seatbelt" or detection.confidence >= no_seatbelt_confidence
        ]
        local_crop = Box(0, 0, crop.shape[1], crop.shape[0])
        decision = seatbelt_result(detections, local_crop, min_confidence=0.40)
        debug_counts[f"reason:{decision.reason}"] += 1
        if decision.reason == "OK":
            debug_counts[f"ok:{decision.label}"] += 1
        if (decision.reason == "OK" and decision.label == "no_seatbelt"
                and save_no_seatbelt_dir is not None
                and debug_counts["no_seatbelt_crops_saved"] < save_no_seatbelt_limit):
            save_no_seatbelt_dir.mkdir(parents=True, exist_ok=True)
            crop_path = save_no_seatbelt_dir / f"frame_{debug_counts['cars_seen']:07d}_no_seatbelt.jpg"
            cv2.imwrite(str(crop_path), crop)
            debug_counts["no_seatbelt_crops_saved"] += 1

        for detection in detections:
            dx1, dy1, dx2, dy2 = (
                int(detection.box.x1 + left),
                int(detection.box.y1 + top),
                int(detection.box.x2 + left),
                int(detection.box.y2 + top),
            )
            cv2.rectangle(
                output,
                (dx1, dy1),
                (dx2, dy2),
                COLORS[detection.label],
                2,
            )
        draw_car_result(output, car_box, crop_box, decision, debug)
    return output


def process_driver_image(frame, seatbelt_model: YOLO, *, imgsz: int, debug_counts: Counter):
    """Classify a supplied driver-focused image without needing a car detector."""
    debug_counts["cars_seen"] += 1
    debug_counts["crops_made"] += 1
    height, width = frame.shape[:2]
    detections = get_seatbelt_detections(seatbelt_model, frame, imgsz)
    decision = seatbelt_result(
        detections,
        Box(0, 0, width, height),
        min_confidence=0.40,
    )
    debug_counts[f"reason:{decision.reason}"] += 1
    output = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = (int(value) for value in (
            detection.box.x1,
            detection.box.y1,
            detection.box.x2,
            detection.box.y2,
        ))
        cv2.rectangle(output, (x1, y1), (x2, y2), COLORS[detection.label], 2)
    draw_car_result(
        output,
        Box(0, 0, width - 1, height - 1),
        Box(0, 0, width - 1, height - 1),
        decision,
        False,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--images", nargs="+", type=Path, help="Image files or directories.")
    source.add_argument("--video", type=Path, help="Input video.")
    parser.add_argument("--model", type=Path, default=DEFAULT_SEATBELT_MODEL)
    parser.add_argument("--vehicle-model", type=Path, default=DEFAULT_VEHICLE_MODEL)
    parser.add_argument("--driver-side", choices=("left", "right"), default="right")
    parser.add_argument("--min-height", type=int, default=120)
    parser.add_argument("--no-seatbelt-conf", type=float, default=0.40)
    parser.add_argument("--save-no-seatbelt-crops", type=Path)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--output-width", type=int, default=960)
    parser.add_argument(
        "--save",
        nargs="?",
        const=None,
        type=Path,
        help="Save output images to a folder or video to a file.",
    )
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if not args.model.is_file():
        raise FileNotFoundError(f"Seatbelt model not found: {args.model}")
    if not args.vehicle_model.is_file():
        raise FileNotFoundError(f"Vehicle model not found: {args.vehicle_model}")
    device = "GPU" if torch.cuda.is_available() else "CPU"
    print(f"Device: {device}")
    seatbelt_model = YOLO(str(args.model))
    debug_counts: Counter[str] = Counter()

    save_path = args.save
    if args.video:
        vehicle_model = YOLO(str(args.vehicle_model))
        if not args.video.is_file():
            raise FileNotFoundError(f"Video not found: {args.video}")
        if save_path is None:
            save_path = ROOT / "data" / "output" / "s4_seatbelt_demo.mp4"
        capture = cv2.VideoCapture(str(args.video))
        if not capture.isOpened():
            capture.release()
            raise SystemExit(f"Could not open video: {args.video}")
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        scale = min(1.0, args.output_width / width) if width else 1.0
        output_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        writer = None
        if save_path is not None:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(
                str(save_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps if fps > 0 else 30.0,
                output_size,
            )
            if not writer.isOpened():
                capture.release()
                raise SystemExit(f"Could not create output video: {save_path}")
        frame_count = 0
        try:
            while True:
                success, frame = capture.read()
                if not success:
                    break
                output = process_frame(
                    frame,
                    vehicle_model,
                    seatbelt_model,
                    driver_side=args.driver_side,
                    min_height=args.min_height,
                    imgsz=args.imgsz,
                    debug_counts=debug_counts,
                    debug=args.debug,
                    no_seatbelt_confidence=args.no_seatbelt_conf,
                    save_no_seatbelt_dir=args.save_no_seatbelt_crops,
                )
                if output_size != (width, height):
                    output = cv2.resize(output, output_size, interpolation=cv2.INTER_AREA)
                if writer is not None:
                    writer.write(output)
                if not args.no_show:
                    cv2.imshow("Stage 4 - Seatbelt demo (press q to quit)", output)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                frame_count += 1
        finally:
            capture.release()
            if writer is not None:
                writer.release()
            if not args.no_show:
                cv2.destroyAllWindows()
        print(f"Frames processed: {frame_count}")
        if writer is not None:
            print(f"Saved video: {save_path}")
    else:
        images = collect_images(args.images)
        if save_path is None:
            save_path = ROOT / "data" / "output" / "s4_seatbelt_images"
        save_path.mkdir(parents=True, exist_ok=True)
        for index, image_path in enumerate(images, 1):
            frame = cv2.imread(str(image_path))
            if frame is None:
                raise OSError(f"Could not read image: {image_path}")
            output = process_driver_image(
                frame,
                seatbelt_model,
                imgsz=args.imgsz,
                debug_counts=debug_counts,
            )
            if args.output_width > 0 and output.shape[1] > args.output_width:
                scale = args.output_width / output.shape[1]
                output = cv2.resize(
                    output,
                    (args.output_width, round(output.shape[0] * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            output_path = save_path / f"{index:04d}_{image_path.name}"
            if not cv2.imwrite(str(output_path), output):
                raise OSError(f"Could not save result image: {output_path}")
            if not args.no_show:
                cv2.imshow("Stage 4 - Seatbelt demo (press q to quit)", output)
                if cv2.waitKey(0) & 0xFF == ord("q"):
                    break
        if not args.no_show:
            cv2.destroyAllWindows()
        print(f"Images processed: {index}")
        print(f"Saved images: {save_path}")

    if args.debug:
        print("Debug summary:")
        for key in ("cars_seen", "crops_made"):
            print(f"  {key}: {debug_counts[key]}")
        print("  reason histogram:")
        for reason in ("OK", "LOW_CONF", "NO_DRIVER", "TOO_SMALL"):
            print(f"    {reason}: {debug_counts[f'reason:{reason}']}")
        print("  OK class counts:")
        for label in ("seatbelt", "no_seatbelt", "unclear"):
            print(f"    {label}: {debug_counts[f'ok:{label}']}")
        if args.save_no_seatbelt_crops:
            print(f"  no_seatbelt crops saved: {debug_counts['no_seatbelt_crops_saved']}")


if __name__ == "__main__":
    main()
