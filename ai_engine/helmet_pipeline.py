"""Motorcycle-only Stage 6 flow: observe, cross zone, vote, emit a decision."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import cv2

from ai_engine.accumulator import Accumulator, TrackMemory
from ai_engine.association import link_head_to_person
from ai_engine.config import EngineConfig
from ai_engine.decision import decide, kind_of
from ai_engine.detector import HelmetAnalysis, HelmetDetector
from ai_engine.evidence import EvidenceWriter
from ai_engine.video_source import VideoSource
from ai_engine.zone import Zone


def _draw(frame, zone: Zone, analyses: list[HelmetAnalysis], memories: dict[int, TrackMemory]):
    """Draw enough geometry to check the vehicle-to-rider/head association."""
    points = [(int(x), int(y)) for x, y in zone.vertices]
    if zone.is_line:
        cv2.line(frame, points[0], points[1], (255, 255, 0), 2)
    else:
        import numpy as np
        cv2.polylines(frame, [np.asarray(points, dtype="int32")], True, (255, 255, 0), 2)

    colors = {"helmet": (40, 220, 40), "no_helmet": (20, 20, 240), "unclear": (0, 220, 255)}
    for analysis in analyses:
        track = analysis.track
        result = analysis.result
        color = colors[result.label]
        x1, y1, x2, y2 = map(int, (track.box.x1, track.box.y1, track.box.x2, track.box.y2))
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 150, 20), 2)
        cv2.putText(frame, f"motorcycle #{track.id}", (x1, max(18, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, .48, (255, 200, 80), 1)
        cv2.putText(frame, f"class={track.cls}", (x1, max(34, y1 - 2)),
                    cv2.FONT_HERSHEY_SIMPLEX, .38, (255, 255, 255), 1)
        for person in analysis.persons:
            p1, p2 = (int(person.x1), int(person.y1)), (int(person.x2), int(person.y2))
            cv2.rectangle(frame, p1, p2, (80, 180, 80), 1)
        for rider in analysis.riders:
            r1, r2 = (int(rider.x1), int(rider.y1)), (int(rider.x2), int(rider.y2))
            cv2.rectangle(frame, r1, r2, (0, 200, 0), 2)
            cv2.putText(frame, "rider", (r1[0], max(14, r1[1] - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 200, 0), 1)
        if analysis.driver is not None:
            driver = analysis.driver
            d1, d2 = (int(driver.x1), int(driver.y1)), (int(driver.x2), int(driver.y2))
            cv2.rectangle(frame, d1, d2, color, 3)
            cv2.putText(frame, "driver", (d1[0], max(14, d1[1] - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, .48, color, 2)
            linked = link_head_to_person(analysis.heads, driver)
            dx, dy = int(driver.centre[0]), int(driver.centre[1])
            for head in linked:
                hx, hy = (int(head.box.centre[0]), int(head.box.centre[1]))
                cv2.line(frame, (dx, dy), (hx, hy), color, 2)
        for head in analysis.heads:
            h = head.box
            h1, h2 = (int(h.x1), int(h.y1)), (int(h.x2), int(h.y2))
            cv2.rectangle(frame, h1, h2, color, 2)
            cv2.putText(frame, head.label, (h1[0], max(12, h1[1] - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX, .38, color, 1)
        memory = memories.get(track.id)
        final = " FINAL" if memory and memory.finalized else ""
        status = f"{result.label.upper()} {result.confidence:.2f}{final}"
        cv2.putText(frame, f"latest: {status}",
                    (x1, max(52, y1 + 6)), cv2.FONT_HERSHEY_SIMPLEX, .46, color, 2)
        cv2.putText(frame, f"helmet: {result.label}",
                    (x1, max(70, y1 + 24)), cv2.FONT_HERSHEY_SIMPLEX, .36, color, 1)
    return frame


def process_motorcycles(
    video_path: str,
    config: EngineConfig,
    on_event: Callable[[dict[str, Any]], None],
    *,
    detector: HelmetDetector | None = None,
    on_frame: Callable[[int, Any], None] | None = None,
    on_transfer: Callable[[dict[str, Any]], None] | None = None,
    on_crossing: Callable[[dict[str, Any]], None] | None = None,
    on_track: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Process a video and emit one helmet decision per motorcycle zone crossing.

    Every event, including NEEDS_REVIEW, is saved before it is sent to on_event.
    """
    detector = detector or HelmetDetector(config)
    camera = config.camera
    source = VideoSource(video_path, camera.frame_skip,
                         start_sec=config.start_sec, end_sec=config.end_sec)
    zone: Zone | None = None
    memory = Accumulator(max_age=max(config.accumulator_max_age, config.lost_grace_frames))
    evidence = EvidenceWriter(config.paths.evidence_dir)
    events: list[dict[str, Any]] = []
    frames_processed = motorcycles_seen = observations_added = crossings = 0

    for frame_idx, frame in source.frames():
        frames_processed += 1
        if zone is None:
            # Normalised camera coordinates need the actual frame dimensions.
            zone = Zone(camera.zone, lost_near_distance=camera.lost_near_distance,
                        frame_size=(frame.shape[1], frame.shape[0]))
        tracks = detector.track_vehicles(frame)
        active: set[int] = {track.id for track in tracks}
        analyses = []
        for track in tracks:
            motorcycles_seen += 1
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
                        "vehicle_type": "motorcycle",
                        "from_track_id": old_track_id,
                        "to_track_id": track.id,
                        "frame_idx": frame_idx,
                        "anchor": track.anchor,
                        "from_box": memory.last_transfer["from_box"],
                        "to_box": [track.box.x1, track.box.y1, track.box.x2, track.box.y2],
                    })
            if on_track is not None:
                on_track({"camera_id": camera.id, "vehicle_type": "motorcycle",
                          "track_id": track.id, "frame_idx": frame_idx, "anchor": track.anchor,
                          "box": [track.box.x1, track.box.y1, track.box.x2, track.box.y2]})
            acc = memory.get(track.id, track.cls, frame_idx)
            acc.update_position(track.anchor, frame_idx, track.box)
            memory.remember_track(camera_id=camera.id, vehicle_class=track.cls,
                                 track_id=track.id, frame_idx=frame_idx, anchor=track.anchor)
            kind = kind_of(track.cls)

            # Run the custom model only near the configured decision region.
            if camera.check_helmet and zone.distance(track.anchor) <= camera.observe_distance:
                if frame_idx % camera.observe_every == 0:
                    analysis = detector.helmet_observation(frame, track)
                    analyses.append(analysis)
                    acc.add_observation(analysis.result, frame, track.box, context=analysis)
                    observations_added += 1

            if zone.crossed(track.id, track.anchor):
                crossings += 1
                if acc.finalized:
                    if on_crossing is not None:
                        on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                     "vehicle_type": "motorcycle", "anchor": track.anchor,
                                     "event_emitted": False, "reason": "ALREADY_FINALIZED"})
                    continue
                label, reason = decide(acc.observations, kind, config.thresholds)
                prior_result = label if memory.soft_duplicate(
                    camera_id=camera.id,
                    vehicle_class=track.cls,
                    frame_idx=frame_idx,
                    anchor=track.anchor,
                    previous_result=label,
                ) else None
                if prior_result is not None:
                    acc.finalized = True
                    if on_crossing is not None:
                        on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                     "vehicle_type": "motorcycle", "anchor": track.anchor,
                                     "event_emitted": False, "reason": "SOFT_DUPLICATE"})
                    continue
                raw_label = "no_helmet" if label == "VIOLATION" else "helmet" if label == "COMPLIANCE" else "unclear"
                confidence_values = [
                    float(getattr(item, "confidence", 0.0))
                    for item in acc.observations
                    if str(getattr(item, "reason", "OK")) == "OK"
                ]
                event = {
                    "event_id": f"{camera.id}_f{frame_idx:06d}_t{track.id}_helmet",
                    "camera_id": camera.id,
                    "track_id": track.id,
                    "vehicle_class": "motorcycle",
                    "vehicle_type": "motorcycle",
                    "violation_type": "helmet",
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
                best_analysis = acc.best_context if isinstance(acc.best_context, HelmetAnalysis) else None
                evidence_frame = acc.best_frame if acc.best_frame is not None else frame
                evidence_vehicle_box = acc.best_box if acc.best_box is not None else track.box
                duplicate_box = best_analysis.track.box if best_analysis else evidence_vehicle_box
                event["vehicle_box"] = [
                    duplicate_box.x1, duplicate_box.y1, duplicate_box.x2, duplicate_box.y2,
                ]
                event["evidence"] = evidence.save_event(
                    event, evidence_frame, evidence_vehicle_box, zone, analysis=best_analysis
                )
                acc.finalized = True
                memory.remember_event(camera_id=camera.id, vehicle_class=track.cls,
                                     track_id=track.id, frame_idx=frame_idx,
                                     anchor=track.anchor, decision=label)
                events.append(event)
                print("Stage 6 event:", event)
                on_event(event)
                if on_crossing is not None:
                    on_crossing({"frame_idx": frame_idx, "track_id": track.id,
                                 "vehicle_type": "motorcycle", "anchor": track.anchor,
                                 "event_emitted": True, "event_id": event["event_id"]})

        for track_id, acc in list(memory._tracks.items()):
            if track_id in active:
                continue
            if frame_idx - acc.last_seen >= config.lost_grace_frames and zone.lost(track_id):
                if acc.finalized:
                    continue
                label, reason = decide(acc.observations, kind_of(acc.cls), config.thresholds)
                if memory.soft_duplicate(
                    camera_id=camera.id,
                    vehicle_class=acc.cls,
                    frame_idx=frame_idx,
                    anchor=acc.last_anchor or (0.0, 0.0),
                    previous_result=label,
                ):
                    acc.finalized = True
                    continue
                raw_label = "no_helmet" if label == "VIOLATION" else "helmet" if label == "COMPLIANCE" else "unclear"
                confidence_values = [
                    float(getattr(item, "confidence", 0.0))
                    for item in acc.observations
                    if str(getattr(item, "reason", "OK")) == "OK"
                ]
                event = {
                    "event_id": f"{camera.id}_f{frame_idx:06d}_t{track_id}_helmet",
                    "camera_id": camera.id,
                    "track_id": track_id,
                    "vehicle_class": "motorcycle",
                    "vehicle_type": "motorcycle",
                    "violation_type": "helmet",
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
                evidence_frame = acc.best_frame if acc.best_frame is not None else frame
                evidence_vehicle_box = acc.best_box if acc.best_box is not None else acc.last_box
                if evidence_vehicle_box is not None:
                    event["vehicle_box"] = [
                        evidence_vehicle_box.x1, evidence_vehicle_box.y1,
                        evidence_vehicle_box.x2, evidence_vehicle_box.y2,
                    ]
                event["evidence"] = evidence.save_event(event, evidence_frame, evidence_vehicle_box, zone)
                acc.finalized = True
                memory.remember_event(camera_id=camera.id, vehicle_class=acc.cls,
                                     track_id=track_id, frame_idx=frame_idx,
                                     anchor=acc.last_anchor or (0.0, 0.0), decision=label)
                events.append(event)
                print("Stage 6 lost-track event:", event)
                on_event(event)

        for track_id in memory.cleanup_old(frame_idx):
            zone.forget(track_id)

        if on_frame is not None:
            on_frame(frame_idx, _draw(frame, zone, analyses, memory._tracks))

    print(f"Helmet pipeline summary: frames={frames_processed}, motorcycle_track_observations={motorcycles_seen}, "
          f"helmet_observations={observations_added}, zone_crossings={crossings}, events={len(events)}")
    return events
