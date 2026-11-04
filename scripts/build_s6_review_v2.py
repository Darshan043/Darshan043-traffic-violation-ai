"""Run the Stage 6 engine and build an event and ID-transfer review pack."""
from __future__ import annotations

import contextlib
import csv
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
import shutil
import sys

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_engine.accumulator import Accumulator
from ai_engine.association import Box
from ai_engine.config import load_config
from pipeline import run_pipeline

OUTPUT = ROOT / "data" / "output" / "s6_review_v2"
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
REVIEW_COLUMNS = [
    "event_id", "video", "time_sec", "track_id", "vehicle_type", "ai_result",
    "confidence", "frames_used", "reason", "transferred_from_id",
    "my_true_result", "correct (y/n)", "duplicate_of", "notes",
]


def _replay_transfers(rows: list[dict], *, time_gap: int, position_gap: float) -> dict[str, int]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["vehicle_type"]].append(row)
    counts = {}
    for vehicle_type, entries in grouped.items():
        class_id = 3 if vehicle_type == "motorcycle" else 2
        accumulator = Accumulator(max_age=120)
        by_frame: dict[int, list[dict]] = defaultdict(list)
        for entry in entries:
            by_frame[entry["frame_idx"]].append(entry)
        count = 0
        for frame_idx in sorted(by_frame):
            current = by_frame[frame_idx]
            active = {entry["track_id"] for entry in current}
            for entry in current:
                replaced = accumulator.transfer_track(
                    camera_id=entry["camera_id"], vehicle_class=class_id,
                    track_id=entry["track_id"], frame_idx=frame_idx,
                    anchor=tuple(entry["anchor"]), active_track_ids=active,
                    time_gap=time_gap, position_gap=position_gap,
                )
                count += replaced is not None
                memory = accumulator.get(entry["track_id"], class_id, frame_idx)
                memory.update_position(tuple(entry["anchor"]), frame_idx, Box(*entry["box"]))
            accumulator.cleanup_old(frame_idx)
        counts[vehicle_type] = count
    return counts


def _draw_transfer(frame, transfer: dict) -> object:
    image = frame.copy()
    boxes = (
        ("from_box", "from_track_id", (0, 0, 255), "before"),
        ("to_box", "to_track_id", (0, 220, 0), "after"),
    )
    for key, id_key, color, label in boxes:
        box = transfer.get(key)
        if not box:
            continue
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        cv2.putText(
            image,
            f"{transfer['vehicle_type']} #{transfer[id_key]} ({label})",
            (x1, max(24, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            .7,
            color,
            2,
            cv2.LINE_AA,
        )
    cv2.putText(
        image, f"ID transfer at {transfer['time_sec']:.2f}s",
        (14, 32), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2, cv2.LINE_AA,
    )
    return image


def _write_review_sheet(rows: list[dict]) -> None:
    with (OUTPUT / "review_sheet.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in REVIEW_COLUMNS} for row in rows)


def _write_suppressed(rows: list[dict]) -> None:
    columns = [
        "event_id", "video", "time_sec", "track_id", "vehicle_type", "ai_result",
        "confidence", "frames_used", "reason", "suppressed_by", "suppression_reason",
    ]
    with (OUTPUT / "suppressed_events.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for event in rows:
            writer.writerow({
                "event_id": event["event_id"], "video": event["video"],
                "time_sec": f"{float(event.get('timestamp_sec', 0)):.3f}",
                "track_id": event["track_id"], "vehicle_type": event["vehicle_type"],
                "ai_result": _result_name(event),
                "confidence": event.get("confidence", 0), "frames_used": event.get("observations", 0),
                "reason": event.get("reason", ""), "suppressed_by": event.get("suppressed_by", ""),
                "suppression_reason": event.get("suppression_reason", ""),
            })


def _write_transfer_files(rows: list[dict]) -> None:
    columns = [
        "video", "time_sec", "frame_idx", "vehicle_type", "from_track_id",
        "to_track_id", "same_vehicle", "before_image", "after_image",
    ]
    with (OUTPUT / "transfers_sheet.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "video": row["video"], "time_sec": f"{row['time_sec']:.3f}",
                "frame_idx": row["frame_idx"], "vehicle_type": row["vehicle_type"],
                "from_track_id": row["from_track_id"], "to_track_id": row["to_track_id"],
                "same_vehicle": "",
                "before_image": f"transfers/{row['before_image']}",
                "after_image": f"transfers/{row['after_image']}",
            })
    parts = [
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage 6 ID transfer review</title>",
        "<style>body{font:14px Arial;margin:20px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #bbb;padding:6px;vertical-align:top}"
        "img{max-width:420px;max-height:240px}</style></head><body>",
        f"<h1>Tracker ID transfers ({len(rows)})</h1><table><thead><tr>"
        "<th>Video / time / type / IDs</th><th>Frame before</th><th>Frame after</th>"
        "<th>same_vehicle (fill in CSV)</th></tr></thead><tbody>",
    ]
    for row in rows:
        details = (f"{html.escape(row['video'])}<br>{row['time_sec']:.3f}s "
                   f"(frame {row['frame_idx']})<br>{html.escape(row['vehicle_type'])} "
                   f"#{row['from_track_id']} → #{row['to_track_id']}")
        parts.append(
            f"<tr><td>{details}</td>"
            f"<td><img src=\"transfers/{html.escape(row['before_image'])}\"></td>"
            f"<td><img src=\"transfers/{html.escape(row['after_image'])}\"></td>"
            "<td>blank; record in transfers_sheet.csv</td></tr>"
        )
    parts.append("</tbody></table></body></html>")
    (OUTPUT / "transfers.html").write_text("\n".join(parts), encoding="utf-8")


def _write_index(rows: list[dict]) -> None:
    parts = [
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage 6 review pack v2</title>",
        "<style>body{font:14px Arial;margin:20px}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #bbb;padding:6px;vertical-align:top}"
        "img{max-width:320px;max-height:220px}tr:nth-child(even){background:#f3f3f3}"
        "</style></head><body>",
        f"<h1>Stage 6 review pack v2 ({len(rows)} event records, including suppressed events)</h1>"
        "<p>Suppressed events are listed in suppressed_events.csv. Reviewer fields are blank.</p>"
        "<table><thead><tr><th>Event details</th><th>Full frame</th><th>Crop</th></tr></thead><tbody>",
    ]
    for row in rows:
        details = "<br>".join(
            f"<b>{html.escape(key)}:</b> {html.escape(str(row.get(key, '')))}"
            for key in REVIEW_COLUMNS[:10]
        )
        if row.get("suppressed_by"):
            details += (
                f"<br><b>suppressed_by:</b> "
                f"{html.escape(str(row['suppressed_by']))}"
            )
        parts.append(
            f"<tr><td>{details}</td><td><img src=\"{html.escape(row['full_image'])}\"></td>"
            f"<td><img src=\"{html.escape(row['crop_image'])}\"></td></tr>"
        )
    parts.append(
        "</tbody></table><h2>Transfers</h2><p>See <a href=\"transfers.html\">transfer frames</a>; "
        "fill same_vehicle in transfers_sheet.csv.</p></body></html>"
    )
    (OUTPUT / "index.html").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "evidence").mkdir(exist_ok=True)
    transfer_dir = OUTPUT / "transfers"
    transfer_dir.mkdir(exist_ok=True)
    zone_path = OUTPUT / "zone_report.json"
    if not zone_path.is_file():
        raise FileNotFoundError(f"Run scripts/zone_report.py first: {zone_path}")
    zone_report = json.loads(zone_path.read_text(encoding="utf-8"))
    zone_by_video = {item["video"]: item for item in zone_report}
    videos = sorted(
        path for path in (ROOT / "data" / "videos").iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )
    if not videos:
        raise FileNotFoundError("No supported videos found under data/videos")

    event_rows: list[dict] = []
    suppressed_rows: list[dict] = []
    transfer_rows: list[dict] = []
    crossing_rows: list[dict] = []
    video_reports: list[dict] = []
    all_track_rows: list[dict] = []
    base_config = load_config({"paths": {"evidence_dir": str(OUTPUT / "evidence")}})

    for video in videos:
        zone_info = zone_by_video[video.name]
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            capture.release()
            raise OSError(f"Could not open video: {video}")
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        capture.release()

        tracked: dict[str, set[int]] = defaultdict(set)
        local_track_rows: list[dict] = []
        local_transfers: list[dict] = []
        local_crossings: list[dict] = []
        last_frames: dict[str, tuple[int, object]] = {}
        pending: dict[tuple[str, int], list[dict]] = defaultdict(list)

        def on_track(record: dict) -> None:
            tracked[record["vehicle_type"]].add(record["track_id"])
            local_track_rows.append(dict(record))

        def on_transfer(record: dict) -> None:
            mode = "helmet" if record["vehicle_type"] == "motorcycle" else "seatbelt"
            transfer = dict(record)
            transfer.update({
                "video": video.name,
                "time_sec": record["frame_idx"] / fps,
                "sequence": len(transfer_rows) + len(local_transfers) + 1,
                "mode": mode,
            })
            previous = last_frames.get(mode)
            if previous is not None:
                transfer["before_frame"] = previous[1].copy()
            local_transfers.append(transfer)
            pending[(mode, record["frame_idx"])].append(transfer)

        def on_frame(mode: str, frame_idx: int, frame) -> None:
            for transfer in pending.pop((mode, frame_idx), []):
                before = transfer.get("before_frame", frame)
                before_name = f"transfer_{transfer['sequence']:04d}_before.jpg"
                after_name = f"transfer_{transfer['sequence']:04d}_after.jpg"
                if not cv2.imwrite(
                    str(transfer_dir / before_name), _draw_transfer(before, transfer)
                ):
                    raise OSError(f"Could not save transfer-before frame: {before_name}")
                if not cv2.imwrite(
                    str(transfer_dir / after_name), _draw_transfer(frame, transfer)
                ):
                    raise OSError(f"Could not save transfer-after frame: {after_name}")
                transfer["before_image"] = before_name
                transfer["after_image"] = after_name
            last_frames[mode] = (frame_idx, frame.copy())

        def on_suppressed(event: dict) -> None:
            suppressed = dict(event, video=video.name)
            suppressed_rows.append(suppressed)
            _append_event_review_row(suppressed, event_rows, video.name)

        def on_crossing(record: dict) -> None:
            local_crossings.append({
                **record,
                "video": video.name,
                "time_sec": record["frame_idx"] / fps,
            })

        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            events = run_pipeline(
                video, base_config, mode="both", on_track=on_track,
                on_transfer=on_transfer, on_frame=on_frame, on_suppressed=on_suppressed,
                on_crossing=on_crossing,
            )
        summary_lines = [
            line.strip() for line in captured.getvalue().splitlines()
            if "pipeline summary:" in line
        ]
        local_track_rows = [dict(record, video=video.name) for record in local_track_rows]
        all_track_rows.extend(local_track_rows)
        transfer_rows.extend(local_transfers)
        retained_tracks = {
            (event.get("vehicle_type"), event["track_id"]) for event in events
        }
        suppressed_tracks = {
            (event.get("vehicle_type"), event["track_id"]) for event in suppressed_rows
            if event.get("video") == video.name
        }
        no_event_crossings = []
        for crossing in local_crossings:
            track = (crossing.get("vehicle_type"), crossing["track_id"])
            if track in retained_tracks:
                continue
            if track in suppressed_tracks:
                crossing["reason"] = "DUPLICATE_SUPPRESSED"
            no_event_crossings.append(crossing)
        crossing_rows.extend(no_event_crossings)

        results = Counter(_result_name(event) for event in events)
        reasons = Counter(event.get("reason", "UNKNOWN") for event in events)
        video_reports.append({
            "video": video.name,
            "frames": frame_count,
            "fps": fps,
            "zone_y": zone_info["recommended_zone_y"],
            "vehicles_tracked": sum(len(ids) for ids in tracked.values()),
            "unique_by_type": {key: len(ids) for key, ids in tracked.items()},
            "events": len(events),
            "results": dict(results),
            "reasons": dict(reasons),
            "id_transfers": len(local_transfers),
            "crossings_without_event": len(no_event_crossings),
            "pipeline_summaries": summary_lines,
        })

        for event in events:
            _append_event_review_row(event, event_rows, video.name)
        print(
            f"{video.name}: frames={frame_count}, fps={fps:.3f}, "
            f"vehicles={video_reports[-1]['vehicles_tracked']}, "
            f"events={len(events)}, transfers={len(local_transfers)}",
            flush=True,
        )

    for report in video_reports:
        rows = [row for row in all_track_rows if row["video"] == report["video"]]
        report["transfer_sensitivity"] = {
            "baseline_80px_15frames": _replay_transfers(rows, time_gap=15, position_gap=80.0),
            "distance_60px_15frames": _replay_transfers(rows, time_gap=15, position_gap=60.0),
            "distance_80px_8frames": _replay_transfers(rows, time_gap=8, position_gap=80.0),
        }
        video_transfers = [row for row in transfer_rows if row["video"] == report["video"]]
        by_type = Counter(row["vehicle_type"] for row in video_transfers)
        car_count = report["unique_by_type"].get("car", 0)
        tracked_count = report["vehicles_tracked"]
        report["actual_transfer_by_type"] = dict(by_type)
        report["car_transfer_rate"] = by_type["car"] / car_count if car_count else 0.0
        report["transfer_rate_all"] = report["id_transfers"] / tracked_count if tracked_count else 0.0

    _write_review_sheet(event_rows)
    _write_suppressed(suppressed_rows)
    _write_transfer_files(transfer_rows)
    _write_index(event_rows)
    retained_rows = [row for row in event_rows if not row.get("suppressed_by")]
    results = Counter(row["ai_result"] for row in retained_rows)
    reasons = Counter(row["reason"] for row in retained_rows)
    candidate_results = Counter(row["ai_result"] for row in event_rows)
    report = {
        "videos": video_reports,
        "event_results": dict(results),
        "reason_codes": dict(reasons),
        "retained_events": len(event_rows) - len(suppressed_rows),
        "review_sheet_events": len(event_rows),
        "suppressed_events": len(suppressed_rows),
        "review_candidate_results": dict(candidate_results),
        "crossings_without_event": len(crossing_rows),
        "suppressed_event_rows": [
            {key: event.get(key) for key in (
                "event_id", "video", "track_id", "vehicle_type", "observations",
                "suppressed_by", "suppression_reason",
            )}
            for event in suppressed_rows
        ],
        "id_transfers": len(transfer_rows),
    }
    (OUTPUT / "run_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_crossings_without_event(crossing_rows)
    print(json.dumps(report, indent=2))
    print(f"Review pack: {OUTPUT}")


def _append_event_review_row(event: dict, rows: list[dict], video_name: str) -> None:
    result = _result_name(event)
    prefix = f"{event['event_id']}_t{event['track_id']}_{result}"
    evidence = event.get("evidence") or {}
    source_full = Path(evidence.get("full_frame", ""))
    source_crop = Path(evidence.get("driver_rider_crop", ""))
    if not source_full.is_file() or not source_crop.is_file():
        raise FileNotFoundError(f"Evidence images missing for {event['event_id']}")
    full_name = f"{prefix}_full.jpg"
    crop_name = f"{prefix}_crop.jpg"
    shutil.copy2(source_full, OUTPUT / full_name)
    shutil.copy2(source_crop, OUTPUT / crop_name)
    rows.append({
        "event_id": event["event_id"],
        "video": video_name,
        "time_sec": f"{float(event.get('timestamp_sec', 0)):.3f}",
        "track_id": event["track_id"],
        "vehicle_type": event.get("vehicle_type", ""),
        "ai_result": result,
        "confidence": f"{float(event.get('confidence', 0)):.4f}",
        "frames_used": event.get("observations", 0),
        "reason": event.get("reason", ""),
        "transferred_from_id": "" if event.get("transferred_from_id") is None
        else event["transferred_from_id"],
        "my_true_result": "", "correct (y/n)": "", "duplicate_of": "", "notes": "",
        "full_image": full_name, "crop_image": crop_name,
        "suppressed_by": event.get("suppressed_by", ""),
    })


def _result_name(event: dict) -> str:
    decision = str(event.get("decision", "")).upper()
    if decision == "NEEDS_REVIEW":
        return "NEEDS_REVIEW"
    result = str(event.get("ai_result", "unclear")).upper()
    return "NEEDS_REVIEW" if result in {"UNCLEAR", "NEEDS_REVIEW"} else result


def _write_crossings_without_event(rows: list[dict]) -> None:
    columns = ["video", "time_sec", "frame_idx", "track_id", "vehicle_type", "reason"]
    with (OUTPUT / "crossings_without_event.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in columns} for row in rows)


if __name__ == "__main__":
    main()
