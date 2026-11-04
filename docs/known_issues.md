# Known issues carried forward from Stage 3

- The motorcycle detector missed about 6 of 40 close-up test photos.
- One bare head was classified as a helmet.
- One rider wearing a helmet received the `NO_HEAD` result.
- The helmet test set contains only 102 images.
- The Stage 3 demo clip does not include a bare-headed rider.

## Stage 6 video validation limits

- The only available Stage 6 videos are `helmet_test.mp4` (240 frames) and
  `test_road.mp4` (2,858 frames). `track_test3.mp4` was unavailable.
- `helmet_test.mp4` contains no bare-headed rider, so the `NO_HELMET` path was
  not validated against a clear negative example.
- `test_road.mp4` has no large front-facing cars. Its small/distant side and
  rear views do not make seatbelts visually verifiable.
- The full run used the configured crossing line at normalized `y=0.90` and
  produced 27 events; 19 (70.37%) were `NEEDS_REVIEW`. Six evidence crops were
  inspected, but the car seatbelt predictions could not be confirmed by eye.
- The duplicate heuristic flagged six likely event pairs for human review; it
  does not establish that they are true duplicates.
- Tracker recovery transfers can preserve observation history after an ID
  switch, but two distinct nearby vehicles could be matched and merged. The
  39 transfers in the available `test_road.mp4` run therefore need manual
  inspection. These automated results are not ground-truth identity evaluation.
- In a seeded output-blackout stress test, 21 tracks were selected; 18 returned
  under the same ID, 3 were not seen again before the clip ended, and no
  duplicate event was detected in those selected lineages. Some actual
  suppressions were shorter than their requested 10-30-frame window because
  the detector had already omitted those IDs in some frames. This does not
  establish real-world recovery accuracy.
