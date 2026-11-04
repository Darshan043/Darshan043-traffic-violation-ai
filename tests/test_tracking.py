from types import SimpleNamespace

from ai_engine.association import Box
from ai_engine.tracking import Track, TrackStore, results_to_tracks


def make_track(track_id=1, cls=2, x1=10, y1=20, x2=30, y2=60, conf=.8):
    return Track(track_id, cls, Box(x1, y1, x2, y2), conf, ((x1+x2)/2, y2))


class Tensor:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value

    def tolist(self):
        return self.value


def test_results_to_tracks_skips_missing_id():
    detection = SimpleNamespace(id=None)
    assert results_to_tracks(SimpleNamespace(boxes=[detection])) == []


def test_results_to_tracks_anchor_is_bottom_centre():
    detection = SimpleNamespace(id=Tensor(7), cls=Tensor(2), conf=Tensor(.75),
                                xyxy=[Tensor([10, 20, 30, 60])])
    track, = results_to_tracks(SimpleNamespace(boxes=[detection]))
    assert track.anchor == (20, 60)


def test_history_is_capped_at_configured_length():
    store = TrackStore(history_size=3)
    for i in range(5):
        store.update(i, [make_track(x1=i)])
    assert len(store.history[1]) == 3
    assert list(store.history[1]) == [(16, 60), (16.5, 60), (17, 60)]


def test_update_refreshes_last_seen():
    store = TrackStore()
    store.update(2, [make_track()])
    store.update(9, [make_track()])
    assert store.first_seen[1] == 2
    assert store.last_seen[1] == 9


def test_cleanup_removes_only_tracks_older_than_max_age():
    store = TrackStore()
    store.update(0, [make_track(1), make_track(2, cls=3)])
    store.update(8, [make_track(2, cls=3)])
    assert store.cleanup(10, max_age=3) == [1]
    assert set(store.tracks) == {2}


def test_class_vote_uses_most_frequent_class():
    store = TrackStore()
    store.update(0, [make_track(cls=2)])
    store.update(1, [make_track(cls=3)])
    store.update(2, [make_track(cls=3)])
    assert store.class_vote(1) == 3
