from ai_engine.zone import Zone


SQUARE = [(100, 100), (200, 100), (200, 200), (100, 200)]
LINE = [(150, 50), (150, 250)]


def test_points_moving_across_a_polygon_fire_once():
    zone = Zone(SQUARE)
    # Start outside, step onto the left edge, then into the middle.
    assert zone.crossed(1, (50, 150)) is False
    assert zone.crossed(1, (100, 150)) is True
    assert zone.crossed(1, (150, 150)) is False


def test_repeated_points_inside_the_zone_do_not_fire_again():
    zone = Zone(SQUARE)
    assert zone.crossed(7, (80, 150)) is False
    assert zone.crossed(7, (150, 150)) is True
    assert zone.crossed(7, (150, 150)) is False
    assert zone.crossed(7, (160, 160)) is False
    assert zone.crossed(7, (140, 140)) is False


def test_vehicle_crossing_a_line_fires_once():
    zone = Zone(LINE)
    assert zone.crossed(3, (120, 150)) is False
    assert zone.crossed(3, (180, 150)) is True
    assert zone.crossed(3, (190, 150)) is False


def test_vehicle_should_not_repeatedly_trigger_the_same_crossing():
    zone = Zone(SQUARE)
    assert zone.crossed(4, (50, 150)) is False
    assert zone.crossed(4, (150, 150)) is True
    # Leave and re-enter: same track ID must not fire again.
    assert zone.crossed(4, (250, 150)) is False
    assert zone.crossed(4, (150, 150)) is False
    # A different vehicle can still fire.
    assert zone.crossed(5, (50, 150)) is False
    assert zone.crossed(5, (150, 150)) is True


def test_vehicle_disappearing_far_from_the_zone_does_not_fire():
    zone = Zone(SQUARE, lost_near_distance=40)
    assert zone.crossed(8, (10, 10)) is False
    assert zone.lost(8) is False


def test_lost_near_the_zone_fires_once():
    zone = Zone(SQUARE, lost_near_distance=40)
    # Last seen just outside the left edge (x=90, edge is x=100).
    assert zone.crossed(9, (90, 150)) is False
    assert zone.lost(9) is True
    # Same ID must not fire again if it later reappears.
    assert zone.lost(9) is False
    assert zone.crossed(9, (150, 150)) is False


def test_lost_after_an_already_fired_crossing_does_not_duplicate():
    zone = Zone(SQUARE, lost_near_distance=40)
    assert zone.crossed(2, (50, 150)) is False
    assert zone.crossed(2, (150, 150)) is True
    assert zone.lost(2) is False


def test_normalised_vertices_scale_with_frame_size():
    zone = Zone([(0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)], frame_size=(400, 400))
    assert zone.crossed(1, (50, 200)) is False
    assert zone.crossed(1, (200, 200)) is True


def test_forget_removes_old_track_state():
    zone = Zone(SQUARE)
    zone.crossed(11, (150, 150))
    assert zone.forget_missing({99}) == [11]
    # After cleanup, the same ID can be treated as a new vehicle.
    assert zone.crossed(11, (150, 150)) is True
