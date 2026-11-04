"""Run helmet/driver association on a video or a folder of still images."""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.association import (Box, HeadDetection, HelmetResult, driver_helmet_result,
                                   pick_driver, riders_for_motorcycle)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
REASONS = ("OK", "NO_RIDER", "DRIVER_UNCLEAR", "NO_HEAD", "TOO_SMALL")


def box_from_xyxy(values) -> Box:
    return Box(*(float(v) for v in values))


def crop_box_to_frame(box: Box, crop_x: int, crop_y: int, scale: float = 1.0) -> Box:
    """Convert a box in a resized crop to full-frame coordinates."""
    return Box(box.x1 / scale + crop_x, box.y1 / scale + crop_y,
               box.x2 / scale + crop_x, box.y2 / scale + crop_y)


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    return inter / max(a.area + b.area - inter, 1e-9)


def analyze_frame(frame, vehicle_model, helmet_model, conf: float, camera_view: str,
                  debug_dir: Path | None = None, debug_limit: int = 20):
    """Shared full detection/association pipeline for a single frame or image."""
    frame_h, frame_w = frame.shape[:2]
    veh = vehicle_model.predict(frame, conf=conf, classes=[0, 3], verbose=False)[0]
    persons: list[Box] = []
    motos: list[Box] = []
    if veh.boxes is not None:
        for b in veh.boxes:
            cls = int(b.cls.item())
            obj = box_from_xyxy(b.xyxy[0].tolist())
            (persons if cls == 0 else motos).append(obj)

    records = []
    crops: list[tuple[object, list[Box], list[HeadDetection], int, int]] = []
    for moto in motos:
        mw, mh = int(round(moto.width)), int(round(moto.height))
        # Clip expanded rider crop to image bounds; slicing uses exclusive right/bottom.
        x1, y1 = max(0, int(moto.x1)), max(0, int(moto.y1 - .60*moto.height))
        x2, y2 = min(frame_w, int(moto.x2)), min(frame_h, int(moto.y2))
        crop = frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else frame[0:0, 0:0]
        all_persons: list[Box] = persons.copy()
        heads: list[HeadDetection] = []
        riders: list[Box] = []
        if mw < 60:
            result = HelmetResult("unclear", 0.0, "TOO_SMALL")
        elif crop.size:
            # Improve person recall for riders occupying only a small part of the frame.
            up_scale = max(1.0, 640.0 / max(crop.shape[1], crop.shape[0]))
            up = cv2.resize(crop, None, fx=up_scale, fy=up_scale, interpolation=cv2.INTER_CUBIC)
            local = vehicle_model.predict(up, conf=conf, classes=[0], verbose=False)[0]
            crop_persons: list[Box] = []
            if local.boxes is not None:
                for pb in local.boxes:
                    candidate = crop_box_to_frame(box_from_xyxy(pb.xyxy[0].tolist()), x1, y1, up_scale)
                    if not any(iou(candidate, old) > .5 for old in all_persons + crop_persons):
                        crop_persons.append(candidate)
            all_persons.extend(crop_persons)
            riders = riders_for_motorcycle(moto, all_persons)  # 50%-inside association rule
            pred = helmet_model.predict(crop, conf=conf, verbose=False)[0]
            if pred.boxes is not None:
                for b in pred.boxes:
                    cls = int(b.cls.item())
                    name = str(helmet_model.names[cls]).lower().replace(" ", "_")
                    if name in ("helmet", "no_helmet"):
                        heads.append(HeadDetection(crop_box_to_frame(box_from_xyxy(b.xyxy[0].tolist()), x1, y1),
                                                   name, float(b.conf.item())))
            result = driver_helmet_result(moto, all_persons, heads, camera_view)
        else:
            result = HelmetResult("unclear", 0.0, "NO_RIDER")
        driver = pick_driver(riders, camera_view)
        color = {"helmet": (30, 220, 30), "no_helmet": (30, 30, 240), "unclear": (0, 220, 255)}[result.label]
        cv2.rectangle(frame, (int(moto.x1), int(moto.y1)), (int(moto.x2), int(moto.y2)), (255, 150, 30), 2)
        if driver:
            cv2.rectangle(frame, (int(driver.x1), int(driver.y1)), (int(driver.x2), int(driver.y2)), color, 4)
        cv2.putText(frame, f"{result.label.upper()} {result.confidence:.2f}",
                    (int(moto.x1), max(25, int(moto.y1)-8)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
        records.append({"moto": moto, "label": result.label, "reason": result.reason,
                        "confidence": result.confidence, "driver": driver})
        crops.append((crop, all_persons, heads, x1, y1))

    if debug_dir is not None:
        saved = 0
        for record, (crop, all_persons, heads, x1, y1) in zip(records, crops):
            if saved >= debug_limit or not crop.size:
                break
            preview = crop.copy()
            if record["reason"] != "TOO_SMALL":
                for person in all_persons:
                    cv2.rectangle(preview, (int(person.x1-x1), int(person.y1-y1)),
                                  (int(person.x2-x1), int(person.y2-y1)), (0,255,0), 2)
                    cv2.putText(preview, "person", (int(person.x1-x1), max(15,int(person.y1-y1))),
                                cv2.FONT_HERSHEY_SIMPLEX, .45, (0,255,0), 1)
            for head in heads:
                b = head.box
                cv2.rectangle(preview, (int(b.x1-x1),int(b.y1-y1)), (int(b.x2-x1),int(b.y2-y1)), (255,0,255), 2)
                cv2.putText(preview, f"{head.label} {head.confidence:.2f}",
                            (int(b.x1-x1), max(14,int(b.y1-y1))), cv2.FONT_HERSHEY_SIMPLEX, .42,(255,0,255),1)
            cv2.putText(preview, record["reason"], (4,max(15,preview.shape[0]-6)),
                        cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,255),1)
            cv2.imwrite(str(debug_dir / f"crop_{saved+1:02d}.jpg"), preview)
            saved += 1
    return frame, records


def report(records):
    counts, reasons = Counter(), Counter()
    for r in records:
        counts[r["label"]] += 1
        reasons[r["reason"]] += 1
    return counts, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "data" / "videos" / "helmet_test.mp4")
    parser.add_argument("--images", type=Path, help="Process all supported still images in this folder")
    parser.add_argument("--max-images", type=int, default=0, help="Maximum still images to process; 0 means all")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "output" / "image_check")
    parser.add_argument("--helmet-model", type=Path, default=ROOT / "models" / "helmet" / "helmet_v1.pt")
    parser.add_argument("--vehicle-model", type=Path, default=ROOT / "models" / "pretrained" / "yolo26n.pt")
    parser.add_argument("--camera-view", choices=("approaching", "receding"), default="approaching")
    parser.add_argument("--conf", type=float, default=.40)
    parser.add_argument("--skip", type=int, default=1)
    parser.add_argument("--scale", type=float, default=.5)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    from ultralytics import YOLO

    vehicle_model, helmet_model = YOLO(str(args.vehicle_model)), YOLO(str(args.helmet_model))
    vehicle_names = vehicle_model.names
    if str(vehicle_names[0]).lower() != "person" or str(vehicle_names[3]).lower() != "motorcycle":
        raise ValueError(f"Expected COCO IDs person=0 and motorcycle=3; model names are {vehicle_names}")

    if args.images:
        if not args.images.is_dir():
            raise FileNotFoundError(args.images)
        paths = sorted(p for p in args.images.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if args.max_images > 0:
            paths = paths[:args.max_images]
        if not paths:
            raise ValueError(f"No supported images found in {args.images}")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        debug_dir = ROOT / "data" / "output" / "debug_crops" if args.debug else None
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
        aggregate = []
        for index, path in enumerate(paths):
            image = cv2.imread(str(path))
            if image is None:
                print(f"SKIP unreadable: {path.name}")
                continue
            annotated, records = analyze_frame(image, vehicle_model, helmet_model, args.conf,
                                               args.camera_view, debug_dir)
            cv2.imwrite(str(args.output_dir / path.name), annotated)
            aggregate.extend(records)
            c, rs = report(records)
            print(f"{path.name}: motorcycles={len(records)} helmet={c['helmet']} no_helmet={c['no_helmet']} "
                  f"unclear={c['unclear']} reasons=" + ",".join(f"{key}:{rs[key]}" for key in REASONS))
        counts, reasons = report(aggregate)
        print(f"Image summary: images={len(paths)} motorcycles={len(aggregate)} helmet={counts['helmet']} "
              f"no_helmet={counts['no_helmet']} unclear={counts['unclear']}")
        print("Reason histogram: " + ", ".join(f"{key}={reasons[key]}" for key in REASONS))
        print(f"Annotated images saved to {args.output_dir}")
        return

    video = args.video
    if not video.exists() and video.name == "helmet_test.mp4":
        video = ROOT / "data" / "videos" / "test_road.mp4"
        print(f"WARNING: helmet_test.mp4 is missing; using {video}.")
    if not video.exists():
        raise FileNotFoundError(video)
    cap = cv2.VideoCapture(str(video))
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_w, frame_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    if args.save:
        out = ROOT / "data" / "output" / "s3_helmet_demo.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps_in,
                                 (max(1,int(frame_w*args.scale)),max(1,int(frame_h*args.scale))))
    all_records = []
    frame_count = total_seen = 0
    started = time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        total_seen += 1
        if (total_seen-1) % max(1,args.skip):
            continue
        debug_dir = ROOT / "data" / "output" / "debug_crops" if args.debug else None
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
        frame, records = analyze_frame(frame, vehicle_model, helmet_model, args.conf, args.camera_view, debug_dir)
        all_records.extend(records)
        frame_count += 1
        elapsed = max(.001,time.perf_counter()-started)
        cv2.putText(frame,f"FPS {frame_count/elapsed:.1f}",(20,35),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,255,255),2)
        if writer:
            writer.write(cv2.resize(frame,(max(1,int(frame_w*args.scale)),max(1,int(frame_h*args.scale)))))
        if not args.no_show:
            cv2.imshow("Stage 3 Helmet Demo",cv2.resize(frame,(max(1,int(frame_w*args.scale)),max(1,int(frame_h*args.scale)))))
            if cv2.waitKey(1)&0xFF==ord("q"):
                break
        if args.max_frames and frame_count>=args.max_frames:
            break
    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    counts,reasons=report(all_records)
    print(f"Summary: frames={frame_count}, motorcycles_seen={len(all_records)}, helmet={counts['helmet']}, "
          f"no_helmet={counts['no_helmet']}, unclear={counts['unclear']}")
    if args.debug:
        print("Reason histogram: "+", ".join(f"{key}={reasons[key]}" for key in REASONS))


if __name__ == "__main__":
    main()
