# Stage 7 — FastAPI Backend

## Architecture

```
backend/app/
├── main.py               ← FastAPI app, lifespan, CORS, routers
├── deps.py               ← Dependency injection (repo, JWT, rate-limit)
├── core/
│   ├── config.py         ← Settings from .env (pydantic-settings)
│   ├── security.py       ← Argon2 hashing, JWT create/decode
│   ├── logging_config.py ← Rotating file log + console; token redaction filter
│   └── errors.py         ← Uniform {"error":"CODE","message":"…"} shape
├── models/               ← Pydantic request/response schemas
├── routers/              ← One file per concern (auth, users, cameras, …)
├── services/
│   ├── engine_manager.py ← Multiprocessing AI worker (spawn-safe on Windows)
│   └── alert_service.py  ← WebSocket broadcaster (singleton)
└── db/
    ├── repository.py     ← Abstract Repository interface
    └── json_repo.py      ← JSON-file implementation (filelock)
```

Data is stored in `storage/data/*.json` (one file per collection).  
Stage 8 swaps in MongoDB by implementing the same `Repository` interface.

---

## Endpoint Table

| Method | URL | Roles | Notes |
|--------|-----|-------|-------|
| POST | `/api/auth/login` | public | Returns JWT; rate-limited 5 fails / 15 min |
| GET | `/api/auth/me` | any | Returns current user |
| GET | `/api/users` | admin | List all users |
| POST | `/api/users` | admin | Create user |
| PUT | `/api/users/{id}` | admin | Update user (disable not delete) |
| DELETE | `/api/users/{id}` | admin | Disable user (self-disable blocked) |
| GET | `/api/cameras` | any | List cameras (RTSP password redacted) |
| POST | `/api/cameras` | admin | Create camera |
| GET | `/api/cameras/{id}` | any | Get camera |
| PUT | `/api/cameras/{id}` | admin | Update camera |
| DELETE | `/api/cameras/{id}` | admin | Delete camera |
| POST | `/api/cameras/{id}/video` | admin | Upload video file (mp4/avi/mov/mkv, ≤500 MB) |
| PUT | `/api/cameras/{id}/zone` | admin | Save detection zone (normalised 0–1 points) |
| GET | `/api/cameras/{id}/snapshot` | any | One JPEG frame from the source |
| GET | `/api/cameras/{id}/status` | any | Status + last-message |
| POST | `/api/cameras/{id}/start` | admin | Start AI worker process |
| POST | `/api/cameras/{id}/stop` | admin | Stop AI worker (clean, ≤2 s) |
| GET | `/api/stream/{camera_id}?token=…` | token | MJPEG stream (img-tag safe) |
| WS | `/ws/alerts?token=…` | token | Violation + status events |
| GET | `/evidence/{path}?token=…` | token | Protected evidence image |
| GET | `/api/violations` | any | Filtered list (page/limit, type, date, …) |
| GET | `/api/violations/{id}` | any | Single violation |
| PUT | `/api/violations/{id}/review` | admin/reviewer | Add review; AI result stays unchanged |
| GET | `/api/violations/export` | any | Streamed CSV |
| GET | `/api/stats/summary` | any | Totals and compliance % |
| GET | `/api/stats/daily` | any | Per-day counts |
| GET | `/api/stats/cameras` | any | Per-camera compliance |
| GET | `/api/settings` | admin | Read decision thresholds |
| PUT | `/api/settings` | admin | Update thresholds |
| GET | `/api/health` | public | Liveness check |
| GET | `/docs` | public | Swagger UI |

---

## How to Run

### 1 — Create the admin user (once)
```powershell
.\.venv\Scripts\python.exe scripts\create_admin.py
```
Prompts for a password; never stores it in code or Git.

### 2 — Start the server
```powershell
.\scripts\run_backend.ps1          # wraps uvicorn on port 8000
# or directly:
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the interactive Swagger UI.

### 3 — Run unit tests (no real models)
```powershell
.\.venv\Scripts\python.exe -m pytest          # 133 passed; no Torch/Ultralytics import
```

### 4 — Run the complete Stage 7 smoke check
```powershell
$env:S7_SMOKE_PASSWORD = Read-Host "Temporary test password"
.\.venv\Scripts\python.exe scripts\s7_smoke.py
Remove-Item Env:\S7_SMOKE_PASSWORD
```

The script runs a CLI baseline first, then starts an isolated temporary backend
store on port 8000. It attempts CUDA and uses CPU only if CUDA fails. The
password must be provided in the environment and is never written to a file.

---

## Environment Variables (`.env`)

| Variable | Required | Default | Meaning |
|----------|----------|---------|---------|
| `SECRET_KEY` | ✅ | — | JWT signing key (≥ 32 chars) |
| `ACCESS_TOKEN_MINUTES` | | 60 | JWT lifetime |
| `CORS_ORIGIN` | | http://localhost:5173 | Allowed CORS origin |
| `STORAGE_DIR` | | storage | Root for data/logs/uploads |
| `MAX_UPLOAD_MB` | | 500 | Video upload size cap |
| `MAX_WORKERS` | | 1 | Max simultaneous AI workers |

Copy `.env.example` → `.env` and fill in `SECRET_KEY`.

---

## Limits and Known Issues

- **Single-pass helmet+seatbelt loop**: when both checks are selected the pipeline runs helmet then seatbelt as two sequential passes (see `docs/known_issues.md`). A true dual-class single pass is planned.
- **MAX_WORKERS=1**: the 4 GB GPU cannot run two YOLO models simultaneously without OOM. A second `start` returns HTTP 409.
- **Test isolation**: the default pytest suite uses fake detectors and asserts at teardown that Torch and Ultralytics were not imported and CUDA was not initialized. Run video inference in a separate process from pytest.
- **Windows spawn safety**: the multiprocessing worker uses `spawn` context; the pipeline worker function lives in an importable module with no model load at import time and `if __name__ == "__main__"` guards.
- **RTSP passwords** are never logged or returned in API responses.
- **Token query parameter** in URLs is redacted in every log line by `SensitiveDataRedactionFilter`.

---

## CLI Baseline Run (helmet_test.mp4, CPU, 2026-11-04)

```
source : data/videos/helmet_test.mp4
mode   : helmet
device : cpu (CUDA_VISIBLE_DEVICES=-1)
frames : 240
events (before suppression): 3
  track 2  NEEDS_REVIEW  TOO_FEW_OBSERVATIONS
  track 1  COMPLIANCE    CLEAR_COMPLIANCE
  track 3  NEEDS_REVIEW  TOO_FEW_OBSERVATIONS
events (after suppression):  1
  track 1  COMPLIANCE    CLEAR_COMPLIANCE
JSON   : storage/cli_events.json
```

> **Note**: The integration test (`tests/integration/test_stage7_real_run.py`) runs the same video
> through the full HTTP + WebSocket API and compares the violation count with this baseline.
> Run it after starting the backend server (`run_backend.ps1`).

---

## Engine Changes (Part 1)

| Change | File | Detail |
|--------|------|--------|
| Live incremental events | `pipeline.py` | `IncrementalDuplicateSuppressor` fires `on_event` as each detection is finalised |
| Annotated frames | `pipeline.py` | `on_annotated_frame(jpeg, idx)` callback; 10 FPS cap, 960 px wide, JPEG q70 |
| Stop event | `pipeline.py`, `helmet_pipeline.py`, `seatbelt_pipeline.py` | `threading.Event` checked every frame |
| Pass indicator overlay | `pipeline.py` | "Pass 1/2: helmet" text drawn on each frame |
| `device` config | `ai_engine/config/engine.py`, `ai_engine/detector.py` | `CameraConfig.device` passed to YOLO `.to()` |

## Result labels

| Pipeline `decision` | Pipeline `ai_result` | Stored `vehicle_events.result` |
|---|---|---|
| `COMPLIANCE` | `helmet` | `HELMET` |
| `VIOLATION` | `no_helmet` | `NO_HELMET` |
| `COMPLIANCE` | `seatbelt` | `SEATBELT` |
| `VIOLATION` | `no_seatbelt` | `NO_SEATBELT` |
| `NEEDS_REVIEW` | any result | `NEEDS_REVIEW` |
| any other or inconsistent pair | any result | `NOT_CHECKED` |

Compliance percentage is calculated from `HELMET` + `SEATBELT` versus
`NO_HELMET` + `NO_SEATBELT`; `NEEDS_REVIEW` is reported separately and is
excluded from that percentage.

## Stage 7 verification results (2026-11-04)

- Default suite: **133 passed, 1 deselected**. Peak pytest RSS was **164.3 MiB**;
  Torch and Ultralytics were absent after the suite, and CUDA was not initialized.
- The earlier report of roughly 12 GB usage/GPU retention was not reproduced.
  At initial inspection no project Python/Uvicorn process was running and only
  1.46 GB system RAM was free; the pre-fix suite imported Torch but reported
  `torch.cuda.is_initialized() == False`. The exact source of earlier system-wide
  memory use cannot be determined from the current run.
- Cause of pytest model imports: `ai_engine.seatbelt_pipeline` and helper-only
  scripts imported Ultralytics at module scope. Model imports are now lazy, and
  the default suite has an end-of-session guard against importing Torch or
  Ultralytics.
- Real API smoke: **42 checks passed** using **CUDA (`cuda:0`)** and temporary
  backend storage. A same-device CLI baseline was run before Uvicorn; both CLI
  and API stored one `HELMET` event.
- Live MJPEG: 10 frames fetched; 3 saved under ignored
  `data/output/s7_stream/`.
- WebSocket: first provisional event at
  `2026-11-04T13:42:22.840506Z`; video finished at
  `2026-11-04T13:42:31.878159Z` (about 9.0 seconds later).
- Stop/worker memory check: the second run stopped in **3.19 seconds**; worker
  RSS went from **1423.7 MiB to 0 MiB** after exit. A second camera start while
  a worker was active returned **409**.
- Token checks: no JWT appeared in the temporary storage logs or Uvicorn output;
  access logs contained `token=REDACTED`.
- Live notifications are provisional candidates, emitted as soon as the engine
  finalizes each observation. Persisted vehicle events are reconciled at run
  completion with the same observation-ranked duplicate suppression as the CLI,
  so live delivery does not change final statistics or event history.
