# AI-Based Traffic Violation Detection and Monitoring System

Repository: `Darshan043-traffic-violation-ai`.

Goal: Detect traffic violations in road video and help monitor them with computer vision.

## How to run Stage 2

Activate the virtual environment in PowerShell, then run these commands from the project folder:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts\s2_read_video.py
python scripts\s2_detect.py
```

The detection script downloads its default `yolo26n.pt` model into `models/pretrained/` the first
time it runs. To save an annotated copy of the input video, run
`python scripts\s2_detect.py --save`. To test without opening a window, add `--no-show`.
The default video is `data/videos/test_road.mp4`; use `--video PATH` to select another video.
