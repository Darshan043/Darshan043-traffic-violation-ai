# Traffic AI specification

This file records implementation progress. Stages 1–5 already exist in the
repository. Stage 6 adds a standalone violation decision engine.

## Stages 1–5 already available

- **Stage 1:** Project folders, virtual environment, `scripts/check_setup.py`.
- **Stage 2:** Video reading (`scripts/s2_read_video.py`) and YOLO vehicle
  detection (`scripts/s2_detect.py`) using pretrained `yolo26n.pt`.
- **Stage 3:** Custom helmet model `models/helmet/helmet_v1.pt`, geometry-only
  rider association in `ai_engine/association.py`, demo in
  `scripts/s3_helmet_demo.py`.
- **Stage 4:** Custom seatbelt model `models/seatbelt/seatbelt_v1.pt`, driver
  crop helpers in `ai_engine/seatbelt.py`, demo in `scripts/s4_seatbelt_demo.py`.
- **Stage 5:** BoT-SORT tracking in `scripts/s5_track.py`, `Track` /
  `TrackStore` in `ai_engine/tracking.py`, selected config
  `ai_engine/config/botsort_conf_test.yaml`.

Existing reusable types: `Box`, `HeadDetection`, `HelmetResult`,
`driver_helmet_result`, `link_head_to_person` (head centre in the upper 35% of
the person box), `car_driver_crop`, `seatbelt_result`, `results_to_tracks`.

Local videos found: `data/videos/test_road.mp4`, `data/videos/helmet_test.mp4`.
`track_test3.mp4` is still missing.

## Stage 6 status

### State verified before Step 3 (2026-11-02)

- Existing Step 1 decision and Step 2 zone files/tests were inspected and left in place.
- The current full suite before Step 3 had **48 passed** (not the 46 in the handoff note); the earlier entries below preserve their original test counts.
- Existing Stage 3 motorcycle crop logic was reused: crop is clipped to the frame, people are detected on the full image and an enlarged rider crop, crop coordinates are mapped back to frame coordinates, rider overlap uses the 50%-inside rule, head centres use the upper 35% of the selected person's box, and only the driver's head determines the result.

### Step 1 — Decision function (passed)

- File: `ai_engine/decision.py`
- Tests: `tests/test_decision.py`
- Voting uses all observations for a track. Violation confirmation needs 70%
  violation labels. Compliance confirmation needs 55% compliance labels.
- Reason codes: `CLEAR_VIOLATION`, `CLEAR_COMPLIANCE`, `TOO_FEW_OBSERVATIONS`,
  `CONFLICTING_OBSERVATIONS`, `UNCLEAR_OBSERVATIONS`, `LOW_CONFIDENCE`.
- Command: `.\.venv\Scripts\python.exe -B -m pytest tests/test_decision.py tests/test_association.py tests/test_seatbelt.py tests/test_tracking.py -q -p no:cacheprovider`
- Result: `37 passed`

### Step 2 — Zone class (passed)

- File: `ai_engine/zone.py`
- Tests: `tests/test_zone.py`
- Polygon (3+ points) or tripwire line (2 points). State is stored per track ID.
- `crossed(track_id, anchor)` fires once: outside→inside, path through the
  boundary, or first appearance already inside a polygon.
- Repeated points inside, leaving and re-entering, and `lost()` after a real
  crossing do not fire again for that ID.
- Lost-near-the-zone: `lost(track_id)` fires once if the last anchor is within
  `lost_near_distance` (default 40 px) and this ID has not fired yet.
- If all vertices are in 0–1 and `frame_size` is given, they are treated as
  normalised and scaled to pixels.
- Command: `.\.venv\Scripts\python.exe -B -m pytest tests/test_zone.py tests/test_decision.py tests/test_association.py tests/test_seatbelt.py tests/test_tracking.py -q -p no:cacheprovider`

### Step 3 — Motorcycle helmet pipeline (passed)

Engine settings live in `ai_engine/config/engine.py` because `ai_engine/config/`
already holds BoT-SORT YAML files. Creating `ai_engine/config.py` would clash
with that folder.

- `ai_engine/detector.py`: wraps existing YOLO26n + `helmet_v1.pt` and Stage 5
  `results_to_tracks`. Motorcycle crop, upscaled person pass, and
  `driver_helmet_result()` (upper-35% head rule) are reused, not rewritten.
- `ai_engine/helmet_pipeline.py`: track → observe near zone → vote on crossing.
  Overlay draws motorcycle, persons, riders, driver, heads, zone, and a line
  from the chosen driver to the linked head.
- `ai_engine/accumulator.py`: per-track observations, best frame, cleanup.
- `scripts/run_video.py`: command-line runner.
- Tests: `tests/test_detector.py`, `tests/test_accumulator.py`,
  `tests/integration/test_s6_helmet_pipeline.py`.
- Focused tests: **55 passed**
  `.\.venv\Scripts\python.exe -B -m pytest tests/test_accumulator.py tests/test_detector.py tests/test_decision.py tests/test_zone.py tests/test_association.py tests/integration/test_s6_helmet_pipeline.py tests/test_tracking.py tests/test_seatbelt.py -q -p no:cacheprovider`
- Real-video command:
  `.\.venv\Scripts\python.exe scripts\run_video.py --video data\videos\helmet_test.mp4 --zone 0.0,0.90,1.0,0.90 --save --no-show --out data\output\s6_helmet_test.mp4 --json data\output\s6_helmet_test_events.json`
- Actual result on `helmet_test.mp4` (1280x720, 240 frames, ~60 s runtime):
  `frames=240`, motorcycle observations=164, helmet observations=164,
  zone crossings=1, events=1.
  Event: track 1, `COMPLIANCE` / `CLEAR_COMPLIANCE`, frame 68 (2.84 s),
  69 observations. This clip has no bare-headed rider, so it cannot prove a
  no-helmet violation path.
- Evidence folder for that event:
  `storage/evidence/2026-11-02/cam1/cam1_f000068_t1_529c64f8/`
- Overlay video: `data/output/s6_helmet_test.mp4`

### Step 5 — Car seatbelt pipeline (completed)

- File: `ai_engine/seatbelt_pipeline.py`
- Tests: `tests/test_seatbelt_pipeline.py`
- Reuses the existing Stage 4 seatbelt model, driver-side crop logic, Stage 5
  BoT-SORT tracking, the voting engine, zone crossing logic, and accumulator.
- The process keeps only the driver-side car crop, runs the custom seatbelt
  detector there, turns the per-frame results into one multi-frame decision,
  emits events when the track crosses the configured zone, and saves evidence as
  in the helmet step.
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_seatbelt_pipeline.py tests/test_seatbelt.py -q -p no:cacheprovider`
- Result: `12 passed`

### Step 6 — Duplicate prevention and lost-near-the-zone handling (implemented)

- Files: `ai_engine/accumulator.py`, `ai_engine/helmet_pipeline.py`,
  `ai_engine/seatbelt_pipeline.py`
- Tests: `tests/test_stage6_duplicate.py`
- The soft duplicate check now suppresses repeated events for the same camera and
  vehicle class when the decision, time window, and vehicle position match.
- Unfinished per-track observations, best evidence frame/context, and zone
  crossing state transfer to a replacement tracker ID only when class, elapsed
  frames, position, and an unambiguous nearest candidate all match.
- A track missing near the zone is kept pending for `lost_grace_frames`; if it
  returns during that period, its state continues. Permanent near-zone loss is
  finalized only after the grace period.
- Accumulator retention is at least the configured grace period.
- Tests cover observation transfer, wrong class/distant/stale candidates,
  duplicate suppression, temporary disappearance, and permanent loss for both
  helmet and seatbelt paths.
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_stage6_duplicate.py tests/test_zone.py tests/test_decision.py -q -p no:cacheprovider`
- Additional command:
  `.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_s6_track_recovery.py tests/test_stage6_duplicate.py tests/test_zone.py -q -p no:cacheprovider`
- Additional result: `23 passed`
- Final full-suite result after the focused audit fixes:
  `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider` →
  `78 passed in 13.89s`

### Step 7 — Debugging and output video overlays (completed)

- Files: `ai_engine/helmet_pipeline.py`, `ai_engine/seatbelt_pipeline.py`
- Tests: `tests/test_stage6_debug_overlay.py`
- The overlay now shows the vehicle tracking ID, class, configured zone, and the
  most recent decision/result for each tracked vehicle.
- Helmet and seatbelt pipelines keep their labels, confidence values, and any
  driver-side crop geometry visible in the frame.
- The debug video path is still driven by the same independent runner pattern,
  so the engine remains runnable without FastAPI, MongoDB or React.
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_stage6_debug_overlay.py tests/integration/test_s6_helmet_pipeline.py tests/test_seatbelt_pipeline.py -q -p no:cacheprovider`
- Result: `7 passed`

### Step 8 — Standalone integration, CLI, JSON and evidence audit (implemented)

- Files: root `pipeline.py`, `scripts/run_video.py`, `ai_engine/evidence.py`,
  `ai_engine/seatbelt_pipeline.py`
- Tests: `tests/integration/test_s6_pipeline.py`,
  `tests/integration/test_s6_cli.py`
- `pipeline.py` orchestrates the existing helmet and seatbelt processors in
  `helmet`, `seatbelt`, or `both` mode. Local video files and RTSP/HTTP stream
  URLs are accepted. Each existing processor retains its own tracker, zone,
  observations, decisions and evidence flow.
- The CLI accepts source, mode, zone, camera ID/view, driver side, frame skip,
  observation settings, model/tracker paths, display/output options, and JSON
  output path. `--video` remains an alias for `--source`.
- In `both` mode, the existing independent processors are run sequentially.
  When saving video, one overlay video is written per mode.
- Evidence audit: evidence includes an annotated full frame, vehicle crop,
  driver/rider crop, and metadata. Seatbelt evidence now uses the car box and
  driver-side crop and includes the seatbelt detections in its annotation.
- Focused command:
  `.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_s6_pipeline.py tests/integration/test_s6_cli.py tests/integration/test_s6_helmet_pipeline.py tests/test_seatbelt_pipeline.py -q -p no:cacheprovider`
- Focused result: `8 passed`
- Full command: `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`
- Full result: `67 passed`
- Real-video smoke tests:
  - Helmet: `helmet_test.mp4`, first 3 seconds, 71 frames, 2 events
    (`NEEDS_REVIEW` and `COMPLIANCE`), output decoded at 640x360 / 23.98 FPS.
  - Seatbelt: `test_road.mp4`, first 3 seconds with `--skip 3`, 50 frames,
    3 events (2 `NEEDS_REVIEW`, 1 `VIOLATION`), output decoded at 960x540 /
    50 FPS.
  - Combined mode: `helmet_test.mp4`, first 3 seconds with `--skip 2`, 36
    frames per mode, one helmet `COMPLIANCE` event and no seatbelt event;
    both outputs decoded at 640x360 / 23.98 FPS.
  - All 6 emitted events across these runs had existing evidence files
    referenced by JSON.

### Remaining verification / limitations

The Stage 6 code path and CLI are implemented and tested, but do not declare
Stage 6 operationally closed yet. The required reviewed 20-crossing / three-video
check has not been completed. Only two videos are available;
`track_test3.mp4` is still missing. The two real-video runs above are bounded
smoke tests, not a 20-crossing identity ground-truth evaluation. Seatbelt
predictions on road footage remain subject to the known Stage 4 dataset limits.
The required reviewed 20-crossing / three-video check is still incomplete.
