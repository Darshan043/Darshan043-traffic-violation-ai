# Seatbelt detector model card

## Model

- **File:** `seatbelt_v1.pt` (local only; model weights are excluded from Git)
- **Architecture/base weights:** YOLO26n, fine-tuned for two classes
- **Classes:** `0 = seatbelt`, `1 = no_seatbelt`
- **Input size:** 640 pixels
- **Training device:** NVIDIA RTX 2050 with CUDA
- **Augmentation constraint:** horizontal flip disabled (`fliplr=0.0`) to preserve driver-side meaning

## Data and training

The prepared training set uses only `datasets/seatbelt_raw/`, with source class 1
(`with-seatbelt`) mapped to `seatbelt` and source class 0 (`Without-seatbelt`) mapped to
`no_seatbelt`. Source data is attributed in `datasets/DATASET_SOURCES.md` and licensed CC BY 4.0.
The images are close-up cabin photos, not CCTV front-view crops; source annotations surround
people or large body regions and are not consistently limited to a driver's upper body.

Training settings: 50 requested epochs, batch 8, workers 0, patience 10, 640 image size,
and `fliplr=0.0`. Early stopping ended training at epoch 26; the best checkpoint was epoch 16.
The final held-out metrics and confidence results are recorded in `docs/stage4_notes.md`.

## Intended use and limitations

This is a beginner project demonstration, not an enforcement or safety system. The test split has
only 30 images and no `no_seatbelt` boxes, so it cannot measure that class's recall and gives a weak
estimate of real-world performance. Training photos are not CCTV crops, and camera angles,
occlusion, visibility, and vehicle layout can change results. The demo assumes a right-side driver
crop for India and does not independently detect whether a driver is present. `UNCLEAR` should be
reviewed rather than treated as a violation.
