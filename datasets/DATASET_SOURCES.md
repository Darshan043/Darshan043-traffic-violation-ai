# Dataset sources

## Helmet Detection (Roboflow Universe)

- **URL:** https://universe.roboflow.com/flashys-workspace/helmet-detection-fsrgu/dataset/2
- **Licence:** CC BY 4.0
- **Download date:** 2026-11-01
- **Source classes:** 0 `Helmet`, 1 `Motorcycle`, 2 `No_helmet`
- **Mapping:** `Helmet` (0) → `helmet` (0); `No_helmet` (2) → `no_helmet` (1); `Motorcycle` (1) dropped because the pretrained vehicle model already detects motorcycles.
- **Known limits:** Public data may contain near-duplicate frames or images from the same video across splits. Motorcycle-only boxes become background images. The `no_helmet` labels are assumed to bound the head as expected by the project; sample previews should be checked before training. CC BY 4.0 attribution applies.

## Seatbelt datasets

These datasets were inspected locally on 2026-11-02. Keep their source archives and
original labels unchanged; the prepared training set will be a separate directory.

| Local directory | Source URL | Licence | Local export/inspection date |
|---|---|---|---|
| `seatbelt_raw/` (Seatbelt-detection v1) | https://universe.roboflow.com/recommendationsystemlivecamerafeed/seatbelt-detection-4plfy/dataset/1 | CC BY 4.0 | 2026-11-02 |
| `seatbelt_raw2/` (testing1 v5) | https://universe.roboflow.com/skrpis/testing1-c0l3z/dataset/5 | CC BY 4.0 | 2026-11-02 |

Both sources are provided by Roboflow users. The first export reports 1,186 images and
three augmented versions of source images; the second reports 10 files but only four
unique filename source prefixes, with one validation image and no test split. Source-prefix
checks for the first dataset found no overlaps between train, validation, and test.
Preserve attribution and CC BY 4.0 terms when redistributing any derived dataset.
