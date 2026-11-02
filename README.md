# AI-Based Traffic Violation Detection and Monitoring System

Repository: `Darshan043-traffic-violation-ai`.

Goal: Detect traffic violations in road video and help monitor them with computer vision.

## How to run Stage 2

Activate the virtual environment in PowerShell, then run these commands from the project folder:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\s2_read_video.py
python scripts\s2_detect.py
```

The detection script downloads its default `yolo26n.pt` model into `models/pretrained/` the first
time it runs. To save an annotated copy of the input video, run
`python scripts\s2_detect.py --save`. To test without opening a window, add `--no-show`.
The default video is `data/videos/test_road.mp4`; use `--video PATH` to select another video.

`requirements.txt` installs the CPU build of PyTorch for compatibility on other computers. If you
have a CUDA-capable NVIDIA GPU and want GPU acceleration, install the matching CUDA build of PyTorch
from [pytorch.org](https://pytorch.org/get-started/locally/) instead.

## How to run Stage 3

Prepare and audit the helmet data, then train from the project root:

```powershell
python scripts\prepare_helmet_dataset.py
python scripts\check_dataset.py
python scripts\s3_train_helmet.py
```

The default local run uses `yolo26n.pt`, 100 epochs, 640 pixels, batch 8, and two workers. On this
RTX 2050 setup, the smoke-run speed projected more than three hours for the full run, and Windows
reported a page-file error with multiprocessing, so use [the Colab notebook](notebooks/helmet_training_colab.ipynb)
for the full run. After placing the downloaded weights at `models/helmet/helmet_v1.pt`, evaluate and
run the visual demo:

```powershell
python scripts\s3_evaluate_helmet.py
python scripts\s3_helmet_demo.py --save
```

The demo can run without a window using `--no-show`. Dataset mapping and current training status are
documented in `docs/stage3_notes.md`.

## How to run Stage 4

Use the project virtual-environment Python directly from PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_seatbelt_dataset.py
.\.venv\Scripts\python.exe scripts\check_seatbelt_dataset.py
.\.venv\Scripts\python.exe scripts\s4_train_seatbelt.py
.\.venv\Scripts\python.exe scripts\s4_evaluate_seatbelt.py
.\.venv\Scripts\python.exe scripts\make_car_crops.py --skip 3
.\.venv\Scripts\python.exe scripts\s4_seatbelt_demo.py --images datasets\seatbelt_raw\test\images --save data\output\seatbelt_test_images --no-show --debug
.\.venv\Scripts\python.exe scripts\s4_seatbelt_demo.py --video data\videos\test_road.mp4 --save --no-show --debug
```

The demo assumes the driver's seat is on the right, as in India. It draws green `SEATBELT`,
red `NO SEATBELT`, and yellow `UNCLEAR` labels. Read [the Stage 4 notes](docs/stage4_notes.md)
and [the model card](models/seatbelt/README.md) before interpreting results.
