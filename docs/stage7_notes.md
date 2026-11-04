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
.\.venv\Scripts\python.exe -m pytest          # 128 tests, ~24 s
```

### 4 — Run integration test (real video, server must be running)
```powershell
# Terminal A — start backend
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# Terminal B — run integration test
.\.venv\Scripts\python.exe -m pytest tests\integration\ -m integration -s -v
```

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
- **CUDA OOM after pytest**: running pytest loads PyTorch into the CUDA context; starting a video immediately after can crash with `CUDA error: unknown error`. Always run video jobs in a fresh process (or set `CUDA_VISIBLE_DEVICES=-1` for CPU-only inference).
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
