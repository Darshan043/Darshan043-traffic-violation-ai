"""Track cars, motorcycles, buses, and trucks with Ultralytics trackers."""
from __future__ import annotations

import argparse
import csv
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.tracking import TrackStore, results_to_tracks

VEHICLE_CLASSES = [2, 3, 5, 7]
YOLO = None


def _load_model(model_path: Path):
    model_factory = YOLO
    if model_factory is None:
        from ultralytics import YOLO as model_factory
    return model_factory(str(model_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=ROOT / "models" / "pretrained" / "yolo26n.pt")
    parser.add_argument("--tracker", default=str(ROOT / "ai_engine" / "config" / "botsort_conf_test.yaml"))
    parser.add_argument("--conf", type=float, default=0.30)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--skip", type=int, default=1)
    parser.add_argument("--start-sec", type=float, default=0.0)
    parser.add_argument("--end-sec", type=float)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--csv", nargs="?", const="auto", default=None)
    parser.add_argument("--out", type=Path, help="Optional annotated-video path")
    parser.add_argument("--label-scale", type=float, default=0.8, help="Drawn label size")
    parser.add_argument("--box-thickness", type=int, default=2)
    parser.add_argument("--trail-thickness", type=int, default=2)
    args = parser.parse_args()
    if args.skip < 1:
        parser.error("--skip must be at least 1")
    if args.start_sec < 0 or (args.end_sec is not None and args.end_sec <= args.start_sec):
        parser.error("--end-sec must be greater than --start-sec")
    if not args.video.is_file():
        raise FileNotFoundError(args.video)
    if not args.model.is_file():
        raise FileNotFoundError(args.model)
    if args.tracker not in ("botsort.yaml", "bytetrack.yaml") and not Path(args.tracker).is_file():
        raise FileNotFoundError(f"Tracker config not found: {args.tracker}")

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise OSError(f"Could not open video: {args.video}")
    fps_in = capture.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    start_frame = int(args.start_sec * fps_in)
    end_frame = int(args.end_sec * fps_in) if args.end_sec is not None else None
    out_video = args.out or ROOT / "data" / "output" / f"s5_{args.video.stem}_{Path(args.tracker).stem}.mp4"
    writer = None
    if args.save:
        out_video.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out_video), cv2.VideoWriter_fourcc(*"mp4v"), fps_in,
                                 (max(1, int(width*args.scale)), max(1, int(height*args.scale))))
        if not writer.isOpened():
            capture.release()
            raise OSError(f"Could not create output video: {out_video}")

    # A new model per invocation resets tracker memory and ID allocation for each video/run.
    model = _load_model(args.model)
    print(f"Run config: video={args.video}; tracker={args.tracker}; model={args.model}; "
          f"frames=[{start_frame},{end_frame if end_frame is not None else 'EOF'}); "
          f"conf={args.conf}; imgsz={args.imgsz}; skip={args.skip}; classes={VEHICLE_CLASSES}; "
          f"input_fps={fps_in}")
    store = TrackStore(history_size=60)
    stats: dict[int, dict] = {}
    processed = frame_idx = 0
    started = time.perf_counter()
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        current = frame_idx
        frame_idx += 1
        if current < start_frame:
            continue
        if end_frame is not None and current >= end_frame:
            break
        # --skip 2+ makes tracking less accurate because vehicles move further between
        # updates; use skip 1 unless speed is a problem.
        if current % args.skip:
            continue
        result = model.track(frame, persist=True, tracker=args.tracker, classes=VEHICLE_CLASSES,
                             conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
        tracks = results_to_tracks(result)
        store.update(current, tracks)
        # Lifetime reporting is kept separately in `stats`; clean old geometry/history
        # from the in-memory store after the tracker has had time to bridge an occlusion.
        store.cleanup(current, max_age=120)
        label_rects: list[tuple[int, int, int, int]] = []
        for track in tracks:
            row = stats.setdefault(track.id, {"classes": Counter(), "first": current, "last": current,
                                             "count": 0, "conf": 0.0})
            row["classes"][track.cls] += 1
            row["last"] = current
            row["count"] += 1
            row["conf"] += track.conf
            x1, y1, x2, y2 = map(int, (track.box.x1, track.box.y1, track.box.x2, track.box.y2))
            color = (int((track.id*67)%200+30), int((track.id*37)%200+30), int((track.id*97)%200+30))
            cv2.rectangle(frame, (x1,y1), (x2,y2), color, args.box_thickness)
            class_name = str(result.names.get(track.cls, track.cls))
            text = f"{class_name} #{track.id}"
            (text_w, text_h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX,
                                                          args.label_scale, max(1,args.box_thickness))
            candidates = [(x1, y1-text_h-8), (x1, y2+text_h+baseline+3),
                          (x2+4, y1+text_h), (x1-text_w-4, y1+text_h)]
            label_x, label_y = candidates[0]
            for cx, cy in candidates:
                cx = max(0, min(cx, width-text_w-2))
                cy = max(text_h+2, min(cy, height-baseline-2))
                rect = (cx, cy-text_h-2, cx+text_w+2, cy+baseline+2)
                if not any(rect[0]<r[2] and rect[2]>r[0] and rect[1]<r[3] and rect[3]>r[1]
                           for r in label_rects):
                    label_x, label_y = cx, cy
                    label_rects.append(rect)
                    break
            cv2.putText(frame, text, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX,
                        args.label_scale, color, max(1,args.box_thickness), cv2.LINE_AA)
            points = list(store.history[track.id])[-40:]
            for a, b in zip(points, points[1:]):
                cv2.line(frame, tuple(map(int,a)), tuple(map(int,b)), color, args.trail_thickness)
        processed += 1
        if writer:
            writer.write(cv2.resize(frame, (max(1,int(width*args.scale)),max(1,int(height*args.scale)))))
        if not args.no_show:
            cv2.imshow("Stage 5 vehicle tracking (q to quit)",
                       cv2.resize(frame,(max(1,int(width*args.scale)),max(1,int(height*args.scale)))))
            if cv2.waitKey(1)&0xFF==ord("q"):
                break

    capture.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    elapsed = max(time.perf_counter()-started, 1e-9)
    lengths = [row["count"] for row in stats.values()]
    by_class = Counter()
    records = []
    for track_id, row in stats.items():
        cls_id = row["classes"].most_common(1)[0][0]
        name = str(model.names.get(cls_id, cls_id))
        by_class[name] += 1
        records.append((track_id, name, row))
    mean_length = statistics.mean(lengths) if lengths else 0.0
    median_length = statistics.median(lengths) if lengths else 0.0
    print(f"Summary: frames={processed}, average_fps={processed/elapsed:.2f}, unique_ids_per_class={dict(by_class)}")
    print(f"Mean track length={mean_length:.2f}; median={median_length:.2f}; "
          f"short_tracks_under_10={sum(n<10 for n in lengths)}; single_frame_tracks={sum(n==1 for n in lengths)}")
    if writer:
        print(f"Saved annotated video: {out_video}")
    if args.csv is not None:
        csv_path = ROOT / "data" / "output" / f"s5_{args.video.stem}_{Path(args.tracker).stem}.csv" if args.csv == "auto" else Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as stream:
            output = csv.writer(stream)
            output.writerow(["track_id","class","first_frame","last_frame","frames_seen","mean_conf"])
            for track_id, name, row in sorted(records):
                output.writerow([track_id,name,row["first"],row["last"],row["count"],f"{row['conf']/row['count']:.5f}"])
        print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
