import argparse
from collections import Counter, deque
from pathlib import Path
import time

import cv2
import torch
from ultralytics import YOLO


VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PRETRAINED_DIR = Path("models/pretrained")
DEFAULT_OUTPUT = Path("data/output/s2_output.mp4")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect cars, motorcycles, buses, and trucks in a video."
    )
    parser.add_argument(
        "--video",
        type=Path,
        default=Path("data/videos/test_road.mp4"),
        help="Input video (default: data/videos/test_road.mp4).",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=PRETRAINED_DIR / "yolo26n.pt",
        help="YOLO weights file (default: models/pretrained/yolo26n.pt).",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.35,
        help="Minimum detection confidence, from 0 to 1 (default: 0.35).",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="YOLO input image size (default: 640).",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=1,
        help="Run detection on every Nth frame (default: 1).",
    )
    parser.add_argument(
        "--save",
        nargs="?",
        const=DEFAULT_OUTPUT,
        default=None,
        type=Path,
        metavar="PATH",
        help="Save annotated video (default path: data/output/s2_output.mp4).",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open a display window.",
    )
    args = parser.parse_args()
    if not 0 <= args.conf <= 1:
        parser.error("--conf must be between 0 and 1.")
    if args.imgsz < 1:
        parser.error("--imgsz must be a positive integer.")
    if args.skip < 1:
        parser.error("--skip must be a positive integer.")
    return args


def resolve_model_path(model_path: Path) -> Path:
    if not model_path.is_absolute() and model_path.parent == Path("."):
        return PRETRAINED_DIR / model_path
    return model_path


def load_model(model_path: Path) -> tuple[YOLO, Path]:
    model_path = resolve_model_path(model_path)
    try:
        return YOLO(str(model_path)), model_path
    except Exception as error:
        if model_path.name.lower() != "yolo26n.pt":
            raise SystemExit(f"Could not load model {model_path}: {error}") from error

        fallback_path = PRETRAINED_DIR / "yolo11n.pt"
        print(
            f"Could not load yolo26n.pt ({error}). "
            "Falling back to models/pretrained/yolo11n.pt."
        )
        try:
            return YOLO(str(fallback_path)), fallback_path
        except Exception as fallback_error:
            raise SystemExit(
                f"Could not load fallback model {fallback_path}: {fallback_error}"
            ) from fallback_error


def main() -> None:
    args = parse_args()
    if not args.video.is_file():
        raise SystemExit(f"Video file does not exist: {args.video}")

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"Could not open video: {args.video}")

    writer = None
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video_fps = capture.get(cv2.CAP_PROP_FPS)
        if width <= 0 or height <= 0:
            raise SystemExit(f"Video has invalid dimensions: {args.video}")

        model, model_path = load_model(args.model)
        print(f"Model: {model_path}")
        print(f"Device: {'GPU' if torch.cuda.is_available() else 'CPU'}")
        print(f"Video: {args.video} ({width}x{height}, {video_fps:g} FPS)")

        if args.save is not None:
            args.save.parent.mkdir(parents=True, exist_ok=True)
            writer = cv2.VideoWriter(
                str(args.save),
                cv2.VideoWriter_fourcc(*"mp4v"),
                video_fps if video_fps > 0 else 30.0,
                (width, height),
            )
            if not writer.isOpened():
                raise SystemExit(f"Could not create output video: {args.save}")

        detections = Counter()
        inference_times = deque(maxlen=30)
        frames_read = 0
        frames_processed = 0
        total_inference_seconds = 0.0
        start_time = time.perf_counter()

        while True:
            success, frame = capture.read()
            if not success:
                break

            frame_number = frames_read
            frames_read += 1
            display_frame = frame.copy()

            if frame_number % args.skip == 0:
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                inference_start = time.perf_counter()
                result = model.predict(
                    frame,
                    classes=list(VEHICLE_CLASSES),
                    conf=args.conf,
                    imgsz=args.imgsz,
                    verbose=False,
                )[0]
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                inference_seconds = time.perf_counter() - inference_start
                total_inference_seconds += inference_seconds
                inference_times.append(inference_seconds)
                frames_processed += 1

                if result.boxes is not None:
                    for box in result.boxes:
                        class_id = int(box.cls[0].item())
                        confidence = float(box.conf[0].item())
                        if class_id not in VEHICLE_CLASSES:
                            continue
                        detections[class_id] += 1
                        x1, y1, x2, y2 = (
                            int(value) for value in box.xyxy[0].tolist()
                        )
                        label = f"{VEHICLE_CLASSES[class_id]} {confidence:.2f}"
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        (text_width, text_height), baseline = cv2.getTextSize(
                            label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2
                        )
                        label_x = min(max(x1, 0), max(width - text_width, 0))
                        label_y = min(
                            max(y1 - 8, text_height + baseline),
                            height - baseline,
                        )
                        cv2.putText(
                            display_frame,
                            label,
                            (label_x, label_y),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.6,
                            (0, 255, 0),
                            2,
                        )

            live_fps = len(inference_times) / sum(inference_times)
            cv2.putText(
                display_frame,
                f"FPS: {live_fps:.1f}",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            if writer is not None:
                writer.write(display_frame)
            if not args.no_show:
                cv2.imshow("Stage 2 - Vehicle detection (press q to quit)", display_frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

        elapsed = time.perf_counter() - start_time
        average_fps = (
            frames_processed / total_inference_seconds
            if total_inference_seconds > 0
            else 0.0
        )
        print("Detection summary:")
        print(f"Frames processed: {frames_processed} of {frames_read} read")
        print(f"Average FPS: {average_fps:.2f}")
        print(f"Elapsed seconds: {elapsed:.2f}")
        for class_id, class_name in VEHICLE_CLASSES.items():
            print(f"{class_name}: {detections[class_id]}")
        if args.save is not None:
            print(f"Saved video: {args.save}")
    finally:
        capture.release()
        if writer is not None:
            writer.release()
        if not args.no_show:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
