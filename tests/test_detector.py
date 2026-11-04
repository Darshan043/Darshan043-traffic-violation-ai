from types import SimpleNamespace

import numpy as np

from ai_engine.association import HelmetResult
from ai_engine.config import load_config
from ai_engine.detector import HelmetDetector


class Scalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value

    def tolist(self):
        return self.value


def box_detection(track_id, cls, conf, coords):
    return SimpleNamespace(
        id=None if track_id is None else Scalar(track_id),
        cls=Scalar(cls), conf=Scalar(conf), xyxy=[Scalar(coords)],
    )


class FakeVehicleModel:
    names = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle"}

    def __init__(self, person_detections=()):
        self.person_detections = list(person_detections)
        self.track_kwargs = None

    def track(self, frame, **kwargs):
        self.track_kwargs = kwargs
        items = [box_detection(7, 3, .90, [100, 300, 300, 500]),
                 box_detection(None, 3, .80, [10, 10, 30, 30])]
        return [SimpleNamespace(boxes=items)]

    def predict(self, image, **kwargs):
        # Full frame is 600 pixels high; crop-upscale input is 640 pixels high.
        items = self.person_detections if image.shape[0] >= 640 else []
        return [SimpleNamespace(boxes=items)]


class FakeHelmetModel:
    names = {0: "helmet", 1: "no_helmet"}

    def predict(self, image, **kwargs):
        items = [box_detection(None, 1, .91, [30, 30, 60, 60])]
        return [SimpleNamespace(boxes=items)]


def test_tracks_motorcycles_without_inventing_missing_ids():
    config = load_config()
    vehicle = FakeVehicleModel()
    detector = HelmetDetector(config, vehicle, FakeHelmetModel())
    tracks = detector.track_vehicles(np.zeros((600, 800, 3), dtype=np.uint8))
    assert [item.id for item in tracks] == [7]
    assert vehicle.track_kwargs["persist"] is True
    assert vehicle.track_kwargs["classes"] == [3]


def test_helmet_observation_uses_upscaled_person_crop_and_full_frame_head_coords():
    local_person = box_detection(None, 0, .88, [20, 40, 150, 300])
    vehicle = FakeVehicleModel([local_person])
    detector = HelmetDetector(load_config(), vehicle, FakeHelmetModel())
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    track = detector.track_vehicles(frame)[0]

    analysis = detector.helmet_observation(frame, track)

    assert analysis.result == HelmetResult("no_helmet", .91, "OK")
    assert analysis.driver is not None
    assert analysis.driver.x1 == 110
    assert analysis.heads[0].box.x1 == 130
    assert analysis.heads[0].box.y1 == 210
    assert analysis.crop_box.y1 == 180


def test_small_motorcycle_is_unclear_without_model_crop_inference():
    vehicle = FakeVehicleModel()
    detector = HelmetDetector(load_config(), vehicle, FakeHelmetModel())
    track = detector.track_vehicles(np.zeros((600, 800, 3), dtype=np.uint8))[0]
    small = track.__class__(track.id, track.cls,
                            track.box.__class__(100, 300, 150, 500), track.conf, track.anchor)
    result = detector.helmet_observation(np.zeros((600, 800, 3), dtype=np.uint8), small).result
    assert result.label == "unclear"
    assert result.reason == "TOO_SMALL"
