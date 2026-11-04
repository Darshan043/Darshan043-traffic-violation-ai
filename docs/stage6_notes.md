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

- Only `helmet_test.mp4` and `test_road.mp4` are available;
  `track_test3.mp4` remains unavailable.
- The video run below is an automated pipeline validation, not a ground-truth
  identity evaluation. Manual review is still required before Stage 6 can be
  considered fully validated.
- Tracker ID observation transfer and the configured lost-track grace period
  are implemented and covered by tests. They do not eliminate the risk of
  mistakenly merging two nearby vehicles.

## Earlier validation run (superseded by the follow-up below)

The earlier run used a normalized zone line at `y=0.90` for both videos and
predated the camera-specific seatbelt safety setting and final duplicate
suppression. Its result table and review pack below are historical only; use
the follow-up results at the end of this file.
Unique vehicle counts are the number of distinct tracker IDs seen by the
respective mode; observation counts are per-frame detections.

| Video | Frames / FPS | Unique vehicles (motorcycle + car) | Events (HELMET / NO_HELMET / SEATBELT / NO_SEATBELT / NEEDS_REVIEW) | Reason codes | ID transfers | Crossings without event |
|---|---:|---:|---|---|---:|---:|
| `helmet_test.mp4` | 240 / 23.976 | 5 (3 + 2) | 1 / 0 / 0 / 0 / 2 | TOO_FEW_OBSERVATIONS 2; CLEAR_COMPLIANCE 1 | 0 | 0 |
| `test_road.mp4` | 2,858 / 50.000 | 219 (8 + 211) | 0 / 0 / 0 / 7 / 17 | TOO_FEW_OBSERVATIONS 3; CONFLICTING_OBSERVATIONS 3; CLEAR_VIOLATION 7; UNCLEAR_OBSERVATIONS 11 | 39 | 0 |

Across both videos there were 27 events: 1 `HELMET`, 7 `NO_SEATBELT`, and
19 `NEEDS_REVIEW`. The review-needed rate was **70.37% (19/27)**. Reason totals
were `TOO_FEW_OBSERVATIONS` 5, `CLEAR_COMPLIANCE` 1,
`CONFLICTING_OBSERVATIONS` 3, `CLEAR_VIOLATION` 7, and
`UNCLEAR_OBSERVATIONS` 11.

The earlier review pack is under the ignored
`data/output/s6_review/` folder. Its `review_sheet.csv` had 27 event rows and the
four requested empty reviewer fields. It is accompanied by `index.html`,
`run_report.json`, `id_transfers.csv` (all 39 transfers as separate rows), and
`crossings_without_event.csv` (header only; no such crossings were recorded).
Each current sheet row has a full-frame and crop image. There are 54 images
linked from the 27 rows; four unlinked image copies from an earlier validation
run are retained in the folder.

The automated likely-duplicate heuristic used same camera and vehicle type,
at most 2 seconds apart, and box IoU above 0.5. It flagged six pairs:

| Video | Event pair | IoU |
|---|---|---:|
| `helmet_test.mp4` | `helmet_test_f000036_t2_helmet` / `helmet_test_f000068_t1_helmet` | 0.605 |
| `helmet_test.mp4` | `helmet_test_f000068_t1_helmet` / `helmet_test_f000088_t3_helmet` | 0.555 |
| `test_road.mp4` | `test_road_f000157_t2_seatbelt` / `test_road_f000231_t25_seatbelt` | 0.538 |
| `test_road.mp4` | `test_road_f000711_t50_seatbelt` / `test_road_f000711_t42_seatbelt` | 0.515 |
| `test_road.mp4` | `test_road_f000813_t60_seatbelt` / `test_road_f000889_t67_seatbelt` | 0.788 |
| `test_road.mp4` | `test_road_f001841_t167_seatbelt` / `test_road_f001915_t170_seatbelt` | 0.669 |

This is a screening heuristic, not proof that the events are duplicates.

Six evidence crops were visually checked. The three motorcycle crops show
helmeted riders; two were nevertheless marked `NEEDS_REVIEW` because they had
too few observations. The three car crops show small/distant side or rear
views, and a seatbelt cannot be confirmed visually; the `NO_SEATBELT` output
is therefore unverified. `test_road.mp4` contains no large front-facing cars,
so it cannot validate the seatbelt detector on a clear driver view.

Latest full regression command:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

Result: **78 passed in 18.44s**.

## Seeded detector-output dropout stress test

The helmet and seatbelt pipelines were run on `test_road.mp4` with a
deterministic wrapper that hid selected tracker outputs in memory; no pipeline
source or configuration was changed. After a track had appeared in 18 frames,
the seeded selector gave it a 22% chance of one blackout window of 10–30
frames. The run selected 21 track IDs. **18 returned with the same tracker ID
and existing accumulator key; 3 were not seen again before the clip ended.**
There were **0 duplicate events** in selected track lineages. The stress run
reported 39 tracker ID transfers overall, but none was counted as recovery of
one of the selected tracks.

The requested blackout windows were 10–30 frames, but the source detector
already omitted some IDs on some frames, so the wrapper actually suppressed
fewer than the requested number of detections for several selected tracks.
“Not seen again” means not reacquired by the end of this clip; it does not prove
the injected blackout alone caused the loss. This is a controlled software
stress test, not a real-world tracking accuracy measurement. Full per-track
window data is in the ignored `data/output/s6_stress/stress_report.json`.

## Zone, seatbelt, duplicate, and review-pack follow-up

The full pipeline was rerun on both available videos using their per-video
camera settings. Candidate zone analysis decoded every available frame and
compared the normalized horizontal lines below:

| Video | Tracked | y=.5 crossings (median px; >=120 px) | y=.6 | y=.7 | y=.8 | y=.9 | Selected zone | Never crossed |
|---|---:|---|---|---|---|---|---:|---:|
| `helmet_test.mp4` | 5 | 0 | 0 | 0 | 0 | 1 (403; 1) | .9 | 4 |
| `test_road.mp4` | 219 | 24 (89.2; 0) | 25 (100.8; 2) | 29 (115.3; 11) | 39 (133.1; 25) | 11 (138.8; 10) | .8 | 180 |

For `helmet_test.mp4`, .9 is the only candidate with a crossing. For
`test_road.mp4`, .8 gives the most crossings and the largest number of crossing
vehicles at least 120 pixels tall. These are geometric choices, not proof that
the line is suitable for every camera. Candidate-line images and the list of
tracks that never crossed are in the ignored `data/output/s6_review_v2/` folder.

The prior `test_road.mp4` run produced **5 `NO_SEATBELT` events**. The current
setting marks that camera `side_or_rear`, so seatbelt judging is disabled;
the rerun produced **0 `NO_SEATBELT` events**. Cars remain tracked and there
were 34 car-zone crossings with no event because seatbelt classification was
disabled for this unverifiable view. This is a safety gate, not evidence that
the scene contains no seatbelt violations.

| Video | Frames / FPS | Tracked (motorcycles / cars) | Retained events by result | Retained reason codes | ID transfers |
|---|---:|---:|---|---|---:|
| `helmet_test.mp4` | 240 / 23.976 | 5 (3 / 2) | HELMET 1; all other results 0 | CLEAR_COMPLIANCE 1 | 0 |
| `test_road.mp4` | 2,858 / 50.000 | 219 (8 / 211) | No events | None | 39 (6 motorcycles / 33 cars) |

Across the three helmet event candidates, two were `NEEDS_REVIEW` /
`TOO_FEW_OBSERVATIONS` and one was `HELMET` / `CLEAR_COMPLIANCE`. Thus the
candidate review-needed rate was 2/3 (66.7%); after duplicate suppression, the
retained-event review-needed rate was 0/1. `test_road.mp4` had no retained
events, so its review-needed rate is not applicable.

`helmet_test.mp4` contains **one visibly distinct rider**, represented by
three tracker IDs: 2, 1, and 3. Their candidate events were at frames 36, 68,
and 88. The previous in-pipeline suppression uses a much shorter 10-frame
window and a same-decision/nearby-position check; the event gaps were 32 and
20 frames, so it did not group them. The follow-up same-camera/type, <=2-second,
IoU >.5 rule retained the 69-observation event for track 1 and recorded tracks
2 and 3 as suppressed candidates. Result: **3 candidates before, 1 retained
after, 2 explicitly listed in `suppressed_events.csv`**. This matching rule can
also merge different vehicles in crowded scenes and needs human review.

| Video | Vehicles tracked | ID transfers (motorcycle / car) | Car transfer rate | Sensitivity replay |
|---|---:|---:|---:|---|
| `helmet_test.mp4` | 5 | 0 / 0 | 0/2 (0%) | 0 with either tighter setting |
| `test_road.mp4` | 219 | 6 / 33 | 33/211 (15.64%) | 60 px: 31 car transfers; 8 frames: 24 |

The car transfer rate is above 10%. Tighter distance or frame-gap settings
were evaluated offline only; the configured limits were **not changed**.
These changes reduced the replayed car transfers by 2 and 9 respectively,
but transfers are not necessarily incorrect and the replay is not a quality
score.

The rebuilt pack is `data/output/s6_review_v2/`. Its review sheet includes all
three event candidates with a full-frame and crop image per row; the two
suppressed candidates are also disclosed in `suppressed_events.csv`. The
39 transfers have before/after images in `transfers.html` and blank
`same_vehicle` fields in `transfers_sheet.csv`. `crossings_without_event.csv`
lists crossed tracks with no retained event. Six images were visually checked:
the three helmet crops show the same helmeted rider; the road scene contains
small/distant vehicles, and their driver views do not make seatbelts
verifiable. No clear detector mistake can be established from those images,
but the seatbelt path is correctly disabled for this camera. The two available
videos are not ground-truth identity evaluation, and `track_test3.mp4` remains
unavailable. Stage 6 is **not fully validated** until the manual transfer and
event review is complete.
