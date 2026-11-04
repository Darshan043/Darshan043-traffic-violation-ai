# Stage 5: Vehicle tracking with YOLO and BoT-SORT

## Objective and flow

Stage 5 detects COCO cars (2), motorcycles (3), buses (5), and trucks (7), then associates detections across frames to give each visible vehicle a temporary ID. `scripts/s5_track.py` calls Ultralytics `model.track(..., persist=True)` once per processed frame. A fresh YOLO model is constructed for each invocation, so tracker memory and ID allocation reset between videos/runs. Boxes without a tracker ID are skipped rather than assigned a made-up ID.

The tracker configuration controls motion prediction, detection association, lost-track buffering, and (optionally) appearance/ReID matching. `ai_engine/tracking.py` converts results into geometry-only `Track` objects and keeps per-ID anchor history, first/last-seen frames, and class votes. The history is capped at 60 anchors; the overlay draws the latest 40. Stale geometry is removed after 120 source frames, while the separate run statistics stay alive for CSV export.

The CSV has one row per track ID: majority-vote class, first/last 0-based source frame, number of observations with an ID, and mean detection confidence. `frames_seen` means observations, not necessarily consecutive frames. A track that exits and re-enters after the tracker drops it can receive a new ID.

## Method and environment

- Ultralytics 8.4.197, `yolo26n.pt`, RTX 2050 CUDA environment.
- Tracker comparisons used conf 0.30, imgsz 640, skip 1, classes `[2, 3, 5, 7]`, saved half-scale video, identical source windows per video, and fresh model/tracker state per run.
- `test_road.mp4` comparison window: source frames 0–999 (0–20 s at 50 FPS).
- `helmet_test.mp4` comparison window: source frames 0–238 (239 frames; the final comparison command used end time 10 s). The selected tracker was then run over the full 240 frames.
- Run configuration and output summary were captured in UTF-16 PowerShell logs under `data/output/`.
- FPS is processed inference frames divided by elapsed loop time; it includes video decoding and writing. It is not directly comparable to Stage 2's 42.71 FPS inference-only measurement.
- `track_test3.mp4` was not present in `data/videos/` and was not tested.

The installed BoT-SORT defaults were read from Ultralytics' `cfg/trackers/botsort.yaml` before copying to `ai_engine/config/botsort_default.yaml`. The installed tracker accepts the `gmc_method: None` string as an identity warp. ReID is supported in this Ultralytics version; `model: auto` uses the detector's features, so no separate ReID download was required. The ReID run completed.

## Controlled tracker comparison

IDs are tracklets, not ground-truth vehicle identities. No manually labeled ID trajectories are available, so these counts describe the tracker outputs and cannot prove identity accuracy.

### `test_road.mp4` — frames 0–999

| Tracker | IDs car / motorcycle / bus / truck | Total IDs | Mean frames | Median frames | Under 10 | Single-frame | FPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ultralytics BoT-SORT default | 160 / 6 / 15 / 112 | 293 | 38.06 | 3 | 202 | 104 | 8.41 |
| Fixed-camera BoT-SORT | 154 / 5 / 13 / 107 | 279 | 40.02 | 3 | 192 | 99 | 15.91 |
| Experiment 3 BoT-SORT | 106 / 3 / 11 / 57 | 177 | 60.99 | 7 | 98 | 37 | 17.14 |
| Experiment 3 + ReID | 103 / 1 / 15 / 65 | 184 | 58.98 | 5.5 | 108 | 43 | 16.17 |
| ByteTrack | 181 / 7 / 18 / 109 | 315 | 35.27 | 3 | 221 | 115 | 17.08 |

### `helmet_test.mp4` — frames 0–238 (239 frames)

| Tracker | IDs car / motorcycle / bus / truck | Total IDs | Mean frames | Median frames | Under 10 | Single-frame | FPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ultralytics BoT-SORT default | 3 / 3 / 0 / 0 | 6 | 36.83 | 9 | 3 | 0 | 12.21 |
| Fixed-camera BoT-SORT | 3 / 3 / 0 / 0 | 6 | 36.67 | 7 | 3 | 1 | 15.50 |
| Experiment 3 BoT-SORT | 2 / 3 / 0 / 0 | 5 | 43.40 | 11 | 2 | 1 | 15.87 |
| Experiment 3 + ReID | 3 / 3 / 0 / 0 | 6 | 36.67 | 7.5 | 3 | 2 | 15.66 |
| ByteTrack | 3 / 3 / 0 / 0 | 6 | 36.50 | 26 | 2 | 0 | 16.40 |

The earlier run called “Original BoT-SORT” used `botsort_traffic.yaml` with buffer 60, not the copied Ultralytics default buffer 30. The table above includes a new true-default run. The fixed-camera config changes both GMC and buffer relative to true default; Experiment 3 then changes only `new_track_thresh` from 0.25 to 0.35. The ReID config matches Experiment 3 and changes only `with_reid`.

Experiment 3 has fewer short tracks on the road clip and runs quickly, but its ID total is much lower: it could be reducing fragments, suppressing real low-confidence vehicles, or both. The videos have no identity ground truth, so fewer IDs are not treated as proof of better tracking. ReID did not improve the summary counts over Experiment 3 in this sample. ByteTrack produced many more short and one-frame tracks on the busy road clip. **Selected default:** `ai_engine/config/botsort_conf_test.yaml` (Experiment 3), provisionally, because it has the fewest short/single-frame tracks on the dense road segment, maintains observed IDs in the reviewed stop/move samples, and is among the fastest. Keep the fixed-camera and default YAMLs available for comparison; revisit this selection with labeled vehicle trajectories.

## ID-check video and visual findings

`data/output/s5_id_check.mp4` is a visual-only rerender of the same Experiment 3 model, tracker, confidence, image size, skip rate, and frames 0–999 (0–20 s). It uses 0.75 output scale, larger labels, thick boxes/trails, and ID-based colors. The source Experiment 3 MP4 and CSV were preserved. `data/output/s5_id_check.csv` records the matching run.

Six time points (frames 0, 200, 400, 600, 820, 999) were visually inspected, and five long-lived CSV tracks were cross-referenced:

| Example | Class | First–last frame | Observations |
|---|---|---:|---:|
| ID 3 | bus | 0–647 | 545 |
| ID 99 | car | 564–999 | 436 |
| ID 64 | car | 382–962 | 435 |
| ID 107 | truck | 614–999 | 386 |
| ID 108 | bus | 618–999 | 368 |

No definite ID swap was confirmed in these sampled views, and the long-lived bus remained consistently boxed while moving through the checked frames. The crowded queue still has overlapping boxes and some label collisions; the sampled review cannot rule out all ID switches. On the full selected-config road run, 233/432 tracks were under 10 observations and 106 were single-frame tracks. Some are vehicles entering/leaving the view, but this is also evidence of fragmentation and warrants further review. The fixed camera allows vehicles to stop and move; camera shake and prolonged occlusion were not isolated as controlled test cases.

## Selected configuration on available videos

| Video | Tested source frames | IDs car / motorcycle / bus / truck | Total | Mean / median | Under 10 / single | FPS |
|---|---|---:|---:|---:|---:|---:|
| `test_road.mp4` | 0–2857 (all 2,858) | 255 / 8 / 37 / 132 | 432 | 71.14 / 7 | 233 / 106 | 18.40 |
| `helmet_test.mp4` | 0–239 (all 240) | 2 / 3 / 0 / 0 | 5 | 43.40 / 11 | 2 / 1 | 15.45 |
| `track_test3.mp4` | unavailable | — | — | — | — | — |

The road video contains stopped/moving traffic, dense overlaps, and vehicles entering/leaving. The motorcycle-focused helmet clip exercises moving motorcycles but has few cars/buses/trucks and is not a broad road-scene test. Neither clip has labeled ground-truth IDs; no automated ID-switch count is claimed.

## Vehicle crop comparison

`scripts/make_car_crops.py` was run on test-road source frames 0–999, conf 0.30, imgsz 640, skip 1, minimum car height 120, driver side right:

| Mode | Detection observations | Too-small cars | Crops saved | Tracks represented | Median crop W×H | Median sharpness (Laplacian variance) | Exact duplicate files |
|---|---:|---:|---:|---:|---:|---:|---:|
| No tracker | 7,095 | 3,508 | 3,587 | n/a | 123×77 px | 2,234.4 | 150 |
| Tracker, top 3 per track, 15-frame minimum separation | 6,959 assigned-ID observations | 3,393 | 110 | 48 | 87.5×74 px | 3,390.5 | 0 |

The tracked mode saved about 97% fewer crops and prevented exact duplicate images in this run. It selected fewer crops per vehicle and the median crops were smaller; the higher sharpness score does not guarantee better visual usefulness. Six representative crops were inspected: some tracked picks were sharper but tightly framed or blocked by a pole, and untracked crops included blurred windows. No claim that all tracked crops are better is warranted. Outputs are in `data/output/s5_crops_untracked/` and `data/output/s5_crops_tracked_spaced/`.

## Tests and regression checks

- Unit tests cover missing IDs, bottom-centre anchors, bounded history, last-seen updates, stale cleanup, and majority class voting.
- Video integration tests use four-frame synthetic clips and a deterministic fake tracker to check tracker calls/initialization plumbing, persistence of IDs, multiple classes, missing IDs, CSV/video output, and empty detections. They do not substitute for the real-video comparisons above.
- Full suite: `28 passed` (`.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider`).
- Stage 1 setup check passed: Python 3.12.10, OpenCV 5.0.0, Ultralytics 8.4.197, NumPy 2.5.4, CUDA available, and every required folder reported `OK`.
- Stage 3 helmet dataset audit completed with no missing labels, malformed labels, invalid classes, or cross-split duplicate hashes. It reported one empty label file and three very small boxes; these are audit warnings, not test failures.
- Stage 4 seatbelt dataset audit completed with zero empty labels, source-prefix leaks, or identical-image leaks. It warned that the test split contains no `no_seatbelt` examples.
- Stage 2 reader/detector, Stage 3 evaluator/demo, and Stage 4 evaluator/demo CLI checks all passed. Both original and MP4V inspection videos reopen and report 1,000 frames at 1440x810 and 50 FPS.

## Reproduction commands

Run from the project root in PowerShell. All outputs go under ignored `data/output/`.

```powershell
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\test_road.mp4 --tracker ai_engine\config\botsort_conf_test.yaml --conf 0.30 --imgsz 640 --skip 1 --save --no-show --csv
.\.venv\Scripts\python.exe scripts\s5_track.py --video data\videos\helmet_test.mp4 --tracker ai_engine\config\botsort_conf_test.yaml --conf 0.30 --imgsz 640 --skip 1 --save --no-show --csv
.\.venv\Scripts\python.exe scripts\make_car_crops.py --video data\videos\test_road.mp4 --out data\output\s5_crops_untracked --skip 1 --min-height 120 --conf 0.30 --start-sec 0 --end-sec 20 --imgsz 640
.\.venv\Scripts\python.exe scripts\make_car_crops.py --video data\videos\test_road.mp4 --out data\output\s5_crops_tracked_spaced --skip 1 --min-height 120 --conf 0.30 --start-sec 0 --end-sec 20 --imgsz 640 --use-tracker --per-track 3 --min-frame-gap 15
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider
```

## Completion status

### Final manual inspection

The user completed a manual visual review of `data/output/s5_id_check_compatible.mp4`.
Vehicles generally kept the same IDs while stopping and moving, and the reviewer saw no
obvious ID switches or incorrect vehicle associations during this inspection. This is a
manual visual review only, not a ground-truth identity evaluation: there are no labeled
vehicle-identity trajectories, and the review does not prove that switches never occur.
The compatible inspection video was verified with OpenCV after MP4V conversion: 1,000
decodable frames at 1440x810 and 50 FPS. The original `s5_id_check.mp4` was preserved.
`track_test3.mp4` was unavailable and is not claimed as tested.

### Selected tracker and limitations

The selected provisional tracker remains BoT-SORT using
`ai_engine/config/botsort_conf_test.yaml`; no tracking parameters were changed for closure.
Its relevant settings are `new_track_thresh: 0.35`, `track_buffer: 60`, `gmc_method: None`,
`with_reid: False`, `match_thresh: 0.8`, and `fuse_score: True`. The evaluated run also used
YOLO26n, confidence 0.30, image size 640, every frame (`skip: 1`), and vehicle classes
`[2, 3, 5, 7]`.

This selection is provisional: the clips have no ground-truth IDs, so tracker comparisons
and this visual review cannot establish identity accuracy. On the full road run, 233 of 432
tracklets were shorter than 10 observations and 106 were single-frame tracklets, indicating
fragmentation or brief detections. Dense overlaps and label collisions remain; prolonged
occlusion, camera shake, and crowded-scene identity switches were not measured with labeled
data. `track_test3.mp4` remains an unavailable test case.

Stage 5's implementation, tests, comparisons, crop checks, both available video runs, and
the requested manual inspection are complete. Closure does not imply ground-truth-validated
tracking accuracy; it means the available checks passed with the limitations above recorded.
