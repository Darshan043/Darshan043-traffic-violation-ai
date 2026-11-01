"""Train the Stage 3 helmet detector."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--name", default="helmet_v1")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    data = ROOT / "datasets" / "helmet" / "data.yaml"
    model_arg = Path(args.model)
    if args.resume:
        model_arg = ROOT / "runs" / args.name / "weights" / "last.pt"
        if not model_arg.exists():
            raise FileNotFoundError(f"No checkpoint to resume: {model_arg}")
    elif args.model == "yolo26n.pt" and (ROOT / "models" / "pretrained" / args.model).exists():
        model_arg = ROOT / "models" / "pretrained" / args.model
    model = YOLO(str(model_arg))
    device = 0 if torch.cuda.is_available() else "cpu"
    print(f"Training on {'CUDA:0' if device == 0 else 'CPU'}; dataset={data}; model={model_arg}", flush=True)
    start = time.perf_counter()
    model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                workers=args.workers, patience=20, project=str(ROOT / "runs"), name=args.name,
                device=device, resume=args.resume)
    elapsed = time.perf_counter() - start
    print(f"Training wall time: {elapsed:.1f}s ({elapsed/60:.1f} min); requested epochs={args.epochs}", flush=True)


if __name__ == "__main__":
    main()
