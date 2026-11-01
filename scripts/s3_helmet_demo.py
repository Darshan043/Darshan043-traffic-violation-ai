"""Run the Stage 3 helmet detector with motorcycle-driver association on a video."""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.association import Box, HeadDetection, driver_helmet_result, pick_driver, riders_for_motorcycle


def box_from_xyxy(values) -> Box:
    return Box(*(float(v) for v in values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "data" / "videos" / "helmet_test.mp4")
    parser.add_argument("--helmet-model", type=Path, default=ROOT / "models" / "helmet" / "helmet_v1.pt")
    parser.add_argument("--vehicle-model", type=Path, default=ROOT / "models" / "pretrained" / "yolo26n.pt")
    parser.add_argument("--camera-view", choices=("approaching", "receding"), default="approaching")
    parser.add_argument("--conf", type=float, default=.25)
    parser.add_argument("--skip", type=int, default=1)
    parser.add_argument("--scale", type=float, default=.5)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()
    video = args.video
    if not video.exists() and video.name == "helmet_test.mp4":
        video = ROOT / "data" / "videos" / "test_road.mp4"
        print(f"WARNING: helmet_test.mp4 is missing; using {video}. This road clip has very few motorcycles.")
    if not video.exists():
        raise FileNotFoundError(video)
    vehicle_model, helmet_model = YOLO(str(args.vehicle_model)), YOLO(str(args.helmet_model))
    cap = cv2.VideoCapture(str(video))
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_w, frame_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    if args.save:
        out = ROOT / "data" / "output" / "s3_helmet_demo.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps_in,
                                 (max(1, int(frame_w*args.scale)), max(1, int(frame_h*args.scale))))
    counts = Counter(); total_seen = motorcycles = frame_index = processed = 0
    started = time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        total_seen += 1
        if (total_seen - 1) % max(1, args.skip):
            continue
        frame_index += 1
        veh = vehicle_model.predict(frame, conf=args.conf, classes=[0, 3], verbose=False)[0]
        persons: list[Box] = []
        motos: list[Box] = []
        if veh.boxes is not None:
            for b in veh.boxes:
                cls = int(b.cls.item()); obj = box_from_xyxy(b.xyxy[0].tolist())
                (persons if cls == 0 else motos).append(obj)
        motorcycles += len(motos)
        for moto in motos:
            riders = riders_for_motorcycle(moto, persons)
            expanded = Box(moto.x1, moto.y1 - .60*moto.height, moto.x2, moto.y2)
            x1, y1 = max(0, int(expanded.x1)), max(0, int(expanded.y1))
            x2, y2 = min(frame_w, int(expanded.x2)), min(frame_h, int(expanded.y2))
            heads: list[HeadDetection] = []
            if x2 > x1 and y2 > y1:
                preds = helmet_model.predict(frame[y1:y2, x1:x2], conf=args.conf, verbose=False)[0]
                if preds.boxes is not None:
                    for b in preds.boxes:
                        cls = int(b.cls.item())
                        name = str(helmet_model.names[cls]).lower().replace(" ", "_")
                        if name not in ("helmet", "no_helmet"):
                            continue
                        coords = b.xyxy[0].tolist()
                        head_box = Box(coords[0]+x1, coords[1]+y1, coords[2]+x1, coords[3]+y1)
                        heads.append(HeadDetection(head_box, name, float(b.conf.item())))
            result = driver_helmet_result(moto, persons, heads, args.camera_view)
            counts[result.label] += 1
            driver = pick_driver(riders, args.camera_view)
            color = {"helmet": (30, 220, 30), "no_helmet": (30, 30, 240), "unclear": (0, 220, 255)}[result.label]
            cv2.rectangle(frame, (int(moto.x1), int(moto.y1)), (int(moto.x2), int(moto.y2)), (255, 150, 30), 2)
            if driver:
                cv2.rectangle(frame, (int(driver.x1), int(driver.y1)), (int(driver.x2), int(driver.y2)), color, 4)
            text = f"{result.label.upper()} {result.confidence:.2f}"
            cv2.putText(frame, text, (int(moto.x1), max(25, int(moto.y1)-8)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
        elapsed = max(.001, time.perf_counter()-started)
        cv2.putText(frame, f"FPS {frame_index/elapsed:.1f}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, .8, (0,255,255), 2)
        if writer:
            resized = cv2.resize(frame, (max(1,int(frame_w*args.scale)), max(1,int(frame_h*args.scale))))
            writer.write(resized)
        if not args.no_show:
            cv2.imshow("Stage 3 Helmet Demo", cv2.resize(frame, (max(1,int(frame_w*args.scale)), max(1,int(frame_h*args.scale)))))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        processed += 1
        if args.max_frames and processed >= args.max_frames:
            break
    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    print(f"Summary: frames={processed}, motorcycles_seen={motorcycles}, helmet={counts['helmet']}, no_helmet={counts['no_helmet']}, unclear={counts['unclear']}")


if __name__ == "__main__":
    main()
