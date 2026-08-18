"""The modelled legs of a rail journey.

None of these are measured, so the tests pin the shape of the assumptions rather
than any real-world number. What matters is that a modelled leg is a
distribution rather than a point, because a point cannot be convolved and would
quietly reintroduce the additive error the project exists to avoid.
"""

import pytest

from data_prep.histogram import percentile, total
from data_prep.transit_times import LINKS, uniform, wait_from_median


def test_uniform_covers_the_range_inclusively():
    h = uniform(3, 6)
    assert total(h) == 4
    assert h[2] == 0 and h[3] == 1 and h[6] == 1 and h[7] == 0


def test_wait_from_median_has_that_median():
    # A five minute median wait implies a ten minute headway and a wait spread
    # evenly from nothing to ten.
    h = wait_from_median(5)
    assert percentile(h, 0.5) == 5
    assert h[0] == 1
    assert h[10] == 1
    assert h[11] == 0


def test_wait_from_median_is_a_spread_not_a_point():
    """A median treated as a constant would understate the tail of every
    journey it appears in, which is exactly the mistake being avoided."""
    h = wait_from_median(6)
    assert percentile(h, 0.9) > percentile(h, 0.5)


def test_wait_from_median_survives_a_zero_median():
    h = wait_from_median(0)
    assert total(h) > 0
    assert percentile(h, 0.5) >= 0


def test_every_link_models_a_wait_as_a_range():
    for links in LINKS.values():
        for link in links:
            low, high = link["link_wait"]
            assert 0 <= low < high


def test_the_airtrain_links_carry_their_own_ride_range():
    for link in LINKS["JFK"]:
        low, high = link["link_ride"]
        assert 0 < low < high


def test_the_bus_links_take_their_ride_from_measured_data():
    """LGA link rides are not hard-coded; they come from bus.json per block."""
    for link in LINKS["LGA"]:
        assert "link_ride" not in link


@pytest.mark.parametrize("route", ["A", "E", "J", "Z"])
def test_the_four_jfk_routes_are_covered(route):
    assert any(route in link["routes"] for link in LINKS["JFK"])


@pytest.mark.parametrize("route", ["7", "E", "F", "M", "R"])
def test_the_q70_feeder_routes_are_covered(route):
    assert any(route in link["routes"] for link in LINKS["LGA"])
