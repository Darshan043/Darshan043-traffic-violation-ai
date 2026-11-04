"""Open a video file or RTSP URL and yield frames with optional skipping."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Iterator

import cv2


@dataclass
class VideoSource:
    source: str
    frame_skip: int = 1
    start_sec: float = 0.0
    end_sec: float | None = None
    reconnect_tries: int = 3
    reconnect_delay: float = 1.0
    fps: float = 0.0
    width: int = 0
    height: int = 0

    def _is_stream(self) -> bool:
        text = str(self.source).lower()
        return text.startswith("rtsp://") or text.startswith("http://") or text.startswith("https://")

    def _open(self) -> cv2.VideoCapture:
        capture = cv2.VideoCapture(str(self.source))
        if not capture.isOpened():
            capture.release()
            raise OSError(f"Could not open video: {self.source}")
        self.fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
        self.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return capture

    def frames(self) -> Iterator[tuple[int, object]]:
        if self.frame_skip < 1:
            raise ValueError("frame_skip must be at least 1")
        tries_left = self.reconnect_tries if self._is_stream() else 1
        last_error: OSError | None = None
        while tries_left:
            tries_left -= 1
            capture = None
            try:
                capture = self._open()
                start_frame = int(self.start_sec * self.fps)
                end_frame = None if self.end_sec is None else int(self.end_sec * self.fps)
                frame_idx = 0
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
                    if current % self.frame_skip:
                        continue
                    yield current, frame
                return
            except OSError as error:
                last_error = error
                if not self._is_stream() or tries_left <= 0:
                    raise
                time.sleep(self.reconnect_delay)
            finally:
                if capture is not None:
                    capture.release()
        if last_error is not None:
            raise last_error
