"""Measure horizontal crossing lines for each available video."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
import statistics
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LINES = (0.5, 0.6, 0.7, 0.8, 0.9)
VEHICLE_CLASSES = {2: "car", 3: "motorcycle"}


def crossed_horizontal(previous_y: float, current_y: float, line_y: float) -> bool:
    """Return whether consecutive bottom-centre anchors crossed a horizontal line."""
    return (previous_y < line_y <= current_y) or (current_y < line_y <= previous_y)


def summarize_candidate(track_records: dict[int, dict], line_y: float, height: int) -> dict:
    crossing_heights = []
    crossing_ids = set()
    for track_id, record in track_records.items():
        points = record["points"]
        for previous, current in zip(points, points[1:]):
            y_line = line_y * height
            if crossed_horizontal(previous[1], current[1], y_line):
                crossing_ids.add(track_id)
                crossing_heights.append(current[2])
                break
    return {
        "vehicles_tracked": len(track_records),
        "line_y": line_y,
        "vehicles_crossing": len(crossing_ids),
        "median_crossing_height_px": statistics.median(crossing_heights) if crossing_heights else 0,
        "crossing_vehicles_at_least_120px": sum(value >= 120 for value in crossing_heights),
        "crossing_track_ids": sorted(crossing_ids),
    }


def analyze_video(video: Path, output_dir: Path) -> dict:
    from ai_engine.config import load_config
    from ai_engine.tracking import results_to_tracks

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise OSError(f"Could not open video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, first_frame = capture.read()
    capture.release()
    if not ok:
        raise OSError(f"Video has no decodable first frame: {video}")

    config = load_config()
    from ultralytics import YOLO

    model = YOLO(str(config.paths.vehicle_model))
    records: dict[int, dict] = {}
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        capture.release()
        raise OSError(f"Could not reopen video: {video}")
    frame_idx = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        result = model.track(
            frame, persist=True, tracker=str(config.paths.tracker), classes=list(VEHICLE_CLASSES),
            conf=config.camera.vehicle_conf, imgsz=config.camera.imgsz, verbose=False,
        )[0]
        tracks = results_to_tracks(result)
        del result
        for track in tracks:
            if track.cls not in VEHICLE_CLASSES:
                continue
            entry = records.setdefault(track.id, {
                "track_id": track.id, "vehicle_type": VEHICLE_CLASSES[track.cls],
                "first_frame": frame_idx, "last_frame": frame_idx, "points": [],
            })
            entry["last_frame"] = frame_idx
            entry["points"].append((track.anchor[0], track.anchor[1], track.box.height))
        frame_idx += 1
    capture.release()
    if frame_idx != expected_frames:
        raise OSError(
            f"Incomplete zone scan for {video.name}: decoded {frame_idx} of "
            f"{expected_frames} frames; rerun after closing memory-heavy applications."
        )

    candidates = [summarize_candidate(records, line, height) for line in LINES]
    chosen = max(candidates, key=lambda row: (
        row["crossing_vehicles_at_least_120px"], row["vehicles_crossing"],
        row["median_crossing_height_px"],
    ))
    no_crossing = []
    crossing_ids = set(chosen["crossing_track_ids"])
    for track_id, record in sorted(records.items()):
        if track_id not in crossing_ids:
            no_crossing.append({
                "video": video.name, "time_sec": round(record["last_frame"] / fps, 3),
                "track_id": track_id, "vehicle_type": record["vehicle_type"],
            })

    annotated = first_frame.copy()
    for line in LINES:
        y = int(round(line * height))
        color = (0, 255, 0) if line == chosen["line_y"] else (100, 160, 255)
        cv2.line(annotated, (0, y), (width - 1, y), color, 3 if line == chosen["line_y"] else 1)
        cv2.putText(annotated, f"y={line:.1f}" + (" chosen" if line == chosen["line_y"] else ""),
                    (12, max(22, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
    image_path = output_dir / f"zone_lines_{video.stem}.jpg"
    if not cv2.imwrite(str(image_path), annotated):
        raise OSError(f"Could not write line preview: {image_path}")
    return {
        "video": video.name, "fps": fps, "width": width, "height": height,
        "frames_processed": frame_idx,
        "vehicles_tracked": len(records), "candidates": candidates,
        "recommended_zone_y": chosen["line_y"],
        "vehicles_never_crossing": no_crossing,
        "line_image": str(image_path),
    }


def main() -> None:
    output_dir = ROOT / "data" / "output" / "s6_review_v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    videos_dir = ROOT / "data" / "videos"
    videos = sorted(path for path in videos_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm"})
    reports = [analyze_video(path, output_dir) for path in videos]
    report_path = output_dir / "zone_report.json"
    report_path.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    never_path = output_dir / "vehicles_never_crossed.csv"
    fields = ("video", "time_sec", "track_id", "vehicle_type")
    with never_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            writer.writerows(report["vehicles_never_crossing"])
    for report in reports:
        print(f"\n{report['video']}: tracked={report['vehicles_tracked']}; "
              f"recommended y={report['recommended_zone_y']:.1f}")
        for row in report["candidates"]:
            print(f"  y={row['line_y']:.1f}: tracked={row['vehicles_tracked']}; "
                  f"crossing={row['vehicles_crossing']}; "
                  f"median_height={row['median_crossing_height_px']:.1f}px; "
                  f">=120px={row['crossing_vehicles_at_least_120px']}")
        print(f"  never crossing chosen line: {len(report['vehicles_never_crossing'])}; "
              f"line preview: {report['line_image']}")
    print(f"Report: {report_path}; never-crossing CSV: {never_path}")


if __name__ == "__main__":
    main()
