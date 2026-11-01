# Helmet detector model card

- **Model:** YOLO26n, fine-tuned for helmet/head detection (model weights pending the Colab training run).
- **Dataset:** Helmet Detection, Roboflow Universe version 2 — [dataset page](https://universe.roboflow.com/flashys-workspace/helmet-detection-fsrgu/dataset/2).
- **Licence:** CC BY 4.0.
- **Classes:** `helmet` (0), `no_helmet` (1). The source Motorcycle class was dropped.
- **Training configuration:** 640 image size, 100 epochs, batch 8, 2 workers, patience 20. Training is pending; the local RTX 2050 smoke run projected more than three hours for 100 epochs and encountered a Windows page-file issue with 2 workers.
- **Training time and best epoch:** Pending Colab training.
- **Test metrics:** Pending; do not infer accuracy from the one-epoch smoke attempt.
- **Known limits:** Public data may contain near-duplicate video frames. Some inspected labels appear noisy, including a likely bare/capped head labeled helmet. Caps, scarves, small distant heads, occlusion, and passenger/driver assignment need validation on the target camera. Add hard negatives and footage from the intended camera before using this model for decisions.
