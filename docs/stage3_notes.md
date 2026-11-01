# Stage 3: Helmet detection

## Dataset preparation

The Roboflow Helmet Detection v2 dataset is stored in `datasets/helmet_raw/` and copied into the standard YOLO layout at `datasets/helmet/`. The original remains untouched. The mapping is `Helmet` (source 0) → `helmet` (0), `No_helmet` (source 2) → `no_helmet` (1); Motorcycle (source 1) is dropped. The generated `data.yaml` uses an absolute path.

The prepared splits contain 4,869 train, 305 validation, and 102 test images. One training image contained only dropped Motorcycle boxes and remains as a background image with an empty label file. Training box counts are helmet 2,927 and no_helmet 3,177, so neither class is below 30% of the other. The audit found 3 boxes under 10 pixels, no missing or orphaned labels, no invalid IDs or boxes, and no byte-identical image hashes across splits. Twelve annotated samples were written to `data/output/label_check/`; six were reviewed. Boxes generally cover the head/helmet, with at least one apparent bare/capped head labeled helmet, indicating annotation noise.

Source and attribution are recorded in `datasets/DATASET_SOURCES.md` (CC BY 4.0).

## Training status

Training uses `yolo26n.pt`, 640 pixels, batch 8, 100 epochs, 2 workers, and patience 20. The RTX 2050 smoke pass reached the end of the training epoch at about 2 minutes, but a Windows worker failed during validation with `WinError 1455` (paging file too small). A zero-worker retry ran at about 2 batches/second and projected to several hours for a full epoch, already beyond the requested three-hour limit. The local run was stopped and `notebooks/helmet_training_colab.ipynb` was created. **No full model training has completed; test metrics, best epoch, training duration, predictions, and demo output are pending.**

## Metrics and errors

| Split/result | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| Test overall | Pending Colab training | Pending | Pending | Pending |
| helmet | Pending | Pending | Pending | Pending |
| no_helmet | Pending | Pending | Pending | Pending |

No confusion matrix or model predictions are available yet. Do not treat the partial smoke run as a trained model or promise a particular accuracy.

## Limits and next steps

Public datasets may include near-duplicate frames and multiple images from the same video, which can make test results optimistic even when exact file hashes do not match. Some label noise is visible in the sample review. The next round should include more footage from the deployment camera, plus hard negatives such as caps and scarves, and should verify driver-only results with two-rider scenes. Stage 6 remains responsible for final violation decisions.
