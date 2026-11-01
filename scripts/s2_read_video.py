import argparse
from pathlib import Path

import cv2


def main() -> None:
    parser = argparse.ArgumentParser(description="Read and display a road video.")
    parser.add_argument(
        "--video",
        type=Path,
        default=Path("data/videos/test_road.mp4"),
        help="Video file to open (default: data/videos/test_road.mp4).",
    )
    args = parser.parse_args()

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"Could not open video: {args.video}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Video: {args.video}")
    print(f"FPS: {fps:g}")
    print(f"Width: {width}")
    print(f"Height: {height}")
    print(f"Total frames: {frame_count}")

    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            cv2.imshow("Stage 2 - Video reader (press q to quit)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
