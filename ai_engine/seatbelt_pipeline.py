"""Car-only Stage 6 flow: observe, cross zone, vote, emit a seatbelt decision."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cv2

from ai_engine.accumulator import Accumulator, TrackMemory
from ai_engine.association import Box
from ai_engine.config import EngineConfig
from ai_engine.decision import decide, kind_of
from ai_engine.evidence import EvidenceWriter
from ai_engine.seatbelt import (
    SeatbeltDetection,
    SeatbeltResult,
    car_driver_crop,
    guard_no_seatbelt_result,
    seatbelt_result,
)
from ai_engine.tracking import Track, results_to_tracks
from ai_engine.video_source import VideoSource
from ai_engine.zone import Zone

try:
    from ultralytics import YOLO
except Exception:  # pragma: no cover - only for import-time safety in minimal envs
    YOLO = None


@dataclass(frozen=True)
class SeatbeltAnalysis:
    """One car's seatbelt observation plus the driver-side crop used."""

    track: Track
    result: SeatbeltResult
    driver_crop: Box | None
    crop_box: Box
    detections: tuple[SeatbeltDetection, ...]


class SeatbeltDetector:
    """Load the vehicle and seatbelt detectors and return tracked cars."""

    def __init__(self, config: EngineConfig, vehicle_model=None, seatbelt_model=None) -> None:
        self.config = config
        if YOLO is None:
            raise RuntimeError("ultralytics is required for the seatbelt pipeline")
        self.vehicle_model = vehicle_model if vehicle_model is not None else YOLO(str(config.paths.vehicle_model))
        self.seatbelt_model = seatbelt_model if seatbelt_model is not None else YOLO(str(config.paths.seatbelt_model))
        if getattr(self.config.camera, "device", None):
            self.vehicle_model.to(self.config.camera.device)
            self.seatbelt_model.to(self.config.camera.device)

    def track_cars(self, frame) -> list[Track]:
        result = self.vehicle_model.track(
            frame,
            persist=True,
            tracker=str(self.config.paths.tracker),
            classes=[2],
            conf=self.config.camera.vehicle_conf,
            imgsz=self.config.camera.imgsz,
            verbose=False,
        )[0]
        return [track for track in results_to_tracks(result) if track.cls == 2]

    def seatbelt_observation(self, frame, track: Track) -> SeatbeltAnalysis:
        car_box = track.box
        crop_box = car_driver_crop(
            car_box,
            self.config.camera.driver_side,
            min_height=self.config.camera.min_car_height,
        )
        if crop_box is None:
            return SeatbeltAnalysis(track, SeatbeltResult("unclear", 0.0, "TOO_SMALL"), None, car_box, ())

        left = max(0, int(crop_box.x1))
        top = max(0, int(crop_box.y1))
        right = min(frame.shape[1], int(crop_box.x2))
        bottom = min(frame.shape[0], int(crop_box.y2))
        local_crop = Box(0.0, 0.0, float(right - left), float(bottom - top))
        if right <= left or bottom <= top:
            return SeatbeltAnalysis(track, SeatbeltResult("unclear", 0.0, "TOO_SMALL"), crop_box, crop_box, ())

        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return SeatbeltAnalysis(track, SeatbeltResult("unclear", 0.0, "TOO_SMALL"), crop_box, crop_box, ())

        seat_result = self.seatbelt_model.predict(
            crop,
            conf=self.config.camera.seatbelt_conf,
            imgsz=self.config.camera.imgsz,
            verbose=False,
        )[0]
        detections: list[SeatbeltDetection] = []
        if seat_result.boxes is not None:
            for item in seat_result.boxes:
                class_id = int(item.cls.item())
                label = str(self.seatbelt_model.names[class_id]).strip().lower().replace("-", "_").replace(" ", "_")
                if label not in ("seatbelt", "no_seatbelt"):
                    continue
                x1, y1, x2, y2 = (float(value) for value in item.xyxy[0].tolist())
                detections.append(
                    SeatbeltDetection(
                        Box(x1, y1, x2, y2),
                        label,
                        float(item.conf.item()),
                    )
                )

        decision = seatbelt_result(detections, local_crop, driver_present=True, min_confidence=0.40)
        decision = guard_no_seatbelt_result(
            decision,
            camera_view=self.config.camera.camera_view,
            crop_height=crop_box.height,
        )
        return SeatbeltAnalysis(track, decision, crop_box, crop_box, tuple(detections))


def _draw(frame, zone: Zone, analyses: list[SeatbeltAnalysis], memories: dict[int, TrackMemory]):
    points = [(int(x), int(y)) for x, y in zone.vertices]
    if zone.is_line:
        cv2.line(frame, points[0], points[1], (255, 255, 0), 2)
    else:
        import numpy as np
        cv2.polylines(frame, [np.asarray(points, dtype="int32")], True, (255, 255, 0), 2)

    colors = {"seatbelt": (40, 220, 40), "no_seatbelt": (40, 50, 240), "unclear": (0, 220, 255)}
    for analysis in analyses:
        track = analysis.track
        result = analysis.result
        color = colors[result.label]
        x1, y1, x2, y2 = map(int, (track.box.x1, track.box.y1, track.box.x2, track.box.y2))
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 150, 20), 2)
        cv2.putText(frame, f"car #{track.id}", (x1, max(18, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 200, 80), 1)
        cv2.putText(frame, f"class={track.cls}", (x1, max(34, y1 - 2)),
                    cv2.FONT_HERSHEY_SIMPLEX, .38, (255, 255, 255), 1)
        if analysis.driver_crop is not None:
            dc = analysis.driver_crop
            cv2.rectangle(
                frame,
                (int(dc.x1), int(dc.y1)),
                (int(dc.x2), int(dc.y2)),
                color,
                1,
            )
        memory = memories.get(track.id)
        final = " FINAL" if memory and memory.finalized else ""
        cv2.putText(
            frame,
            f"latest: {result.label.upper()} {result.confidence:.2f}{final}",
            (x1, max(52, y1 + 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            color,
            2,
        )
        cv2.putText(
            frame,
            f"seatbelt: {result.label}",
            (x1, max(70, y1 + 24)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.36,
            color,
            1,
        )
    return frame


def process_cars(
    video_path: str,
    config: EngineConfig,
    on_event: Callable[[dict[str, Any]], None],
    *,
    detector: SeatbeltDetector | None = None,
    on_frame: Callable[[int, Any], None] | None = None,
    on_transfer: Callable[[dict[str, Any]], None] | None = None,
    on_crossing: Callable[[dict[str, Any]], None] | None = None,
    on_track: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Any = None,
) -> list[dict[str, Any]]:
    """Process a video and emit one seatbelt decision per car zone crossing."""
    detector = detector or SeatbeltDetector(config)
    camera = config.camera
    source = VideoSource(video_path, camera.frame_skip,
                         start_sec=config.start_sec, end_sec=config.end_sec)
    zone: Zone | None = None
    memory = Accumulator(max_age=max(config.accumulator_max_age, config.lost_grace_frames))
    evidence = EvidenceWriter(config.paths.evidence_dir)
    events: list[dict[str, Any]] = []
    frames_processed = cars_seen = observations_added = crossings = 0

    for frame_idx, frame in source.frames():
        if stop_event is not None and stop_event.is_set():
            break
        frames_processed += 1
        if zone is None:
            zone = Zone(camera.zone, lost_near_distance=camera.lost_near_distance,
                        frame_size=(frame.shape[1], frame.shape[0]))

        tracks = detector.track_cars(frame)
        active: set[int] = {track.id for track in tracks}
        analyses: list[SeatbeltAnalysis] = []
        for track in tracks:
            cars_seen += 1
            old_track_id = memory.transfer_track(
                camera_id=camera.id,
                vehicle_class=track.cls,
                track_id=track.id,
                frame_idx=frame_idx,
                anchor=track.anchor,
                active_track_ids=active,
                time_gap=config.transfer_time_gap,
                position_gap=config.transfer_position_gap,
            )
            if old_track_id is not None:
                zone.transfer(old_track_id, track.id)
                if on_transfer is not None:
                    on_transfer({
                        "camera_id": camera.id,
                        "vehicle_type": "car",
                        "from_track_id": old_track_id,
                        "to_track_id": track.id,
                        "frame_idx": frame_idx,
                        "anchor": track.anchor,
                        "from_box": memory.last_transfer["from_box"],
                        "to_box": [track.box.x1, track.box.y1, track.box.x2, track.box.y2],
                    })
            if on_track is not None:
                on_track({"camera_id": camera.id, "vehicle_type": "car",
                          "track_id": track.id, "frame_idx": frame_idx, "anchor": track.anchor,
                          "box": [track.box.x1, track.box.y1, track.box.x2, track.box.y2]})
            acc = memory.get(track.id, track.cls, frame_idx)
            acc.update_position(track.anchor, frame_idx, track.box)
            memory.remember_track(camera_id=camera.id, vehicle_class=track.cls,
                                 track_id=track.id, frame_idx=frame_idx, anchor=track.anchor)

            if camera.check_seatbelt and zone.distance(track.anchor) <= camera.observe_distance:
                if frame_idx % camera.observe_every == 0:
                    analysis = detector.seatbelt_observation(frame, track)
                    analyses.append(analysis)
                    acc.add_observation(analysis.result, frame, track.box, context=analysis)
                    observations_added += 1

            if zone.crossed(track.id, track.anchor):
                crossings += 1
                if not camera.check_seatbelt:
                    if on_crossing is not None:
                        on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                     "vehicle_type": "car", "anchor": track.anchor,
                                     "event_emitted": False, "reason": "SEATBELT_DISABLED"})
                    continue
                if acc.finalized:
                    if on_crossing is not None:
                        on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                     "vehicle_type": "car", "anchor": track.anchor,
                                     "event_emitted": False, "reason": "ALREADY_FINALIZED"})
                    continue
                label, reason = decide(acc.observations, kind_of(track.cls), config.thresholds)
                guarded = [item for item in acc.observations
                           if getattr(item, "reason", "") == "UNVERIFIABLE_VIEW"]
                if guarded:
                    label, reason = "NEEDS_REVIEW", "UNVERIFIABLE_VIEW"
                elif label == "VIOLATION":
                    no_belt = [item for item in acc.observations
                               if getattr(item, "label", "") == "no_seatbelt"
                               and getattr(item, "reason", "") == "OK"]
                    mean_conf = (sum(item.confidence for item in no_belt) / len(no_belt)
                                 if no_belt else 0.0)
                    if any((item.crop_height or 0.0) < 200 for item in no_belt) or mean_conf < 0.70:
                        label, reason = "NEEDS_REVIEW", "UNVERIFIABLE_VIEW"
                if memory.soft_duplicate(
                    camera_id=camera.id,
                    vehicle_class=track.cls,
                    frame_idx=frame_idx,
                    anchor=track.anchor,
                    previous_result=label,
                ):
                    acc.finalized = True
                    if on_crossing is not None:
                        on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                     "vehicle_type": "car", "anchor": track.anchor,
                                     "event_emitted": False, "reason": "SOFT_DUPLICATE"})
                    continue
                raw_label = "no_seatbelt" if label == "VIOLATION" else "seatbelt" if label == "COMPLIANCE" else "unclear"
                confidence_values = [
                    float(getattr(item, "confidence", 0.0))
                    for item in acc.observations
                    if str(getattr(item, "reason", "OK")) == "OK"
                ]
                event = {
                    "event_id": f"{camera.id}_f{frame_idx:06d}_t{track.id}_seatbelt",
                    "camera_id": camera.id,
                    "track_id": track.id,
                    "vehicle_class": "car",
                    "vehicle_type": "car",
                    "violation_type": "seatbelt",
                    "decision": label,
                    "ai_result": raw_label,
                    "confidence": sum(confidence_values) / len(confidence_values) if confidence_values else 0.0,
                    "reason": reason,
                    "timestamp_sec": frame_idx / (source.fps or 25.0),
                    "frame_idx": frame_idx,
                    "observations": len(acc.observations),
                    "anchor": track.anchor,
                    "transferred_from_id": acc.transferred_from_id,
                    "vehicle_box": [track.box.x1, track.box.y1, track.box.x2, track.box.y2],
                }
                best_frame = acc.best_frame if acc.best_frame is not None else frame
                best_box = acc.best_box if acc.best_box is not None else track.box
                best_analysis = acc.best_context if isinstance(acc.best_context, SeatbeltAnalysis) else None
                duplicate_box = best_analysis.track.box if best_analysis else best_box
                event["vehicle_box"] = [
                    duplicate_box.x1, duplicate_box.y1, duplicate_box.x2, duplicate_box.y2,
                ]
                event["evidence"] = evidence.save_event(
                    event, best_frame, best_box, zone, analysis=best_analysis
                )
                acc.finalized = True
                memory.remember_event(camera_id=camera.id, vehicle_class=track.cls,
                                     track_id=track.id, frame_idx=frame_idx,
                                     anchor=track.anchor, decision=label)
                events.append(event)
                print("Stage 6 seatbelt event:", event)
                on_event(event)
                if on_crossing is not None:
                    on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                 "vehicle_type": "car", "anchor": track.anchor,
                                 "event_emitted": True, "event_id": event["event_id"]})

        for track_id, acc in list(memory._tracks.items()):
            if track_id in active:
                continue
            if frame_idx - acc.last_seen >= config.lost_grace_frames and zone.lost(track_id):
                if not camera.check_seatbelt:
                    continue
                if acc.finalized:
                    continue
                label, reason = decide(acc.observations, kind_of(acc.cls), config.thresholds)
                guarded = [item for item in acc.observations
                           if getattr(item, "reason", "") == "UNVERIFIABLE_VIEW"]
                if guarded:
                    label, reason = "NEEDS_REVIEW", "UNVERIFIABLE_VIEW"
                elif label == "VIOLATION":
                    no_belt = [item for item in acc.observations
                               if getattr(item, "label", "") == "no_seatbelt"
                               and getattr(item, "reason", "") == "OK"]
                    mean_conf = (sum(item.confidence for item in no_belt) / len(no_belt)
                                 if no_belt else 0.0)
                    if any((item.crop_height or 0.0) < 200 for item in no_belt) or mean_conf < 0.70:
                        label, reason = "NEEDS_REVIEW", "UNVERIFIABLE_VIEW"
                if memory.soft_duplicate(
                    camera_id=camera.id,
                    vehicle_class=acc.cls,
                    frame_idx=frame_idx,
                    anchor=acc.last_anchor or (0.0, 0.0),
                    previous_result=label,
                ):
                    acc.finalized = True
                    continue
                raw_label = "no_seatbelt" if label == "VIOLATION" else "seatbelt" if label == "COMPLIANCE" else "unclear"
                confidence_values = [
                    float(getattr(item, "confidence", 0.0))
                    for item in acc.observations
                    if str(getattr(item, "reason", "OK")) == "OK"
                ]
                event = {
                    "event_id": f"{camera.id}_f{frame_idx:06d}_t{track_id}_seatbelt",
                    "camera_id": camera.id,
                    "track_id": track_id,
                    "vehicle_class": "car",
                    "vehicle_type": "car",
                    "violation_type": "seatbelt",
                    "decision": label,
                    "ai_result": raw_label,
                    "confidence": sum(confidence_values) / len(confidence_values) if confidence_values else 0.0,
                    "reason": reason,
                    "timestamp_sec": frame_idx / (source.fps or 25.0),
                    "frame_idx": frame_idx,
                    "observations": len(acc.observations),
                    "anchor": acc.last_anchor,
                    "transferred_from_id": acc.transferred_from_id,
                    "vehicle_box": ([acc.last_box.x1, acc.last_box.y1, acc.last_box.x2, acc.last_box.y2]
                                    if acc.last_box is not None else None),
                }
                best_frame = acc.best_frame if acc.best_frame is not None else frame
                best_box = acc.best_box if acc.best_box is not None else acc.last_box
                best_analysis = acc.best_context if isinstance(acc.best_context, SeatbeltAnalysis) else None
                if best_box is not None:
                    duplicate_box = best_analysis.track.box if best_analysis else best_box
                    event["vehicle_box"] = [
                        duplicate_box.x1, duplicate_box.y1, duplicate_box.x2, duplicate_box.y2,
                    ]
                event["evidence"] = evidence.save_event(
                    event, best_frame, best_box, zone, analysis=best_analysis
                )
                acc.finalized = True
                memory.remember_event(camera_id=camera.id, vehicle_class=acc.cls,
                                     track_id=track_id, frame_idx=frame_idx,
                                     anchor=acc.last_anchor or (0.0, 0.0), decision=label)
                events.append(event)
                print("Stage 6 seatbelt lost-track event:", event)
                on_event(event)

        for track_id in memory.cleanup_old(frame_idx):
            zone.forget(track_id)

        if on_frame is not None:
            on_frame(frame_idx, _draw(frame, zone, analyses, memory._tracks))

    print(
        "Seatbelt pipeline summary: "
        f"frames={frames_processed}, car_track_observations={cars_seen}, "
        f"seatbelt_observations={observations_added}, zone_crossings={crossings}, events={len(events)}"
    )
    return events
