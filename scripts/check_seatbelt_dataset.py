"""Audit the prepared seatbelt YOLO dataset and save annotated label previews."""
from __future__ import annotations

import argparse
import hashlib
import random
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
CLASS_NAMES = {0: "seatbelt", 1: "no_seatbelt"}
COLORS = {0: (40, 220, 40), 1: (40, 50, 240)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "seatbelt" / "data.yaml")
    parser.add_argument(
        "--preview-dir",
        type=Path,
        default=ROOT / "datasets" / "seatbelt_previews",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive.")
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    if {int(key): str(value) for key, value in config["names"].items()} != CLASS_NAMES:
        raise ValueError(f"Unexpected prepared classes: {config.get('names')}")
    base = Path(config.get("path") or args.data.parent)
    if not base.is_absolute():
        base = (args.data.parent / base).resolve()

    errors = Counter()
    class_boxes: Counter[tuple[str, int]] = Counter()
    class_images: Counter[tuple[str, int]] = Counter()
    prefix_splits: dict[str, set[str]] = defaultdict(set)
    hash_splits: dict[str, set[str]] = defaultdict(set)
    candidates: dict[str, list[Path]] = defaultdict(list)
    total_images = total_labels = 0
    for split in ("train", "val", "test"):
        image_dir = base / "images" / split
        label_dir = base / "labels" / split
        images = sorted(
            path
            for path in image_dir.glob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ) if image_dir.is_dir() else []
        labels = sorted(label_dir.glob("*.txt")) if label_dir.is_dir() else []
        label_map = {path.stem: path for path in labels}
        image_stems = {path.stem for path in images}
        total_images += len(images)
        total_labels += len(labels)
        print(f"{split}: {len(images)} images, {len(labels)} label files")
        errors["empty_label_files"] += sum(
            not path.read_text(encoding="utf-8").strip() for path in labels
        )
        for image in images:
            candidates[split].append(image)
            prefix_splits[image.name.split(".rf.", 1)[0]].add(split)
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            hash_splits[digest].add(split)
            if image.stem not in label_map:
                errors["missing_label_files"] += 1
                print(f"  ERROR missing label: {image.name}")
                continue
            frame = cv2.imread(str(image))
            if frame is None:
                errors["unreadable_images"] += 1
                print(f"  ERROR unreadable image: {image}")
                continue
            height, width = frame.shape[:2]
            seen_classes = set()
            label_path = label_map[image.stem]
            for line_number, line in enumerate(
                label_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                fields = line.split()
                if not fields:
                    continue
                try:
                    class_id = int(fields[0])
                    coords = [float(value) for value in fields[1:]]
                except ValueError:
                    errors["malformed_labels"] += 1
                    print(f"  ERROR malformed label: {label_path}:{line_number}")
                    continue
                if len(coords) != 4 or class_id not in CLASS_NAMES:
                    errors["invalid_class_or_box_fields"] += 1
                    print(f"  ERROR invalid class/box fields: {label_path}:{line_number}")
                    continue
                x, y, box_width, box_height = coords
                inside = (
                    0 <= x <= 1
                    and 0 <= y <= 1
                    and 0 < box_width <= 1
                    and 0 < box_height <= 1
                    and 0 <= x - box_width / 2
                    and x + box_width / 2 <= 1
                    and 0 <= y - box_height / 2
                    and y + box_height / 2 <= 1
                )
                if not inside:
                    errors["invalid_boxes"] += 1
                    print(f"  ERROR out-of-range box: {label_path}:{line_number}")
                    continue
                class_boxes[(split, class_id)] += 1
                seen_classes.add(class_id)
                if box_width * width < 10 or box_height * height < 10:
                    errors["very_small_boxes"] += 1
            for class_id in seen_classes:
                class_images[(split, class_id)] += 1
        extra_labels = [path for path in labels if path.stem not in image_stems]
        for label in extra_labels:
            errors["labels_without_images"] += 1
            print(f"  ERROR label without image: {label.name}")

    print("Box counts by split:")
    for split in ("train", "val", "test"):
        print(
            f"  {split}: "
            + ", ".join(
                f"{CLASS_NAMES[class_id]}={class_boxes[(split, class_id)]}"
                for class_id in CLASS_NAMES
            )
        )
        print(
            f"  {split} images by class: "
            + ", ".join(
                f"{CLASS_NAMES[class_id]}={class_images[(split, class_id)]}"
                for class_id in CLASS_NAMES
            )
        )
    total_by_class = {
        class_id: sum(class_boxes[(split, class_id)] for split in ("train", "val", "test"))
        for class_id in CLASS_NAMES
    }
    print(
        "Total boxes: "
        + ", ".join(f"{CLASS_NAMES[c]}={total_by_class[c]}" for c in CLASS_NAMES)
    )
    if min(total_by_class.values()) < 0.30 * max(total_by_class.values()):
        minority = min(total_by_class, key=total_by_class.get)
        print(
            f"WARNING: {CLASS_NAMES[minority]} has less than 30% of the other "
            "class's boxes."
        )
    for class_id in CLASS_NAMES:
        if class_boxes[("test", class_id)] == 0:
            print(
                f"WARNING: test split has no {CLASS_NAMES[class_id]} boxes; "
                "per-class test results for this class are not representative."
            )

    prefix_leaks = {
        prefix: sorted(splits)
        for prefix, splits in prefix_splits.items()
        if len(splits) > 1
    }
    hash_leaks = sum(1 for splits in hash_splits.values() if len(splits) > 1)
    print(f"Source-prefix cross-split leaks (filename before '.rf.'): {len(prefix_leaks)}")
    for prefix, splits in list(prefix_leaks.items())[:10]:
        print(f"  {prefix}: {', '.join(splits)}")
    print(f"Identical-image cross-split leaks (SHA-256): {hash_leaks}")
    print("Audit totals:")
    for issue, count in sorted(errors.items()):
        print(f"  {issue}: {count}")
    print(f"  images: {total_images}; label_files: {total_labels}")

    rng = random.Random(args.seed)
    selected = []
    per_split = max(1, args.samples // 3)
    for split in ("train", "val", "test"):
        options = candidates[split]
        selected.extend((split, path) for path in rng.sample(options, min(per_split, len(options))))
    selected = selected[:args.samples]
    remaining = [
        (split, path)
        for split in ("train", "val", "test")
        for path in candidates[split]
        if path not in {image for _, image in selected}
    ]
    needed = max(0, args.samples - len(selected))
    selected.extend(rng.sample(remaining, min(needed, len(remaining))))
    args.preview_dir.mkdir(parents=True, exist_ok=True)
    for index, (split, image_path) in enumerate(selected[:args.samples], 1):
        frame = cv2.imread(str(image_path))
        label_path = base / "labels" / split / f"{image_path.stem}.txt"
        height, width = frame.shape[:2]
        for line in label_path.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) != 5:
                continue
            class_id = int(fields[0])
            x, y, box_width, box_height = map(float, fields[1:])
            x1 = max(0, min(width - 1, round((x - box_width / 2) * width)))
            y1 = max(0, min(height - 1, round((y - box_height / 2) * height)))
            x2 = max(0, min(width - 1, round((x + box_width / 2) * width)))
            y2 = max(0, min(height - 1, round((y + box_height / 2) * height)))
            color = COLORS[class_id]
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, max(2, width // 500))
            label = CLASS_NAMES[class_id]
            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, max(0.5, width / 1600), 2
            )
            text_x = min(x1, max(width - text_width, 0))
            text_y = min(max(y1 - 5, text_height + baseline), height - baseline)
            cv2.putText(
                frame,
                label,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.5, width / 1600),
                color,
                2,
            )
        preview_path = args.preview_dir / f"{index:02d}_{split}_{image_path.name}"
        if not cv2.imwrite(str(preview_path), frame):
            raise OSError(f"Could not save preview: {preview_path}")
    print(f"Saved {min(args.samples, len(selected))} annotated previews to {args.preview_dir}")
    if any(errors.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
