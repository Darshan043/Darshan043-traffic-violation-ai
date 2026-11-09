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

## How to run Stage 5

Track COCO vehicles (car, motorcycle, bus, and truck) with the selected Experiment 3 BoT-SORT
configuration. Run from the project root:

```powershell
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\helmet_test.mp4 --tracker ai_engine\config\botsort_conf_test.yaml --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --tracker ai_engine\config\botsort_default.yaml --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --tracker botsort.yaml --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --tracker bytetrack.yaml --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --start-sec 0 --end-sec 20 --scale 0.75 --label-scale 1.3 --box-thickness 4 --trail-thickness 3 --out data\output\s5_id_check.mp4 --save --no-show --csv data\output\s5_id_check.csv
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

The selected configuration is `ai_engine/config/botsort_conf_test.yaml`; `botsort_default.yaml`,
`botsort_fixed_camera.yaml`, the ReID comparison and `bytetrack.yaml` are available for comparison.
`--csv` writes one row per track (ID, majority-vote class, first/last frame, observed frames, and
mean confidence). Use `--tracker PATH` to choose another YAML. `--start-sec` and `--end-sec` select
a reproducible video window. Larger label/box/trail options change only the inspection view, not
detection or association settings. See [Stage 5 notes](docs/stage5_notes.md) for the measured
comparisons, limitations, crop experiment, and interpretation guidance.


## How to run Stage 7

Stage 7 is a FastAPI backend that exposes every AI engine feature as a REST + WebSocket API.

### Quick start

```powershell
# 1. Create the admin account (once — prompts for password)
.\.venv\Scripts\python.exe scripts\create_admin.py

# 2. Start the server (port 8000)
.\scripts\run_backend.ps1

# 3. Open the interactive docs
start http://localhost:8000/docs
```

### Run unit tests (no real models, ~24 s)

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Run the real-video integration test

The server must already be running in another terminal:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\ -m integration -s -v
```

### Key endpoints

| URL | What it does |
|-----|-------------|
| `POST /api/auth/login` | Get a JWT token |
| `GET  /api/cameras` | List cameras |
| `POST /api/cameras/{id}/start` | Start AI analysis |
| `GET  /api/stream/{id}?token=…` | Live MJPEG frames |
| `WS   /ws/alerts?token=…` | Violation events (WebSocket) |
| `GET  /api/violations` | Query stored violations |
| `GET  /api/stats/summary` | Compliance summary |

See [Stage 7 notes](docs/stage7_notes.md) for the full endpoint table, architecture, and known limits.

## How to run Stage 8 (MongoDB)

The backend keeps the JSON repository by default. To opt in to MongoDB, configure `MONGO_URL`,
`MONGO_DB`, and `REPO_BACKEND=mongo` privately in `.env` or the process environment. Never commit
`.env` or paste a connection string into logs or chat. See [Stage 8 notes](docs/stage8_notes.md)
for the collection layout, indexes, safe test setup, migration, evidence retention, and backup/restore.

Create an admin and start the API with the project's Python:

```powershell
.\.venv\Scripts\python.exe scripts\create_admin.py
.\scripts\run_backend.ps1
```

Run the default offline suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Mongo tests are excluded by default. They require a dedicated, isolated test deployment,
`MONGO_TEST_URL`, and `MONGO_TEST_DB=traffic_ai_test`; the fixture deletes documents only from
allowlisted collections in a generated `traffic_ai_test_<10 lowercase hexadecimal characters>`
database on that configured endpoint. It does not drop the database. Set
`MONGO_TEST_ISOLATED=1` only after confirming that the endpoint is a separate isolated test deployment.
The safe preflight checker requires `MONGO_TEST_DATABASE` to name a fresh randomized database already
authorized for the test writer. It connects only through `MONGO_TEST_URL` and rejects the production
endpoint.
Read [Stage 8 notes](docs/stage8_notes.md) before opting in. The E2E helper processes
`data\videos\helmet_test.mp4` twice and requires a randomized test database plus
`MONGO_E2E_ISOLATED=1` after confirming the deployment is separate and non-production. Stage 8 prior-run
inspection uses `MONGO_E2E_READONLY_URL` scoped to `traffic_ai_e2e_audit`; its manifests describe run
metadata and identifiers and do not verify contents of prior randomized databases. See
[Stage 8 notes](docs/stage8_notes.md) for the read/write scopes and audit behavior.
