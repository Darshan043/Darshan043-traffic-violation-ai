# Known issues carried forward from Stage 3

- The motorcycle detector missed about 6 of 40 close-up test photos.
- One bare head was classified as a helmet.
- One rider wearing a helmet received the `NO_HEAD` result.
- The helmet test set contains only 102 images.
- The Stage 3 demo clip does not include a bare-headed rider.

## Stage 4 seatbelt limitations

- The test split has no `no_seatbelt` labels; it cannot measure that class. Validation at confidence 0.40 reports precision/recall/mAP50 of 1.000/1.000/0.995 for both classes, but validation was used to select the best checkpoint, so these scores are optimistic.
- On `test_road.mp4`, the initial 0.40 demo had 7,812 `OK` results: 568 `seatbelt` and 7,244 `no_seatbelt`. The six inspected no-seatbelt crops were blurred, distant driver windows and the belt was not visually clear.
- Because 92.7% of `OK` results were `no_seatbelt`, the run was repeated with no-seatbelt confidence 0.60 and car minimum height 200 px. It produced 21 `OK` results, all `no_seatbelt`; 24,453 cars were excluded as too small. The six stricter-run crops were still blurred windows with no clearly visible belt, so this change does not establish that the predictions are correct.
- Training and validation images are close-up photos, not CCTV-style road footage. Do not use these predictions as violation evidence without in-domain data and manual review.

## Stage 6 video validation limits

- The only available Stage 6 videos are `helmet_test.mp4` (240 frames) and
  `test_road.mp4` (2,858 frames). `track_test3.mp4` was unavailable.
- `helmet_test.mp4` contains no bare-headed rider, so the `NO_HELMET` path was
  not validated against a clear negative example.
- `test_road.mp4` has no large front-facing cars. Its small/distant side and
  rear views do not make seatbelts visually verifiable. The camera is
  configured as `side_or_rear`, so the latest run emitted 0 `NO_SEATBELT`
  events; the preceding unguarded run emitted 5.
- The final per-camera zone candidates are `y=.90` for `helmet_test.mp4` and
  `y=.80` for `test_road.mp4`. The zone sweep reported 4 and 180 never-crossed
  tracks respectively. These lines are video-specific and have not been
  validated on other camera placements.
- The latest duplicate pass on `helmet_test.mp4` retained 1 event and logged
  2 suppressed candidates. Three track IDs (2, 1, 3) appear to be one visible
  helmeted rider. The same-camera/type, <=2-second, IoU >.5 rule can still
  merge distinct vehicles in crowded scenes; every suppression needs review.
- On `test_road.mp4`, 33 of 211 cars had an ID transfer (15.64%). Replay-only
  tighter settings yielded 31 transfers at 60 px / 15 frames and 24 at 80 px /
  8 frames. Production matching limits were not changed.
- Tracker recovery transfers can preserve observation history after an ID
  switch, but two distinct nearby vehicles could be matched and merged. The
  39 total transfers in the available `test_road.mp4` run therefore need
  manual inspection. These automated results are not ground-truth identity
  evaluation.
- In a seeded output-blackout stress test, 21 tracks were selected; 18 returned
  under the same ID, 3 were not seen again before the clip ended, and no
  duplicate event was detected in those selected lineages. Some actual
  suppressions were shorter than their requested 10–30-frame window because
  the detector had already omitted those IDs in some frames. This does not
  establish real-world recovery accuracy.

## Single-pass helmet+seatbelt loop

Currently, when a camera enables both helmet and seatbelt checks, the pipeline runs helmet and seatbelt as two sequential passes over the source. A single-pass helmet+seatbelt loop combining motorcycle and car tracking in one frame loop is planned as a later improvement.
