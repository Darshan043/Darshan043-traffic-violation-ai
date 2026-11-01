# Stage 2: Basic computer vision experiments

## Test setup

- Video: `data/videos/test_road.mp4` (1920x1080, 50 FPS, 2,858 frames)
- Device: NVIDIA GeForce RTX 2050 GPU, PyTorch CUDA 13.2 (`torch.cuda.is_available() == True`)
- Model: `yolo26n.pt`, except for the model comparison
- Unless varied in a table, settings were confidence 0.35, image size 640, and skip 1.

Average FPS is the number of frames sent to the model divided by time spent in model inference.
It excludes model loading, video decoding, and display time. Detection counts are detections across
all processed frames; the same vehicle may be counted again in later frames, so these are not counts
of unique vehicles.

## Confidence threshold

| Confidence | Average FPS | Car detections | Motorcycle detections | Bus detections | Truck detections |
|---:|---:|---:|---:|---:|---:|
| 0.10 | 44.76 | 52,181 | 800 | 11,135 | 25,638 |
| 0.35 | 42.71 | 18,008 | 104 | 4,290 | 4,880 |
| 0.70 | 45.24 | 4,406 | 0 | 1,597 | 304 |

## Image size

| Image size | Average FPS | Car detections | Motorcycle detections | Bus detections | Truck detections |
|---:|---:|---:|---:|---:|---:|
| 480 | 45.57 | 15,432 | 44 | 3,757 | 2,279 |
| 640 | 42.71 | 18,008 | 104 | 4,290 | 4,880 |
| 960 | 37.96 | 45,423 | 262 | 7,204 | 6,622 |

## Frame skip

| `--skip` | Frames processed | Average FPS | Car detections | Motorcycle detections | Bus detections | Truck detections |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 2,858 | 42.71 | 18,008 | 104 | 4,290 | 4,880 |
| 2 | 1,429 | 41.50 | 9,004 | 53 | 2,142 | 2,445 |
| 3 | 953 | 22.22 | 6,014 | 37 | 1,427 | 1,612 |

## Model size

| Model | Average FPS | Car detections | Motorcycle detections | Bus detections | Truck detections |
|---|---:|---:|---:|---:|---:|
| `yolo26n.pt` (nano) | 42.71 | 18,008 | 104 | 4,290 | 4,880 |
| `yolo26s.pt` (small) | 45.08 | 38,246 | 897 | 7,771 | 11,228 |

## What to learn

**Caution:** Each setting was measured in a single run. Small FPS differences between settings are
noisy and should not be treated as reliable performance differences.

1. Lowering confidence finds many more possible vehicles, but some extra boxes may be false alarms; raising it removes weaker detections.
2. A larger image size can reveal more small or distant vehicles, but it takes more processing time.
3. `--skip 2` and `--skip 3` process fewer frames, so fast-moving vehicles can pass between the frames that are checked.
4. The small model found more detections than the nano model in this video, but counts alone do not prove which model is more accurate.
