"""Camera AI process manager for single-worker video execution."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import multiprocessing as mp
import os
from pathlib import Path
import queue
import threading
from typing import Any
import cv2
import numpy as np

from backend.app.core.config import settings
from backend.app.db.repository import Repository
from backend.app.models.camera import Camera
from backend.app.models.event import VehicleEvent
from backend.app.models.violation import Violation
from backend.app.services.alert_service import alert_broadcaster

logger = logging.getLogger("traffic_ai.engine_manager")


def _generate_no_signal_frame(camera_id: str, width: int = 960, height: int = 540) -> bytes:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    text1 = f"NO SIGNAL"
    text2 = f"CAMERA: {camera_id}"
    cv2.putText(frame, text1, (width // 2 - 120, height // 2 - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (180, 180, 180), 2)
    cv2.putText(frame, text2, (width // 2 - 150, height // 2 + 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 120, 120), 1)
    _, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    return buf.tobytes()


def camera_worker_process(
    camera_id: str,
    camera_data: dict[str, Any],
    frame_queue: Any,
    event_queue: Any,
    stop_event: Any,
    evidence_dir: str,
) -> None:
    """Standalone worker process entry point for AI video execution."""
    try:
        import sys
        root = Path(__file__).resolve().parents[3]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

        from ai_engine.config import load_config
        from pipeline import run_pipeline

        checks = camera_data.get("checks", ["helmet", "seatbelt"])
        has_helmet = "helmet" in checks
        has_seatbelt = "seatbelt" in checks
        if has_helmet and has_seatbelt:
            mode = "both"
        elif has_helmet:
            mode = "helmet"
        elif has_seatbelt:
            mode = "seatbelt"
        else:
            mode = "both"

        config = load_config({
            "camera": {
                "id": camera_id,
                "zone": camera_data.get("zone", [0.0, 0.9, 1.0, 0.9]),
                "driver_side": camera_data.get("driver_side", "right"),
                "camera_view": camera_data.get("camera_view", "unknown"),
                "motorcycle_view": camera_data.get("motorcycle_view", "approaching"),
                "check_helmet": has_helmet,
                "check_seatbelt": has_seatbelt,
                # Match the CLI defaults so API and CLI runs make equivalent decisions.
                "observe_distance": 400.0,
                "observe_every": 1,
                "device": os.environ.get("TRAFFIC_AI_DEVICE"),
            },
            "paths": {"evidence_dir": evidence_dir},
        })

        def handle_annotated_frame(jpeg_bytes: bytes, _: int) -> None:
            try:
                if frame_queue.full():
                    try:
                        frame_queue.get_nowait()
                    except Exception:
                        pass
                frame_queue.put_nowait(jpeg_bytes)
            except Exception:
                pass

        def handle_event(event: dict[str, Any]) -> None:
            try:
                event_queue.put_nowait({"type": "event_candidate", "data": event})
            except Exception:
                pass

        source = camera_data.get("source_path", "")
        events = run_pipeline(
            source=source,
            config=config,
            mode=mode,
            live=True,
            stop_event=stop_event,
            on_event=handle_event,
            on_annotated_frame=handle_annotated_frame,
        )
        event_queue.put({"type": "events_complete", "events": events})
        event_queue.put({"type": "finished", "camera_id": camera_id})
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        try:
            event_queue.put({
                "type": "error",
                "camera_id": camera_id,
                "error": str(exc),
                "traceback": tb,
            })
        except Exception:
            pass


class WorkerHandle:
    def __init__(
        self,
        camera_id: str,
        process: mp.Process,
        frame_queue: mp.Queue,
        event_queue: mp.Queue,
        stop_event: Any,
    ) -> None:
        self.camera_id = camera_id
        self.process = process
        self.frame_queue = frame_queue
        self.event_queue = event_queue
        self.stop_event = stop_event
        self.latest_frame: bytes | None = None
        self.listener_thread: threading.Thread | None = None


class EngineManager:
    def __init__(self) -> None:
        self.active_worker: WorkerHandle | None = None
        self._lock = threading.Lock()

    def get_latest_frame(self, camera_id: str) -> bytes:
        with self._lock:
            worker = self.active_worker
            if worker and worker.camera_id == camera_id:
                try:
                    while True:
                        worker.latest_frame = worker.frame_queue.get_nowait()
                except (queue.Empty, OSError, ValueError):
                    pass
                if worker.latest_frame is not None:
                    return worker.latest_frame
        return _generate_no_signal_frame(camera_id)

    def start_camera(
        self,
        camera_id: str,
        camera: Camera,
        repo: Repository,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        with self._lock:
            if self.active_worker is not None and self.active_worker.process.is_alive():
                if self.active_worker.camera_id == camera_id:
                    return
                raise RuntimeError(
                    f"Only 1 AI worker may run at a time. Camera '{self.active_worker.camera_id}' is already running."
                )

            if not camera.source_path:
                raise ValueError("Camera has no video source configured")

            ctx = mp.get_context("spawn")
            frame_q = ctx.Queue(maxsize=2)
            event_q = ctx.Queue()
            stop_evt = ctx.Event()

            proc = ctx.Process(
                target=camera_worker_process,
                args=(
                    camera_id,
                    camera.model_dump(),
                    frame_q,
                    event_q,
                    stop_evt,
                    str(settings.evidence_dir),
                ),
                daemon=True,
            )
            proc.start()

            worker = WorkerHandle(
                camera_id=camera_id,
                process=proc,
                frame_queue=frame_q,
                event_queue=event_q,
                stop_event=stop_evt,
            )
            self.active_worker = worker

            # Update camera status in repository
            repo.update_camera(camera_id, {"status": "processing"})
            asyncio.run_coroutine_threadsafe(
                alert_broadcaster.broadcast({
                    "type": "camera_status",
                    "camera_id": camera_id,
                    "status": "processing",
                }),
                loop,
            )

            # Start event listener thread
            t = threading.Thread(
                target=self._event_listener,
                args=(worker, repo, loop),
                daemon=True,
            )
            worker.listener_thread = t
            t.start()

    def stop_camera(
        self,
        camera_id: str,
        repo: Repository,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        with self._lock:
            worker = self.active_worker
            if worker is None or worker.camera_id != camera_id:
                repo.update_camera(camera_id, {"status": "offline"})
                return

            worker.stop_event.set()
            worker.process.join(timeout=3.0)
            if worker.process.is_alive():
                worker.process.terminate()
                worker.process.join(timeout=1.0)

            self.active_worker = None
            repo.update_camera(camera_id, {"status": "offline"})
            asyncio.run_coroutine_threadsafe(
                alert_broadcaster.broadcast({
                    "type": "camera_status",
                    "camera_id": camera_id,
                    "status": "offline",
                }),
                loop,
            )

    def _event_listener(
        self,
        worker: WorkerHandle,
        repo: Repository,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        camera_id = worker.camera_id
        while worker.process.is_alive() or not worker.event_queue.empty():
            try:
                msg = worker.event_queue.get(timeout=0.5)
            except (queue.Empty, OSError, ValueError):
                continue

            msg_type = msg.get("type")
            if msg_type == "event_candidate":
                event_data = msg.get("data", {})
                self._broadcast_candidate(event_data, loop)
            elif msg_type == "events_complete":
                for event_data in msg.get("events", []):
                    self._record_event(event_data, repo, loop)
            elif msg_type == "finished":
                logger.info("Video processing finished for camera %s", camera_id)
                repo.update_camera(camera_id, {"status": "offline"})
                asyncio.run_coroutine_threadsafe(
                    alert_broadcaster.broadcast({
                        "type": "finished",
                        "camera_id": camera_id,
                    }),
                    loop,
                )
                asyncio.run_coroutine_threadsafe(
                    alert_broadcaster.broadcast({
                        "type": "camera_status",
                        "camera_id": camera_id,
                        "status": "offline",
                    }),
                    loop,
                )
                break
            elif msg_type == "error":
                err = msg.get("error", "Unknown worker error")
                logger.error("Camera worker error on %s: %s\n%s", camera_id, err, msg.get("traceback", ""))
                repo.update_camera(camera_id, {"status": "error"})
                asyncio.run_coroutine_threadsafe(
                    alert_broadcaster.broadcast({
                        "type": "camera_status",
                        "camera_id": camera_id,
                        "status": "error",
                        "error": err,
                    }),
                    loop,
                )
                break

        # If process exited without finished message
        if not worker.stop_event.is_set():
            worker.process.join(timeout=1.0)
            exitcode = getattr(worker.process, "exitcode", None)
            if exitcode != 0 and exitcode is not None:
                repo.update_camera(camera_id, {"status": "error"})
                asyncio.run_coroutine_threadsafe(
                    alert_broadcaster.broadcast({
                        "type": "camera_status",
                        "camera_id": camera_id,
                        "status": "error",
                        "error": f"Worker process exited with code {worker.process.exitcode}",
                    }),
                    loop,
                )

    def _record_event(
        self,
        event: dict[str, Any],
        repo: Repository,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        decision = event.get("decision", "NEEDS_REVIEW")
        ai_result = event.get("ai_result", "unclear")
        v_type = event.get("violation_type", "helmet")

        # 1. Store vehicle event (for compliance % stats)
        ve = VehicleEvent(
            event_id=event.get("event_id", f"ev_{now}"),
            camera_id=event.get("camera_id", "cam1"),
            track_id=int(event.get("track_id", 0)),
            vehicle_type=event.get("vehicle_type", "motorcycle"),
            violation_type=v_type,
            decision=decision,
            ai_result=ai_result,
            confidence=float(event.get("confidence", 0.0)),
            reason=event.get("reason", ""),
            timestamp_sec=float(event.get("timestamp_sec", 0.0)),
            frame_idx=int(event.get("frame_idx", 0)),
            created_at=now,
        )
        repo.save_vehicle_event(ve)

        # 2. Store violation if NO_HELMET, NO_SEATBELT, or NEEDS_REVIEW
        if decision in ("VIOLATION", "NEEDS_REVIEW"):
            violation = Violation(
                event_id=ve.event_id,
                camera_id=ve.camera_id,
                track_id=ve.track_id,
                violation_type=ve.violation_type,
                ai_result=ai_result,
                detection_confidence=ve.confidence,
                reason_code=ve.reason,
                evidence=event.get("evidence", {}),
                review_status="UNREVIEWED",
                final_decision=None,
                reviewed_by=None,
                reviewed_at=None,
                review_note=None,
                created_at=now,
            )
            repo.save_violation(violation)
            asyncio.run_coroutine_threadsafe(
                alert_broadcaster.broadcast({
                    "type": "violation",
                    "event": violation.model_dump(),
                }),
                loop,
            )

    def _broadcast_candidate(
        self,
        event: dict[str, Any],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        if event.get("decision") not in ("VIOLATION", "NEEDS_REVIEW"):
            return
        asyncio.run_coroutine_threadsafe(
            alert_broadcaster.broadcast({
                "type": "event_candidate",
                "event": event,
                "provisional": True,
            }),
            loop,
        )


engine_manager = EngineManager()
