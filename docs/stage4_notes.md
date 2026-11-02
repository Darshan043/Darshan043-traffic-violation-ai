# Stage 4: Seatbelt detection

## Dataset and audit

Only the larger `datasets/seatbelt_raw/` source was prepared; the 10-image `seatbelt_raw2/`
source was kept separate and not merged. The main source has 1,186 images:

The second source has 9 training files and 1 validation image, but only four distinct filename
source prefixes across the whole set, with no test split. Its single validation image can be used
for a qualitative demo only; it is not a held-out test set.

The second source uses source class 0 `no-seatbelt` (10 boxes) and source class 1 `seatbelt`
(6 boxes). The first source uses source class 0 `Without-seatbelt` and class 1 `with-seatbelt`.
Both sources contain boxes around people/body regions, but only the first source was used for
training.

| Split | Images | Seatbelt boxes | No-seatbelt boxes |
|---|---:|---:|---:|
| Train | 1,056 | 351 | 705 |
| Validation | 100 | 34 | 66 |
| Test | 30 | 30 | 0 |

Mapping: source class 1 `with-seatbelt` → class 0 `seatbelt`; source class 0
`Without-seatbelt` → class 1 `no_seatbelt`. No class has fewer than 30% of the other class's
boxes in the combined dataset. The test split has no `no_seatbelt` examples, so its score for
that class cannot be measured meaningfully. The audit found zero invalid boxes, zero identical
image hashes across splits, and zero filename-prefix leaks (the part before `.rf.`).

Twelve annotated previews were saved locally under `datasets/seatbelt_previews/`. They show
close-up in-car photos, including rotated/augmented images, not CCTV-style front views. Boxes
usually cover the person's upper body or a larger part of the person; they are not consistently
the requested driver-only upper-body crops. The accepted class mapping was applied without
changing source box geometry.

## Training

- Route: local RTX 2050 GPU; PyTorch CUDA was available.
- Images counted before training: 1,186 total (1,056 train, 100 validation, 30 test), below the
  1,500-image local limit.
- One-epoch smoke test: 70.5 seconds; projected 50-epoch time about 58.8 minutes.
- Training settings: batch 8, workers 0, image size 640, horizontal flip 0.0, patience 10.
- Training stopped early at epoch 26 after 10 epochs without improvement; the best checkpoint
  was epoch 16. Wall time was about 18 minutes 16 seconds. Best validation precision was 0.9939,
  recall 1.0000, mAP50 0.9950, and mAP50-95 0.7069.
- The final checkpoint is `models/seatbelt/seatbelt_v1.pt` locally; Git ignores it.

## Test results

The 30-image test set is small and contains only `seatbelt` ground-truth boxes. Training images
are close-up cabin photos, not CCTV crops, so these results cannot establish performance on CCTV
footage. No meaningful test metrics are available for `no_seatbelt`, because that class has no
test ground-truth boxes.

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| seatbelt | 0.9634 | 0.9667 | 0.9657 | 0.4157 |
| no_seatbelt | N/A | N/A | N/A | N/A (no test labels) |

Confusion matrix at confidence 0.25 and IoU 0.50 (rows are true; columns are predicted):

| True \ Predicted | seatbelt | no_seatbelt | background |
|---|---:|---:|---:|
| seatbelt | 29 | 0 | 1 |
| no_seatbelt | 0 | 0 | 0 |
| background | 3 | 0 | 0 |

| Confidence | Class | Precision | Recall | TP | FP | FN |
|---:|---|---:|---:|---:|---:|---:|
| 0.25 | seatbelt | 0.906 | 0.967 | 29 | 3 | 1 |
| 0.25 | no_seatbelt | N/A | N/A | 0 | 0 | 0 |
| 0.40 | seatbelt | 0.967 | 0.967 | 29 | 1 | 1 |
| 0.40 | no_seatbelt | N/A | N/A | 0 | 0 | 0 |
| 0.50 | seatbelt | 0.967 | 0.967 | 29 | 1 | 1 |
| 0.50 | no_seatbelt | N/A | N/A | 0 | 0 | 0 |

At confidence 0.25, the model added extra seatbelt boxes to two images; on a third it missed the
annotated seatbelt and also made an extra prediction. The generated test-preview images and
confusion/precision-recall plots are in the ignored `runs/seatbelt_eval/` folder.

Qualitative demos ran on all 30 source-1 test images, the one source-2 validation image, and
`data/videos/test_road.mp4`. The raw2 image received a seatbelt prediction even though a clear
strap is not visible, illustrating that the small out-of-domain sample is not a reliable test.
The image demos counted 30/30 and 1/1 inputs as crops with `OK` decisions. The video summary is
recorded below. Six saved images were visually inspected: the five raw1 close-up examples show
the belt and plausible detections, but the boxes are broad body-region boxes; the raw2 image
demonstrates a false positive. This is not yet a dependable road-video detector.

| Video demo measure | Result |
|---|---:|
| Frames processed | 2,858 |
| Output video | 960 x 540 at 50 FPS; opens and reads successfully |
| Car detections | 24,499 |
| Driver crops made | 9,235 |
| `OK` decisions | 7,812 |
| `LOW_CONF` decisions | 1,423 |
| `TOO_SMALL` car boxes | 15,264 |
| `NO_DRIVER` decisions | 0 |

`make_car_crops.py --skip 3` read the same 2,858 frames, found 8,177 cars, skipped 5,086 cars
below the minimum height, and saved 3,091 driver-side crops. The very high car count and many
small detections show why this is only an exploratory demo. It does not independently verify a
driver, and its status labels should not be used as evidence of a real violation.

## Why seatbelt detection is harder than helmet detection

Helmets are relatively distinctive objects near the top of a rider. A seatbelt is a thin,
diagonal strap that can be hidden by clothing, arms, glare, or the steering wheel. Seatbelt
decisions also depend on finding the correct driver's side of a car and seeing enough of the
driver, which changes with camera direction and country. The available training pictures are
close-ups and do not match the project's road-video view, while the test set does not include
the no-seatbelt class.
