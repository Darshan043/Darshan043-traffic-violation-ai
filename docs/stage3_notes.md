# Stage 3: Helmet detection

## Dataset and mapping

Roboflow Helmet Detection v2 was prepared with the original data left unchanged. Source `Helmet` (0) maps to `helmet` (0), `No_helmet` (2) maps to `no_helmet` (1), and `Motorcycle` (1) is dropped. Splits contain 4,869 train, 305 validation, and 102 test images. One training image with only dropped motorcycle boxes remains as a background image. The source has CC BY 4.0 terms; attribution is in `datasets/DATASET_SOURCES.md`.

## Training

The final YOLO26n weights were trained on Google Colab, for up to 40 epochs at 640 pixels, batch 16, workers 2, patience 10. The local RTX 2050 run was too slow for full training; the batch-8/worker issue also encountered Windows `WinError 1455`. Exact completed epoch and training wall time are not stored in the stripped checkpoint and are unknown.

## Test results

Evaluation used 102 test images and 127 objects.

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| Overall | 0.9985 | 0.9692 | 0.9650 | 0.7848 |
| helmet | 0.9980 | 0.9385 | 0.9350 | 0.8165 |
| no_helmet | 0.9990 | 1.0000 | 0.9950 | 0.7531 |

Confusion matrix (rows are predicted classes, columns are true classes; background is the final row/column):

| Predicted \\ True at evaluator default conf=0.001 | helmet | no_helmet | background |
|---|---:|---:|---:|
| helmet | 61 | 0 | 23 |
| no_helmet | 0 | 62 | 10 |
| background | 4 | 0 | 0 |

At this low default threshold there are 33 background false-positive boxes (23 helmet + 10 no_helmet) and 4 missed helmet objects. At demo confidence 0.25 these background false boxes disappeared on this test set. The matrix counts at a fixed threshold do not directly reproduce Ultralytics' best-confidence precision/recall summary. Plots are copied to `docs/stage3/`.

### Confidence threshold check

| Confidence | Precision | Recall | Background false-positive boxes |
|---:|---:|---:|---:|
| 0.25 | 1.0000 | 0.9692 | 0 |
| 0.40 | 1.0000 | 0.9692 | 0 |
| 0.50 | 1.0000 | 0.9692 | 0 |

Recommend `0.25` as the initial demo and pipeline threshold: the held-out set showed no recall loss versus the higher thresholds, while avoiding the low-threshold false boxes. The set is small, so this is only a starting point; later multi-frame voting should smooth isolated predictions.

## Preview review and demo

Twelve validation predictions were saved under `data/output/val_preview/`. The reviewed examples were mostly plausible for obvious helmeted and bare heads, but at least one clearly bare head was called `helmet`. Small/distant heads and ambiguous headwear remain risky; public images also differ from a fixed traffic camera.

The initial `test_road.mp4` demo saw 223 motorcycles: 35 had a matched person, 0 had a helmet-model head, and the reason histogram was `TOO_SMALL=138`, `NO_RIDER=50`, `NO_HEAD=35`, `DRIVER_UNCLEAR=0`, `OK=0`. Median motorcycle box size was 52×76 px, below the new 60-pixel width guard. The fix runs person detection again on an upscaled, clipped motorcycle/rider crop. The COCO vehicle IDs are verified as person=0 and motorcycle=3; crop-relative head/person predictions are translated back to full-frame coordinates. Person association retains the 50%-inside rule.

On the newly added `helmet_test.mp4`, the fixed demo processed 240 frames and saw 182 motorcycle detections: 181 had a matched person, 175 had a helmet-model head; reason histogram `OK=175`, `NO_RIDER=1`, `DRIVER_UNCLEAR=1`, `NO_HEAD=5`, `TOO_SMALL=0`. Labels were helmet=175, no_helmet=0, unclear=7. Five saved frames were reviewed: in the three frames with the large rider visible, the driver/person box and helmet label looked right; two sampled frames had no rider in view. Overlapping motorcycle boxes/labels were visible in one sample. This clip contains no bare-headed rider, so it cannot validate `no_helmet` decisions.

## Limits and next round

The 102-image test split is small, so the scores are likely optimistic. Public datasets often include near-duplicate frames or multiple frames from the same videos; exact hashes found no identical files across splits, but that does not eliminate near-duplicate/video leakage. Add footage from the target camera, more multi-rider examples, and hard negatives such as caps and scarves. Recheck passenger-versus-driver behavior on purposeful two-rider clips. These results do not guarantee field accuracy; Stage 6 remains responsible for final violation decisions.
