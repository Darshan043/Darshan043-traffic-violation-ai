import json

from scripts import run_video


def test_cli_writes_final_json_events(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"placeholder")
    events = [{
        "camera_id": "cam-test",
        "track_id": 12,
        "vehicle_class": "car",
        "violation_type": "seatbelt",
        "decision": "NEEDS_REVIEW",
        "reason": "TOO_FEW_OBSERVATIONS",
        "frame_idx": 4,
        "observations": 1,
    }]
    monkeypatch.setattr(run_video, "run_pipeline", lambda *args, **kwargs: events)
    json_path = tmp_path / "events.json"

    result = run_video.main([
        "--source", str(source),
        "--mode", "seatbelt",
        "--no-show",
        "--json", str(json_path),
    ])

    assert result == 0
    assert json.loads(json_path.read_text(encoding="utf-8")) == events
