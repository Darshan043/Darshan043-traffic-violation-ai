# Stage 6 notes

## Step 5: Car seatbelt pipeline

This step was implemented by reusing the existing Stage 4 seatbelt detection and driver-side crop helpers, together with the Stage 5 tracker and the Stage 6 decision engine.

Files added:
- `ai_engine/seatbelt_pipeline.py`
- `tests/test_seatbelt_pipeline.py`

What the pipeline does:
- Tracks cars with the existing vehicle model and tracker.
- Uses the driver-side crop helper to keep only the correct half of the car.
- Runs the custom seatbelt detector on the driver crop.
- Uses the shared decision voting logic to turn several observations into one `VIOLATION`, `COMPLIANCE`, or `NEEDS_REVIEW` result.
- Saves evidence and metadata when a tracked car crosses the configured zone.

Verification:
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_seatbelt_pipeline.py tests/test_seatbelt.py -q -p no:cacheprovider`
- Result: `12 passed in 12.54s`

## Step 6: Duplicate prevention and lost-near-the-zone handling

This step adds the soft duplicate check and the lost-track handling that are needed before the Stage 6 event flow can be considered stable.

Files updated:
- `ai_engine/accumulator.py`
- `ai_engine/helmet_pipeline.py`
- `ai_engine/seatbelt_pipeline.py`
- `tests/test_stage6_duplicate.py`

What the logic does:
- Suppresses repeated events when the same camera and vehicle class reappear near the same place within a short time window and with the same final decision.
- Tracks recent anchors and suppresses matching events after a prior decision.
- Uses the zone's `lost()` rule to finalize a pending event when a vehicle disappears near the zone, but before the item is fully forgotten.

Verification:
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_stage6_duplicate.py tests/test_zone.py tests/test_decision.py -q -p no:cacheprovider`
- Result: `12 passed`

Final Stage 6 audit fixes:
- Unfinished accumulated observations, best evidence, and zone crossing state now move to a replacement ID only when vehicle class, elapsed frame gap, spatial proximity, and unique-nearest matching agree. Active tracks, wrong classes, stale candidates, distant candidates, and ambiguous candidates are not transferred.
- A missing track stays pending until `lost_grace_frames` have elapsed. A temporary return resumes the existing track state; permanent near-zone loss is finalized after the grace period.
- Accumulator retention is raised to at least `lost_grace_frames`, so pending tracks cannot be cleaned before their grace deadline.
- Added integration coverage for both helmet and seatbelt modes, including successful transfer, incorrect matching, temporary disappearance, and permanent loss.
- Focused command: `.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_s6_track_recovery.py tests/test_stage6_duplicate.py tests/test_zone.py -q -p no:cacheprovider`
- Result: **23 passed**.
- Full suite: `.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider` → **78 passed in 13.89s**.

The required manual review of at least 20 crossings across three videos remains
outstanding. Only two relevant videos are currently present, and
`track_test3.mp4` is unavailable. These automated tests establish the tested
transfer and grace-period behaviors, but do not complete the video review or
validate detector accuracy.

## Step 7: Debugging and output video overlays

This step makes the Stage 6 pipelines easier to inspect and validate by drawing the live track metadata and latest result directly onto the video frame.

Files updated:
- `ai_engine/helmet_pipeline.py`
- `ai_engine/seatbelt_pipeline.py`
- `tests/test_stage6_debug_overlay.py`

What the overlay adds:
- Vehicle tracking ID and class label
- Helmet/seatbelt label and confidence text
- Zone or crossing line
- Latest result for each track
- Driver-side crop boxes where relevant

This is still independent of FastAPI, MongoDB and React; it is a local engine-level debug overlay and video output path.

Verification:
- Command: `./.venv/Scripts/python.exe -B -m pytest tests/test_stage6_debug_overlay.py tests/integration/test_s6_helmet_pipeline.py tests/test_seatbelt_pipeline.py -q -p no:cacheprovider`
- Result: `7 passed`

Step 7 is used by the standalone Step 8 CLI for visible and saved annotated output.

## Step 8: Standalone final integration

The root `pipeline.py` orchestrates the existing helmet and seatbelt processors
without importing FastAPI, MongoDB, or React. It accepts a video file or a
RTSP/HTTP stream and supports `helmet`, `seatbelt`, or `both` modes. In `both`
mode, the processors run sequentially and produce separate annotated videos
when video saving is enabled.

The CLI in `scripts/run_video.py` keeps the previous `--video` option as an alias
for `--source`. It supports zone/camera settings, model and tracker overrides,
frame skipping, output video, display control, and JSON event output.

### Evidence audit

Evidence saving was already used by the helmet pipeline and produces an
annotated full frame, vehicle crop, driver/rider crop, and metadata in a unique
event folder. The audit found the seatbelt pipeline was calling the writer
without its analysis, so its driver crop and detector annotations were absent.
It now passes the best seatbelt analysis to the writer. Seatbelt evidence uses
the car box, driver-side crop, and seatbelt boxes/labels in the annotated frame.

### Verification

Focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/integration/test_s6_pipeline.py tests/integration/test_s6_cli.py tests/integration/test_s6_helmet_pipeline.py tests/test_seatbelt_pipeline.py -q -p no:cacheprovider
```

Result: **8 passed**.

Full suite:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Result: **67 passed**.

Real-video CLI smoke tests:

| Mode | Input and options | Processed frames | Events | Output verification |
|---|---|---:|---:|---|
| Helmet | `helmet_test.mp4`, `--end-sec 3` | 71 | 2: one `NEEDS_REVIEW`, one `COMPLIANCE` | Decoded, 640x360, 23.98 FPS |
| Seatbelt | `test_road.mp4`, `--end-sec 3 --skip 3` | 50 | 3: two `NEEDS_REVIEW`, one `VIOLATION` | Decoded, 960x540, 50 FPS |
| Both | `helmet_test.mp4`, `--end-sec 3 --skip 2` | 36 per mode | 1 helmet `COMPLIANCE`; no seatbelt events | Both outputs decoded, 640x360, 23.98 FPS |

Commands used:

```powershell
.\.venv\Scripts\python.exe scripts\run_video.py --source data\videos\helmet_test.mp4 --mode helmet --end-sec 3 --save --no-show --out data\output\s6_step8_helmet_cli.mp4 --json data\output\s6_step8_helmet_cli.json
.\.venv\Scripts\python.exe scripts\run_video.py --source data\videos\test_road.mp4 --mode seatbelt --end-sec 3 --skip 3 --save --no-show --out data\output\s6_step8_seatbelt_cli.mp4 --json data\output\s6_step8_seatbelt_cli.json
.\.venv\Scripts\python.exe scripts\run_video.py --source data\videos\helmet_test.mp4 --mode both --end-sec 3 --skip 2 --save --no-show --out data\output\s6_step8_both_verified.mp4 --json data\output\s6_step8_both_verified.json
```

JSON referenced evidence files were checked: the five events from the separate
helmet/seatbelt smoke tests and the event from combined mode all had existing
evidence image and metadata files. These short runs verify CLI integration and
output creation only; they do not prove detector accuracy. In particular, the
seatbelt violation label is not ground-truth validated, and Stage 4 documents
known limitations on road-video crops.

### Remaining verification / limitations

- The full reviewed 20-crossing / three-video check is not complete.
- Only `helmet_test.mp4` and `test_road.mp4` are available;
  `track_test3.mp4` remains unavailable.
- The real-video tests were bounded smoke runs, not a manual identity ground
  truth review. Stage 6 should not be declared operationally closed until the
  remaining review is performed with the missing/required footage.
- Tracker ID observation transfer and honoring the lost-track grace period are
  also still required before Step 6 can be considered fully complete. They were
  documented, not changed as part of this Step 8 task.
