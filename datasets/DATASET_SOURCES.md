# Dataset sources

## Helmet Detection (Roboflow Universe)

- **URL:** https://universe.roboflow.com/flashys-workspace/helmet-detection-fsrgu/dataset/2
- **Licence:** CC BY 4.0
- **Download date:** 2026-11-01
- **Source classes:** 0 `Helmet`, 1 `Motorcycle`, 2 `No_helmet`
- **Mapping:** `Helmet` (0) → `helmet` (0); `No_helmet` (2) → `no_helmet` (1); `Motorcycle` (1) dropped because the pretrained vehicle model already detects motorcycles.
- **Known limits:** Public data may contain near-duplicate frames or images from the same video across splits. Motorcycle-only boxes become background images. The `no_helmet` labels are assumed to bound the head as expected by the project; sample previews should be checked before training. CC BY 4.0 attribution applies.
