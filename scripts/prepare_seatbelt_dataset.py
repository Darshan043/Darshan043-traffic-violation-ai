"""Prepare one seatbelt source dataset with the agreed two-class mapping."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets" / "seatbelt_raw"
DESTINATION = ROOT / "datasets" / "seatbelt"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
CLASS_MAP = {0: 1, 1: 0}
EXPECTED_NAMES = ["without-seatbelt", "with-seatbelt"]
SPLITS = {"train": ("train",), "val": ("valid", "val"), "test": ("test",)}


def class_names(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(value[key]) for key in sorted(value, key=lambda item: int(item))]
    if isinstance(value, list):
        return [str(name) for name in value]
    raise ValueError(f"Unsupported source class names: {value!r}")


def remap_label(source: Path, destination: Path) -> int:
    rows = []
    with source.open(encoding="utf-8") as label_file:
        for line_number, line in enumerate(label_file, 1):
            fields = line.split()
            if not fields:
                continue
            try:
                class_id = int(fields[0])
            except ValueError as error:
                raise ValueError(f"Invalid class id at {source}:{line_number}") from error
            if class_id not in CLASS_MAP or len(fields) != 5:
                raise ValueError(f"Unexpected label at {source}:{line_number}: {line.strip()}")
            rows.append(" ".join([str(CLASS_MAP[class_id]), *fields[1:]]))
    destination.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--dest", type=Path, default=DESTINATION)
    args = parser.parse_args()
    source, destination = args.source.resolve(), args.dest.resolve()
    config_path = source / "data.yaml"
    if not config_path.is_file():
        raise FileNotFoundError(f"Source data.yaml not found: {config_path}")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    names = [name.strip().lower() for name in class_names(config.get("names"))]
    if names != EXPECTED_NAMES:
        raise ValueError(f"Unexpected classes {names}; expected {EXPECTED_NAMES}")
    if destination.exists():
        raise FileExistsError(
            f"Destination already exists: {destination}. Remove or move it manually before preparing again."
        )

    split_sources: dict[str, Path] = {}
    for output_split, source_candidates in SPLITS.items():
        for source_split in source_candidates:
            candidate = source / source_split / "images"
            if candidate.is_dir():
                split_sources[output_split] = candidate
                break
        if output_split not in split_sources:
            raise FileNotFoundError(f"Missing {output_split} image split under {source}")

    destination.mkdir(parents=True)
    images_copied = 0
    labels_copied = 0
    boxes_remapped = 0
    for output_split, image_dir in split_sources.items():
        output_images = destination / "images" / output_split
        output_labels = destination / "labels" / output_split
        output_images.mkdir(parents=True)
        output_labels.mkdir(parents=True)
        source_label_dir = image_dir.parent / "labels"
        image_paths = sorted(
            path
            for path in image_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        for image_path in image_paths:
            shutil.copy2(image_path, output_images / image_path.name)
            source_label = source_label_dir / f"{image_path.stem}.txt"
            output_label = output_labels / f"{image_path.stem}.txt"
            if source_label.is_file():
                boxes_remapped += remap_label(source_label, output_label)
                labels_copied += 1
            else:
                output_label.write_text("", encoding="utf-8")
            images_copied += 1
        print(
            f"{output_split}: copied {len(image_paths)} images "
            f"from {image_dir.relative_to(source)}"
        )

    output_config = {
        "path": destination.as_posix(),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {0: "seatbelt", 1: "no_seatbelt"},
        "nc": 2,
    }
    (destination / "data.yaml").write_text(
        yaml.safe_dump(output_config, sort_keys=False), encoding="utf-8"
    )
    print(f"Prepared one source only: {source}")
    print("Mapping: source 1 with-seatbelt -> 0 seatbelt; source 0 Without-seatbelt -> 1 no_seatbelt")
    print(
        f"Totals: {images_copied} images, {labels_copied} labelled images, "
        f"{boxes_remapped} remapped boxes"
    )
    print(f"Prepared dataset: {destination}")


if __name__ == "__main__":
    main()
