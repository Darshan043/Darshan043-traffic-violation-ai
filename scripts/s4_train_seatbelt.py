"""Train the Stage 4 seatbelt detector locally on the prepared dataset."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import time

import torch
import yaml
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets" / "seatbelt" / "data.yaml"
DEFAULT_MODEL = ROOT / "models" / "pretrained" / "yolo26n.pt"
OUTPUT_MODEL = ROOT / "models" / "seatbelt" / "seatbelt_v1.pt"
LOCAL_IMAGE_LIMIT = 1500


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--name", default="seatbelt_v1")
    parser.add_argument("--no-copy", action="store_true", help="Do not copy the best checkpoint to models/seatbelt.")
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("--epochs must be positive.")
    config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
    dataset_root = Path(config.get("path") or args.data.parent)
    if not dataset_root.is_absolute():
        dataset_root = (args.data.parent / dataset_root).resolve()
    split_counts = {
        split: sum(
            1
            for path in (dataset_root / "images" / split).glob("*")
            if path.is_file()
            and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
        )
        for split in ("train", "val", "test")
    }
    image_count = sum(split_counts.values())
    print(f"Image count before training: {split_counts}; total={image_count}", flush=True)
    if image_count > LOCAL_IMAGE_LIMIT:
        raise SystemExit(
            f"Refusing local training for {image_count} images (> {LOCAL_IMAGE_LIMIT}). "
            "Use the Colab training notebook instead."
        )
    if not args.model.is_file():
        raise FileNotFoundError(f"Pretrained model not found: {args.model}")
    device = 0 if torch.cuda.is_available() else "cpu"
    print(
        f"Device: {'CUDA:0 ' + torch.cuda.get_device_name(0) if device == 0 else 'CPU'}; "
        f"model={args.model}; workers=0; batch={args.batch}; epochs={args.epochs}; "
        f"patience={args.patience}; fliplr=0.0; imgsz={args.imgsz}",
        flush=True,
    )
    model = YOLO(str(args.model))
    start = time.perf_counter()
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=0,
        patience=args.patience,
        fliplr=0.0,
        project=str(ROOT / "runs" / "seatbelt"),
        name=args.name,
        device=device,
    )
    elapsed = time.perf_counter() - start
    print(
        f"Training wall time: {elapsed:.1f}s; requested epochs={args.epochs}; "
        f"50-epoch projection at this rate: {elapsed * 50 / args.epochs / 60:.1f} minutes",
        flush=True,
    )
    if not args.no_copy:
        checkpoint = Path(model.trainer.save_dir) / "weights" / "best.pt"
        if not checkpoint.is_file():
            raise FileNotFoundError(f"Training finished but best checkpoint is missing: {checkpoint}")
        OUTPUT_MODEL.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checkpoint, OUTPUT_MODEL)
        print(f"Best checkpoint copied to {OUTPUT_MODEL}", flush=True)


if __name__ == "__main__":
    main()
