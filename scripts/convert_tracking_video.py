"""Re-encode the Stage 5 tracking inspection video as MP4V without rerunning tracking."""
from __future__ import annotations

from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "output" / "s5_id_check.mp4"
OUTPUT = ROOT / "data" / "output" / "s5_id_check_compatible.mp4"


def main() -> None:
    if not INPUT.is_file():
        raise SystemExit(f"Input video not found: {INPUT}")
    if INPUT.resolve() == OUTPUT.resolve():
        raise SystemExit("Input and output paths must be different.")

    capture = cv2.VideoCapture(str(INPUT))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"Could not open input video: {INPUT}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS)
    if width <= 0 or height <= 0 or fps <= 0:
        capture.release()
        raise SystemExit(
            f"Invalid input video properties: resolution={width}x{height}, FPS={fps}"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(OUTPUT),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        writer.release()
        raise SystemExit(f"Could not open MP4V output writer: {OUTPUT}")

    frames_read = 0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if frame.shape[1] != width or frame.shape[0] != height:
                raise RuntimeError(
                    f"Input frame {frames_read} has unexpected size "
                    f"{frame.shape[1]}x{frame.shape[0]} (expected {width}x{height})."
                )
            writer.write(frame)
            frames_read += 1
    finally:
        capture.release()
        writer.release()

    if frames_read == 0:
        raise SystemExit(f"No frames could be read from input: {INPUT}")

    verification = cv2.VideoCapture(str(OUTPUT))
    if not verification.isOpened():
        verification.release()
        raise SystemExit(f"Could not reopen output video: {OUTPUT}")
    output_width = int(verification.get(cv2.CAP_PROP_FRAME_WIDTH))
    output_height = int(verification.get(cv2.CAP_PROP_FRAME_HEIGHT))
    output_fps = verification.get(cv2.CAP_PROP_FPS)
    decoded_frames = 0
    try:
        while True:
            success, _ = verification.read()
            if not success:
                break
            decoded_frames += 1
    finally:
        verification.release()

    if (output_width, output_height) != (width, height):
        raise RuntimeError(
            f"Output resolution mismatch: {output_width}x{output_height}; "
            f"expected {width}x{height}."
        )
    if abs(output_fps - fps) > 0.01:
        raise RuntimeError(f"Output FPS mismatch: {output_fps}; expected {fps}.")
    if decoded_frames != frames_read:
        raise RuntimeError(
            f"Output decode check failed: read {frames_read} input frames, "
            f"but decoded {decoded_frames} output frames."
        )

    print(f"Input frame count: {frames_read}")
    print(f"Successfully written frame count: {decoded_frames}")
    print(f"Output resolution: {output_width}x{output_height}")
    print(f"Output FPS: {output_fps:g}")
    print(f"Output file size: {OUTPUT.stat().st_size} bytes")
    print("Output decode verification: passed")


if __name__ == "__main__":
    main()
