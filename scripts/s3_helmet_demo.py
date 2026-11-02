"""Run the Stage 3 helmet detector with motorcycle-driver association on a video."""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.association import (Box, HeadDetection, HelmetResult, driver_helmet_result,
                                   pick_driver, riders_for_motorcycle)


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
    parser.add_argument("--debug", action="store_true", help="Print association diagnostics and save up to 20 crops")
    args = parser.parse_args()
    video = args.video
    if not video.exists() and video.name == "helmet_test.mp4":
        video = ROOT / "data" / "videos" / "test_road.mp4"
        print(f"WARNING: helmet_test.mp4 is missing; using {video}.")
    if not video.exists():
        raise FileNotFoundError(video)
    vehicle_model, helmet_model = YOLO(str(args.vehicle_model)), YOLO(str(args.helmet_model))
    # COCO IDs: person=0, motorcycle=3. Fail clearly if a different model is supplied.
    vehicle_names = vehicle_model.names
    if str(vehicle_names[0]).lower() != "person" or str(vehicle_names[3]).lower() != "motorcycle":
        raise ValueError(f"Expected COCO IDs person=0 and motorcycle=3; model names are {vehicle_names}")
    cap = cv2.VideoCapture(str(video))
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_w, frame_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    if args.save:
        out = ROOT / "data" / "output" / "s3_helmet_demo.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps_in,
                                 (max(1, int(frame_w*args.scale)), max(1, int(frame_h*args.scale))))
    counts, reasons = Counter(), Counter()
    motorcycles = associated_people = motos_with_heads = total_seen = processed = 0
    moto_sizes: list[tuple[int, int]] = []
    crop_sizes: list[tuple[int, int]] = []
    debug_dir = ROOT / "data" / "output" / "debug_crops"
    if args.debug:
        debug_dir.mkdir(parents=True, exist_ok=True)
    debug_saved = 0
    started = time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        total_seen += 1
        if (total_seen - 1) % max(1, args.skip):
            continue
        veh = vehicle_model.predict(frame, conf=args.conf, classes=[0, 3], verbose=False)[0]
        persons: list[Box] = []
        motos: list[Box] = []
        if veh.boxes is not None:
            for b in veh.boxes:
                cls = int(b.cls.item())
                obj = box_from_xyxy(b.xyxy[0].tolist())
                (persons if cls == 0 else motos).append(obj)
        motorcycles += len(motos)
        for moto in motos:
            mw, mh = int(round(moto.width)), int(round(moto.height))
            moto_sizes.append((mw, mh))
            # Crop bounds are clipped to the image before slicing (right/bottom exclusive).
            ex1, ey1 = moto.x1, moto.y1 - .60 * moto.height
            x1, y1 = max(0, int(ex1)), max(0, int(ey1))
            x2, y2 = min(frame_w, int(moto.x2)), min(frame_h, int(moto.y2))
            crop = frame[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else frame[0:0, 0:0]
            cw, ch = (crop.shape[1], crop.shape[0]) if crop.size else (0, 0)
            crop_sizes.append((cw, ch))
            if mw < 60:
                result = HelmetResult("unclear", 0.0, "TOO_SMALL")
                heads: list[HeadDetection] = []
                riders: list[Box] = []
            elif crop.size:
                # Small motorcycles make the corresponding rider tiny in the full frame.
                # Upscale the clipped crop and run only the person class there as well.
                up_scale = max(1.0, 640.0 / max(cw, ch))
                up = cv2.resize(crop, None, fx=up_scale, fy=up_scale, interpolation=cv2.INTER_CUBIC)
                local_result = vehicle_model.predict(up, conf=args.conf, classes=[0], verbose=False)[0]
                crop_persons: list[Box] = []
                if local_result.boxes is not None:
                    for pb in local_result.boxes:
                        q = pb.xyxy[0].tolist()
                        candidate = crop_box_to_frame(box_from_xyxy(q), x1, y1, up_scale)
                        if not any(iou(candidate, old) > .5 for old in persons + crop_persons):
                            crop_persons.append(candidate)
                all_persons = persons + crop_persons
                riders = riders_for_motorcycle(moto, all_persons)
                if riders:
                    associated_people += 1
                pred = helmet_model.predict(crop, conf=args.conf, verbose=False)[0]
                heads = []
                if pred.boxes is not None:
                    for b in pred.boxes:
                        cls = int(b.cls.item())
                        name = str(helmet_model.names[cls]).lower().replace(" ", "_")
                        if name not in ("helmet", "no_helmet"):
                            continue
                        q = b.xyxy[0].tolist()
                        # Helmet model boxes are crop-relative: restore full-frame origin.
                        heads.append(HeadDetection(crop_box_to_frame(box_from_xyxy(q), x1, y1), name,
                                                   float(b.conf.item())))
                if heads:
                    motos_with_heads += 1
                result = driver_helmet_result(moto, all_persons, heads, args.camera_view)
            else:
                result = HelmetResult("unclear", 0.0, "NO_RIDER")
                heads, riders = [], []
            reasons[result.reason] += 1
            counts[result.label] += 1
            driver = pick_driver(riders, args.camera_view)
            color = {"helmet": (30, 220, 30), "no_helmet": (30, 30, 240), "unclear": (0, 220, 255)}[result.label]
            cv2.rectangle(frame, (int(moto.x1), int(moto.y1)), (int(moto.x2), int(moto.y2)), (255, 150, 30), 2)
            if driver:
                cv2.rectangle(frame, (int(driver.x1), int(driver.y1)), (int(driver.x2), int(driver.y2)), color, 4)
            cv2.putText(frame, f"{result.label.upper()} {result.confidence:.2f}",
                        (int(moto.x1), max(25, int(moto.y1)-8)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
            if args.debug and debug_saved < 20 and crop.size:
                preview = crop.copy()
                for person in all_persons if mw >= 60 and crop.size else []:
                    cv2.rectangle(preview, (int(person.x1-x1), int(person.y1-y1)),
                                  (int(person.x2-x1), int(person.y2-y1)), (0, 255, 0), 2)
                    cv2.putText(preview, "person", (int(person.x1-x1), max(15, int(person.y1-y1))),
                                cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 0), 1)
                for head in heads:
                    hb = head.box
                    cv2.rectangle(preview, (int(hb.x1-x1), int(hb.y1-y1)),
                                  (int(hb.x2-x1), int(hb.y2-y1)), (255, 0, 255), 2)
                    cv2.putText(preview, f"{head.label} {head.confidence:.2f}",
                                (int(hb.x1-x1), max(14, int(hb.y1-y1))), cv2.FONT_HERSHEY_SIMPLEX, .42,
                                (255, 0, 255), 1)
                cv2.putText(preview, result.reason, (4, max(15, preview.shape[0]-6)),
                            cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 255), 1)
                cv2.imwrite(str(debug_dir / f"crop_{debug_saved+1:02d}.jpg"), preview)
                debug_saved += 1
        processed += 1
        elapsed = max(.001, time.perf_counter()-started)
        cv2.putText(frame, f"FPS {processed/elapsed:.1f}", (20, 35), cv2.FONT_HERSHEY_SIMPLEX, .8, (0,255,255), 2)
        if writer:
            writer.write(cv2.resize(frame, (max(1,int(frame_w*args.scale)), max(1,int(frame_h*args.scale)))))
        if not args.no_show:
            cv2.imshow("Stage 3 Helmet Demo", cv2.resize(frame, (max(1,int(frame_w*args.scale)), max(1,int(frame_h*args.scale)))))
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        if args.max_frames and processed >= args.max_frames:
            break
    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    print(f"Summary: frames={processed}, motorcycles_seen={motorcycles}, helmet={counts['helmet']}, "
          f"no_helmet={counts['no_helmet']}, unclear={counts['unclear']}")
    if args.debug:
        med = lambda values: tuple(round(statistics.median(v[i] for v in values), 1) for i in (0, 1)) if values else (0, 0)
        print(f"Debug: motorcycles={motorcycles}; with_person={associated_people}; with_head={motos_with_heads}")
        print("Reason histogram: " + ", ".join(f"{key}={reasons[key]}" for key in
              ("OK", "NO_RIDER", "DRIVER_UNCLEAR", "NO_HEAD", "TOO_SMALL")))
        print(f"Median motorcycle box (w,h)={med(moto_sizes)} px; clipped crop (w,h)={med(crop_sizes)} px")
        print(f"Debug crops saved: {debug_saved} in {debug_dir}")


if __name__ == "__main__":
    main()
