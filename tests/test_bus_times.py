"""The bus unit check.

`average_travel_time` looks like seconds on short segments and is actually
minutes. The guard that catches a change of unit is the only thing standing
between this project and a fifteen minute bus reported as fifteen seconds, so it
gets tested against both a good feed and a broken one.
"""

import pytest

from data_prep.bus_times import verify_units

LEG = {"route_id": "Q70+"}


def rows(travel_time, n=20, distance=3.99, speed=15.0):
    return [
        {
            "road_distance": str(distance),
            "average_road_speed": str(speed),
            "average_travel_time": str(travel_time),
        }
        for _ in range(n)
    ]


def test_minutes_are_accepted():
    # 3.99 miles at 15 mph is 15.96 minutes.
    verify_units(rows(15.96), "kufs-yh3x", LEG)


def test_seconds_would_be_rejected():
    """If the column ever switched to seconds the numbers would be sixty times
    too small, and every bus in the project would look impossibly fast."""
    with pytest.raises(RuntimeError, match="does not match"):
        verify_units(rows(15.96 * 60), "kufs-yh3x", LEG)


def test_a_small_disagreement_is_tolerated():
    verify_units(rows(16.2), "kufs-yh3x", LEG)


def test_too_few_rows_is_an_error_not_a_pass():
    """An empty or near-empty response must not be mistaken for a clean check."""
    with pytest.raises(RuntimeError, match="too few rows"):
        verify_units(rows(15.96, n=3), "kufs-yh3x", LEG)


def test_unusable_rows_do_not_count_towards_the_check():
    bad = [{"road_distance": "1", "average_road_speed": "0", "average_travel_time": "5"}] * 50
    with pytest.raises(RuntimeError, match="too few rows"):
        verify_units(bad, "kufs-yh3x", LEG)
