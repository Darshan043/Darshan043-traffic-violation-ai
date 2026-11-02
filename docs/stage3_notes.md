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

| Predicted \\ True | helmet | no_helmet | background |
|---|---:|---:|---:|
| helmet | 61 | 0 | 23 |
| no_helmet | 0 | 62 | 10 |
| background | 4 | 0 | 0 |

Plots are copied to `docs/stage3/`. The confusion matrix counts use Ultralytics' operating threshold and therefore do not directly reproduce the reported best-confidence precision values.

## Preview review and demo

Twelve validation predictions were saved under `data/output/val_preview/`. The reviewed examples were mostly plausible for obvious helmeted and bare heads, but at least one clearly bare head was called `helmet`. Small/distant heads and ambiguous headwear remain risky; public images also differ from a fixed traffic camera. The generic `test_road.mp4` fallback was used because `helmet_test.mp4` was absent. It processed 2,858 frames and saw 223 motorcycles; all 223 results were `unclear`. Three sampled frames contained no highlighted driver, so that video cannot establish that driver selection or labels work in traffic scenes.

## Limits and next round

The 102-image test split is small, so the scores are likely optimistic. Public datasets often include near-duplicate frames or multiple frames from the same videos; exact hashes found no identical files across splits, but that does not eliminate near-duplicate/video leakage. Add footage from the target camera, more multi-rider examples, and hard negatives such as caps and scarves. Recheck passenger-versus-driver behavior on purposeful two-rider clips. These results do not guarantee field accuracy; Stage 6 remains responsible for final violation decisions.
