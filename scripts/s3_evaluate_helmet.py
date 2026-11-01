"""Evaluate the Stage 3 helmet model on the held-out test split."""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "helmet" / "helmet_v1.pt")
    parser.add_argument("--data", type=Path, default=ROOT / "datasets" / "helmet" / "data.yaml")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    model = YOLO(str(args.model))
    metrics = model.val(data=str(args.data), split="test", imgsz=args.imgsz, batch=args.batch,
                        workers=args.workers, plots=True, project=str(ROOT / "runs" / "helmet_eval"), name="test")
    box = metrics.box
    names = metrics.names
    print("\nTEST METRICS")
    print(f"{'class':<14} {'precision':>10} {'recall':>10} {'mAP50':>10} {'mAP50-95':>10}")
    print(f"{'overall':<14} {box.mp:10.4f} {box.mr:10.4f} {box.map50:10.4f} {box.map:10.4f}")
    class_p, class_r = box.p, box.r
    class_ap50, class_maps = box.ap50, box.maps
    for cls_id, name in names.items():
        if cls_id < len(class_p):
            print(f"{name:<14} {class_p[cls_id]:10.4f} {class_r[cls_id]:10.4f} {class_ap50[cls_id]:10.4f} {class_maps[cls_id]:10.4f}")

    plot_source = Path(metrics.save_dir)
    docs_dir = ROOT / "docs" / "stage3"
    docs_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for filename in ("confusion_matrix.png", "confusion_matrix_normalized.png", "PR_curve.png", "results.png"):
        src = plot_source / filename
        if src.exists() and src.stat().st_size <= 10 * 1024 * 1024:
            dst = docs_dir / filename
            shutil.copy2(src, dst)
            copied.append(dst.name)
    print(f"Plots copied to {docs_dir}: {', '.join(copied) or 'none'}")

    val_images = sorted(p for p in (ROOT / "datasets" / "helmet" / "images" / "val").iterdir() if p.suffix.lower() in IMAGE_EXTS)
    rng = random.Random(42)
    chosen = rng.sample(val_images, min(12, len(val_images)))
    preview_dir = ROOT / "data" / "output" / "val_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for image_path in chosen:
        pred = model.predict(source=str(image_path), imgsz=args.imgsz, verbose=False)[0]
        cv2.imwrite(str(preview_dir / image_path.name), pred.plot())
    print(f"Saved {len(chosen)} validation predictions to {preview_dir}")


if __name__ == "__main__":
    main()
