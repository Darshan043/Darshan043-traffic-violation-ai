"""Evaluate the trained seatbelt detector on its held-out test split."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
CLASS_NAMES = {0: "seatbelt", 1: "no_seatbelt"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
COLORS = {0: (40, 220, 40), 1: (40, 50, 240)}


@dataclass(frozen=True)
class Prediction:
    class_id: int
    confidence: float
    box: tuple[float, float, float, float]


def read_ground_truth(label_path: Path, width: int, height: int) -> list[Prediction]:
    truth = []
    if not label_path.is_file():
        return truth
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if not fields:
            continue
        if len(fields) != 5:
            raise ValueError(f"Malformed test label: {label_path}:{line_number}")
        class_id = int(fields[0])
        x, y, box_width, box_height = map(float, fields[1:])
        if class_id not in CLASS_NAMES:
            raise ValueError(f"Unknown test class {class_id}: {label_path}:{line_number}")
        truth.append(
            Prediction(
                class_id,
                1.0,
                (
                    (x - box_width / 2) * width,
                    (y - box_height / 2) * height,
                    (x + box_width / 2) * width,
                    (y + box_height / 2) * height,
                ),
            )
        )
    return truth


def box_iou(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_left = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    area_right = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = area_left + area_right - intersection
    return intersection / union if union else 0.0


def class_scores(
    truth: list[Prediction],
    predictions: list[Prediction],
    class_id: int,
    confidence: float,
) -> tuple[int, int, int]:
    ground_truth = [item for item in truth if item.class_id == class_id]
    detections = sorted(
        (
            item
            for item in predictions
            if item.class_id == class_id and item.confidence >= confidence
        ),
        key=lambda item: item.confidence,
        reverse=True,
    )
    matched: set[int] = set()
    true_positives = false_positives = 0
    for detection in detections:
        available = [
            (box_iou(detection.box, target.box), index)
            for index, target in enumerate(ground_truth)
            if index not in matched
        ]
        best_iou, best_index = max(available, default=(0.0, -1))
        if best_iou >= 0.5:
            matched.add(best_index)
            true_positives += 1
        else:
            false_positives += 1
    return true_positives, false_positives, len(ground_truth) - len(matched)


def make_confusion_matrix(
    records: list[tuple[str, list[Prediction], list[Prediction]]],
    confidence: float,
) -> np.ndarray:
    background = len(CLASS_NAMES)
    matrix = np.zeros((background + 1, background + 1), dtype=np.int64)
    for _, truth, predictions in records:
        remaining_truth = set(range(len(truth)))
        for prediction in sorted(
            (item for item in predictions if item.confidence >= confidence),
            key=lambda item: item.confidence,
            reverse=True,
        ):
            matches = [
                (box_iou(prediction.box, truth[index].box), index)
                for index in remaining_truth
            ]
            overlap, index = max(matches, default=(0.0, -1))
            if overlap >= 0.5:
                matrix[truth[index].class_id, prediction.class_id] += 1
                remaining_truth.remove(index)
            else:
                matrix[background, prediction.class_id] += 1
        for index in remaining_truth:
            matrix[truth[index].class_id, background] += 1
    return matrix


def print_confusion_matrix(matrix: np.ndarray) -> None:
    labels = [CLASS_NAMES[index] for index in CLASS_NAMES] + ["background"]
    print("\nCONFUSION MATRIX at confidence 0.25, IoU 0.50 (rows=true, columns=predicted)")
    print(f"{'true \\\\ pred':<16}" + "".join(f"{label:>16}" for label in labels))
    for index, label in enumerate(labels):
        print(f"{label:<16}" + "".join(f"{value:16d}" for value in matrix[index]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "seatbelt" / "seatbelt_v1.pt")
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "seatbelt" / "data.yaml")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--conf", type=float, default=0.001)
    parser.add_argument("--preview-limit", type=int, default=12)
    args = parser.parse_args()
    if not args.model.is_file():
        raise FileNotFoundError(f"Trained model not found: {args.model}")
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    dataset_root = Path(config.get("path") or args.data.parent)
    if not dataset_root.is_absolute():
        dataset_root = (args.data.parent / dataset_root).resolve()
    test_image_dir = dataset_root / "images" / "test"
    test_label_dir = dataset_root / "labels" / "test"
    images = sorted(
        path
        for path in test_image_dir.glob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise FileNotFoundError(f"No test images found in {test_image_dir}")

    model = YOLO(str(args.model))
    metrics = model.val(
        data=str(args.data),
        split="test",
        imgsz=args.imgsz,
        batch=args.batch,
        workers=0,
        conf=args.conf,
        plots=True,
        project=str(ROOT / "runs" / "seatbelt_eval"),
        name="test",
        exist_ok=True,
    )
    box_metrics = metrics.box
    metric_indices = [int(value) for value in box_metrics.ap_class_index]
    print("\nTEST METRICS")
    print(f"{'class':<16}{'precision':>12}{'recall':>12}{'mAP50':>12}{'mAP50-95':>12}")
    for class_id, class_name in CLASS_NAMES.items():
        if class_id not in metric_indices:
            print(f"{class_name:<16}{'N/A':>12}{'N/A':>12}{'N/A':>12}{'N/A':>12}  (no test labels)")
            continue
        metric_index = metric_indices.index(class_id)
        p = float(box_metrics.p[metric_index])
        r = float(box_metrics.r[metric_index])
        ap50 = float(box_metrics.ap50[metric_index])
        ap = float(box_metrics.all_ap[metric_index].mean())
        print(f"{class_name:<16}{p:12.4f}{r:12.4f}{ap50:12.4f}{ap:12.4f}")
    print(
        "Note: per-class scores are not reliable when a test class has no ground-truth boxes."
    )

    records = []
    for image_path in images:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise OSError(f"Could not read test image: {image_path}")
        height, width = frame.shape[:2]
        truth = read_ground_truth(
            test_label_dir / f"{image_path.stem}.txt", width, height
        )
        result = model.predict(
            source=frame,
            imgsz=args.imgsz,
            conf=0.001,
            verbose=False,
        )[0]
        predicted = []
        if result.boxes is not None:
            for detection in result.boxes:
                class_id = int(detection.cls[0].item())
                if class_id not in CLASS_NAMES:
                    continue
                predicted.append(
                    Prediction(
                        class_id,
                        float(detection.conf[0].item()),
                        tuple(float(value) for value in detection.xyxy[0].tolist()),
                    )
                )
        records.append((image_path.name, truth, predicted))

    print_confusion_matrix(make_confusion_matrix(records, 0.25))
    print("\nCONFIDENCE TABLE (IoU 0.50)")
    print(f"{'confidence':<12}{'class':<16}{'precision':>12}{'recall':>12}{'TP':>8}{'FP':>8}{'FN':>8}")
    for threshold in (0.25, 0.40, 0.50):
        for class_id, class_name in CLASS_NAMES.items():
            tp = fp = fn = 0
            for _, truth, predicted in records:
                row_tp, row_fp, row_fn = class_scores(
                    truth, predicted, class_id, threshold
                )
                tp += row_tp
                fp += row_fp
                fn += row_fn
            precision = tp / (tp + fp) if tp + fp else None
            recall = tp / (tp + fn) if tp + fn else None
            p_text = f"{precision:.3f}" if precision is not None else "N/A"
            r_text = f"{recall:.3f}" if recall is not None else "N/A"
            print(
                f"{threshold:<12.2f}{class_name:<16}{p_text:>12}{r_text:>12}"
                f"{tp:8d}{fp:8d}{fn:8d}"
            )

    preview_dir = ROOT / "runs" / "seatbelt_eval" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    print("\nPLAIN-WORD TEST MISTAKES (confidence 0.25, IoU 0.50)")
    mistake_count = 0
    preview_count = 0
    for filename, truth, predicted in records:
        matched_truth: set[int] = set()
        unmatched_predictions = []
        for prediction in sorted(
            (item for item in predicted if item.confidence >= 0.25),
            key=lambda item: item.confidence,
            reverse=True,
        ):
            matches = [
                (box_iou(prediction.box, target.box), index)
                for index, target in enumerate(truth)
                if index not in matched_truth
            ]
            overlap, index = max(matches, default=(0.0, -1))
            if overlap < 0.5:
                unmatched_predictions.append(prediction)
            else:
                matched_truth.add(index)
                if prediction.class_id != truth[index].class_id:
                    mistake_count += 1
                    print(
                        f"- Wrong label in {filename}: actual "
                        f"{CLASS_NAMES[truth[index].class_id]}, predicted "
                        f"{CLASS_NAMES[prediction.class_id]}."
                    )
        for index, target in enumerate(truth):
            if index not in matched_truth:
                mistake_count += 1
                print(f"- Missed {CLASS_NAMES[target.class_id]} in {filename}.")
        for prediction in unmatched_predictions:
            mistake_count += 1
            print(f"- Extra {CLASS_NAMES[prediction.class_id]} box in {filename}.")
        if preview_count < args.preview_limit:
            image_path = test_image_dir / filename
            frame = cv2.imread(str(image_path))
            height, width = frame.shape[:2]
            for prediction in predicted:
                x1, y1, x2, y2 = (int(value) for value in prediction.box)
                color = COLORS[prediction.class_id]
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, max(2, width // 500))
                text = f"{CLASS_NAMES[prediction.class_id]} {prediction.confidence:.2f}"
                cv2.putText(
                    frame,
                    text,
                    (max(0, x1), min(max(20, y1 - 5), height - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    max(0.5, width / 1600),
                    color,
                    2,
                )
            if not cv2.imwrite(str(preview_dir / filename), frame):
                raise OSError(f"Could not save prediction preview for {filename}")
            preview_count += 1
    if mistake_count == 0:
        print("- No unmatched or wrong-class boxes at this threshold.")
    print(f"Preview images saved: {preview_count} to {preview_dir}")
    print(f"Ultralytics confusion/PR plots saved under: {metrics.save_dir}")


if __name__ == "__main__":
    main()
