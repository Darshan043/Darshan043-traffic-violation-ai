"""Audit a prepared YOLO dataset and write annotated training samples."""
from __future__ import annotations

import argparse
import hashlib
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
COLORS = {0: (40, 220, 40), 1: (40, 50, 240)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "helmet" / "data.yaml")
    parser.add_argument("--preview-dir", type=Path, default=ROOT / "data" / "output" / "label_check")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    yaml_text = args.data.read_text(encoding="utf-8")
    match = re.search(r"(?m)^path:\s*(.+?)\s*$", yaml_text)
    base = Path(match.group(1).strip().strip("'\"")) if match else args.data.parent
    if not base.is_absolute():
        base = (args.data.parent / base).resolve()
    names = {0: "helmet", 1: "no_helmet"}
    all_hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    class_counts = Counter()
    class_image_counts = Counter()
    issues = Counter()
    images_total = labels_total = 0
    training_candidates = []
    for split in ("train", "val", "test"):
        image_dir, label_dir = base / "images" / split, base / "labels" / split
        images = sorted(p for p in image_dir.glob("*") if p.suffix.lower() in EXTS) if image_dir.exists() else []
        labels = sorted(label_dir.glob("*.txt")) if label_dir.exists() else []
        label_map = {p.stem: p for p in labels}
        image_stems = {p.stem for p in images}
        print(f"{split}: {len(images)} images, {len(labels)} label files")
        images_total += len(images)
        labels_total += len(labels)
        issues["missing_label_files"] += sum(1 for p in images if p.stem not in label_map)
        issues["empty_label_files"] += sum(1 for p in labels if not p.read_text(encoding="utf-8").strip())
        for label in labels:
            if label.stem not in image_stems:
                print(f"  ERROR label without image: {label}")
                issues["labels_without_image"] += 1
        for image in images:
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            all_hashes[digest].append((split, image.name))
            if split == "train":
                training_candidates.append(image)
            label = label_map.get(image.stem)
            if not label:
                continue
            frame = cv2.imread(str(image))
            if frame is None:
                print(f"  ERROR unreadable image: {image}")
                issues["unreadable_images"] += 1
                continue
            h, w = frame.shape[:2]
            classes_in_image = set()
            for line_no, line in enumerate(label.read_text(encoding="utf-8").splitlines(), 1):
                vals = line.split()
                if not vals:
                    continue
                try:
                    cls = int(vals[0]); x, y, bw, bh = map(float, vals[1:5])
                except (ValueError, IndexError):
                    print(f"  ERROR malformed label: {label}:{line_no}")
                    issues["malformed_labels"] += 1
                    continue
                if cls not in names:
                    print(f"  ERROR invalid class {cls}: {label}:{line_no}")
                    issues["invalid_class_ids"] += 1
                else:
                    class_counts[(split, cls)] += 1
                    classes_in_image.add(cls)
                edges_ok = (0 <= x-bw/2 <= 1 and 0 <= x+bw/2 <= 1 and
                            0 <= y-bh/2 <= 1 and 0 <= y+bh/2 <= 1)
                if not (edges_ok and 0 <= x <= 1 and 0 <= y <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                    print(f"  ERROR out-of-range/zero box: {label}:{line_no}")
                    issues["invalid_boxes"] += 1
                    continue
                if bw * w < 10 or bh * h < 10:
                    issues["very_small_boxes"] += 1
            for cls in classes_in_image:
                class_image_counts[(split, cls)] += 1
    print("Class boxes:")
    for split in ("train", "val", "test"):
        print(f"  {split} boxes: " + ", ".join(f"{names[c]}={class_counts[(split,c)]}" for c in sorted(names)))
        print(f"  {split} images: " + ", ".join(f"{names[c]}={class_image_counts[(split,c)]}" for c in sorted(names)))
    train_box_counts = [class_counts[("train", c)] for c in sorted(names)]
    if len(train_box_counts) >= 2 and min(train_box_counts) < .30 * max(train_box_counts):
        minority = sorted(names)[train_box_counts.index(min(train_box_counts))]
        print(f"WARNING class imbalance: {names[minority]} has less than 30% of the other class's training boxes. Consider collecting more minority-class examples or using balanced sampling; labels were not changed.")
    print("Cross-split identical image hashes:")
    leak_count = 0
    for records in all_hashes.values():
        splits = {s for s, _ in records}
        if len(splits) > 1:
            leak_count += 1
            print(f"  {records}")
    issues["cross_split_duplicate_hashes"] = leak_count
    print("Audit totals:")
    for key, value in issues.items():
        print(f"  {key}: {value}")
    print(f"  images: {images_total}; label_files: {labels_total}")
    args.preview_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    chosen = rng.sample(training_candidates, min(args.samples, len(training_candidates)))
    for i, image in enumerate(chosen, 1):
        frame = cv2.imread(str(image))
        label = base / "labels" / "train" / f"{image.stem}.txt"
        if label.exists():
            h, w = frame.shape[:2]
            for line in label.read_text(encoding="utf-8").splitlines():
                vals = line.split()
                if len(vals) < 5:
                    continue
                cls = int(vals[0]); x, y, bw, bh = map(float, vals[1:5])
                x1, y1 = int((x - bw/2)*w), int((y - bh/2)*h)
                x2, y2 = int((x + bw/2)*w), int((y + bh/2)*h)
                color = COLORS.get(cls, (255, 255, 0))
                cv2.rectangle(frame, (x1,y1), (x2,y2), color, max(2, w//500))
                cv2.putText(frame, names.get(cls, str(cls)), (x1, max(18,y1-5)), cv2.FONT_HERSHEY_SIMPLEX, max(.5,w/1600), color, 2)
        cv2.imwrite(str(args.preview_dir / f"label_{i:02d}_{image.name}.jpg"), frame)
    print(f"Saved {len(chosen)} annotated samples to {args.preview_dir}")


if __name__ == "__main__":
    main()
