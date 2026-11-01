"""Copy and remap the confirmed Roboflow helmet dataset without changing the source."""
from __future__ import annotations

import argparse
import random
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "datasets" / "helmet_raw"
DEST = ROOT / "datasets" / "helmet"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
CLASS_MAP = {0: 0, 2: 1}
SPLITS = {"train": "train", "valid": "val", "val": "val", "test": "test"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--dest", type=Path, default=DEST)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    source, dest = args.source.resolve(), args.dest.resolve()
    yaml_text = (source / "data.yaml").read_text(encoding="utf-8")
    names_match = re.search(r"(?m)^names:\s*\[([^\]]+)\]", yaml_text)
    names = [value.strip().strip("'\" ") for value in names_match.group(1).split(",")] if names_match else []
    names = dict(enumerate(names))
    expected = {0: "Helmet", 1: "Motorcycle", 2: "No_helmet"}
    if names != expected:
        raise ValueError(f"Unexpected source classes {names}; expected {expected}")
    if dest.exists():
        raise FileExistsError(f"Destination already exists: {dest}. Move it aside manually before preparing again.")
    dest.mkdir(parents=True)
    rng = random.Random(args.seed)
    background_only = 0
    counts = {s: 0 for s in ("train", "val", "test")}

    # Ignore the YAML's relative paths: use the known Roboflow folder layout.
    source_splits = {"train": source / "train" / "images", "val": source / "valid" / "images"}
    if (source / "test" / "images").is_dir():
        source_splits["test"] = source / "test" / "images"
    if "train" not in source_splits or "val" not in source_splits:
        raise ValueError("Source data.yaml must provide train and valid/val splits")
    if "test" not in source_splits:
        valid_images = sorted(p for p in source_splits["val"].iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if len(valid_images) < 2:
            raise ValueError("Cannot make a test split from fewer than two validation images")
        rng.shuffle(valid_images)
        n_test = max(1, round(len(valid_images) * .10))
        held_out = {p.name for p in valid_images[:n_test]}
        print(f"No test split found: moving {n_test} validation images (10%, seed {args.seed}) into test.")
    else:
        held_out = set()

    output_sources = {
        "train": [(source_splits["train"], None)],
        "val": [(source_splits["val"], held_out)],
        "test": [(source_splits["test"], None)] if "test" in source_splits else [(source_splits["val"], held_out)],
    }
    for split, sources in output_sources.items():
        (dest / "images" / split).mkdir(parents=True)
        (dest / "labels" / split).mkdir(parents=True)
        for image_dir, selected_names in sources:
            files = sorted(p for p in image_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
            if selected_names is not None:
                files = [p for p in files if (p.name in selected_names) == (split == "test")]
            for img in files:
                shutil.copy2(img, dest / "images" / split / img.name)
                src_label = image_dir.parent / "labels" / f"{img.stem}.txt"
                mapped: list[str] = []
                saw_moto = False
                if src_label.exists():
                    for line_no, line in enumerate(src_label.read_text(encoding="utf-8").splitlines(), 1):
                        parts = line.split()
                        if not parts:
                            continue
                        class_id = int(float(parts[0]))
                        if class_id == 1:
                            saw_moto = True
                            continue
                        if class_id not in CLASS_MAP:
                            raise ValueError(f"Unknown class {class_id} in {src_label}:{line_no}")
                        mapped.append(" ".join([str(CLASS_MAP[class_id]), *parts[1:]]))
                if saw_moto and not mapped:
                    background_only += 1
                (dest / "labels" / split / f"{img.stem}.txt").write_text("\n".join(mapped) + ("\n" if mapped else ""), encoding="utf-8")
                counts[split] += 1

    output_yaml = (f"path: {dest.as_posix()}\n"
                 "train: images/train\nval: images/val\ntest: images/test\n"
                 "names:\n  0: helmet\n  1: no_helmet\n")
    (dest / "data.yaml").write_text(output_yaml, encoding="utf-8")
    print(f"Prepared dataset at {dest}")
    print(f"Images: train={counts['train']}, val={counts['val']}, test={counts['test']}")
    print(f"Images containing only dropped Motorcycle boxes (background after remap): {background_only}")


if __name__ == "__main__":
    main()
