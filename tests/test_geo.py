"""Point-in-polygon, written by hand and therefore tested by hand.

The failure this guards against is subtle and total: swap longitude and latitude
and every station lands outside every zone, or worse, inside the wrong one. A
silently empty join would look like "no subway here" rather than like a bug.
"""

from data_prep.geo import point_in_geometry, point_in_polygon, point_in_ring

SQUARE = [[0, 0], [0, 10], [10, 10], [10, 0]]
HOLE = [[3, 3], [3, 7], [7, 7], [7, 3]]


def test_a_point_inside_a_square():
    assert point_in_ring(5, 5, SQUARE)


def test_a_point_outside_a_square():
    assert not point_in_ring(15, 5, SQUARE)
    assert not point_in_ring(5, 15, SQUARE)
    assert not point_in_ring(-1, 5, SQUARE)


def test_a_hole_is_not_inside_the_polygon():
    assert point_in_polygon(1, 1, [SQUARE, HOLE])
    assert not point_in_polygon(5, 5, [SQUARE, HOLE])


def test_an_empty_polygon_contains_nothing():
    assert not point_in_polygon(1, 1, [])


def test_multipolygon_checks_every_part():
    far = [[100, 100], [100, 110], [110, 110], [110, 100]]
    geometry = {"type": "MultiPolygon", "coordinates": [[SQUARE], [far]]}
    assert point_in_geometry(5, 5, geometry)
    assert point_in_geometry(105, 105, geometry)
    assert not point_in_geometry(50, 50, geometry)


def test_plain_polygon_geometry_is_handled():
    geometry = {"type": "Polygon", "coordinates": [SQUARE]}
    assert point_in_geometry(5, 5, geometry)


def test_unknown_geometry_types_are_not_inside():
    assert not point_in_geometry(5, 5, {"type": "Point", "coordinates": [5, 5]})


def test_a_concave_shape_does_not_swallow_its_notch():
    """A rectangle with a bite out of the right side. The bite is outside."""
    c_shape = [[0, 0], [0, 10], [10, 10], [10, 7], [4, 7], [4, 3], [10, 3], [10, 0]]
    assert point_in_ring(2, 5, c_shape)
    assert not point_in_ring(7, 5, c_shape)
    assert point_in_ring(7, 1, c_shape)
