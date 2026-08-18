"""The modelled legs of a rail journey.

None of these are measured, so the tests pin the shape of the assumptions rather
than any real-world number. What matters is that a modelled leg is a
distribution rather than a point, because a point cannot be convolved and would
quietly reintroduce the additive error the project exists to avoid.
"""

import pytest

from data_prep.histogram import percentile, total
from data_prep.rail_times import CONNECTORS, AIRTRAIN_RIDE, uniform, wait_from_median


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


def test_every_connector_has_a_modelled_airtrain_leg():
    for connector in CONNECTORS.values():
        assert connector in AIRTRAIN_RIDE
        low, high = AIRTRAIN_RIDE[connector]
        assert 0 < low < high


@pytest.mark.parametrize("route", ["A", "E", "J", "Z"])
def test_the_four_jfk_routes_are_covered(route):
    assert route in CONNECTORS
