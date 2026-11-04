from ai_engine.accumulator import Accumulator
from ai_engine.association import Box, HelmetResult


def test_get_reuses_the_same_track_memory():
    store = Accumulator()
    first = store.get(4, 3, frame_idx=1)
    second = store.get(4, 3, frame_idx=8)
    assert first is second
    first.update_position((10, 20), 8, Box(0, 0, 10, 20))
    assert second.last_anchor == (10, 20)


def test_best_frame_keeps_highest_ok_confidence():
    store = Accumulator()
    memory = store.get(1, 3, 0)
    weak = type("Frame", (), {"copy": lambda self: "weak"})()
    strong = type("Frame", (), {"copy": lambda self: "strong"})()
    memory.add_observation(HelmetResult("helmet", 0.4, "OK"), weak, Box(0, 0, 4, 4))
    memory.add_observation(HelmetResult("helmet", 0.9, "OK"), strong, Box(1, 1, 5, 5))
    memory.add_observation(HelmetResult("unclear", 0.99, "NO_HEAD"), weak, Box(2, 2, 6, 6))
    assert memory.best_frame == "strong"
    assert memory.best_box == Box(1, 1, 5, 5)
    assert len(memory.observations) == 3


def test_cleanup_removes_only_old_tracks():
    store = Accumulator(max_age=5)
    store.get(1, 3, 0).update_position((0, 0), 0)
    store.get(2, 3, 8).update_position((1, 1), 8)
    assert store.cleanup_old(10) == [1]
    assert 1 not in store
    assert 2 in store
