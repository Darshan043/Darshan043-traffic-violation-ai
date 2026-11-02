# Helmet detector model card

- **Model:** YOLO26n, trained on Google Colab; local RTX 2050 training was too slow for a full run.
- **Weights:** `models/helmet/helmet_v1.pt` (kept outside Git).
- **Dataset:** [Roboflow Helmet Detection v2](https://universe.roboflow.com/flashys-workspace/helmet-detection-fsrgu/dataset/2), CC BY 4.0.
- **Classes:** `helmet` (0), `no_helmet` (1). Source `Motorcycle` (1) was dropped; `Helmet` (0) and `No_helmet` (2) were remapped.
- **Training:** 640 image size, up to 40 epochs, batch 16, workers 2, patience 10. The stripped checkpoint does not preserve the actual completed epoch or wall time, so those are unknown.
- **Test split:** 102 images, 127 labeled objects.

| Class | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| Overall | 0.9985 | 0.9692 | 0.9650 | 0.7848 |
| helmet | 0.9980 | 0.9385 | 0.9350 | 0.8165 |
| no_helmet | 0.9990 | 1.0000 | 0.9950 | 0.7531 |

These scores are likely optimistic: 102 test images are a small sample, and public datasets can contain related frames from the same videos across splits. Exact image hashes were checked for cross-split duplicates, but that does not catch near-duplicates. Validation previews included at least one bare head incorrectly predicted as helmet. Small or distant heads, caps, scarves, occlusion, and driver/passenger association need more evaluation. Collect footage from the target camera and hard negatives before operational use; these metrics do not promise field accuracy.
