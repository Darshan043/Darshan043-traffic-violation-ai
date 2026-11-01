from pathlib import Path
import sys

import cv2
import numpy
import torch
import ultralytics


REQUIRED_FOLDERS = (
    "ai_engine",
    "backend",
    "frontend",
    "datasets",
    "models",
    "data",
    "storage",
    "tests",
    "docs",
    "scripts",
    "data/videos",
    "models/helmet",
    "models/seatbelt",
    "storage/evidence",
    "storage/uploads",
    "storage/logs",
)


def main() -> None:
    print(f"Python version: {sys.version.split()[0]}")
    print(f"OpenCV version: {cv2.__version__}")
    print(f"Ultralytics version: {ultralytics.__version__}")
    print(f"NumPy version: {numpy.__version__}")
    print(f"torch.cuda.is_available(): {torch.cuda.is_available()}")
    print(f"venv active: {sys.prefix != sys.base_prefix}")
    for folder in REQUIRED_FOLDERS:
        status = "OK" if Path(folder).is_dir() else "MISSING"
        print(f"{folder}: {status}")


if __name__ == "__main__":
    main()
