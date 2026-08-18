"""When the page is allowed to say one mode beats the other.

The inputs are not equally precise and none of them are precise to the minute, so
a small difference is not a result. The verdict rule refuses to call anything
under five minutes, and these tests hold it to that - including at the boundary,
which is where a rule like this usually rots.
"""

import pytest

from data_prep.leave_by import MEANINGFUL_MINUTES, verdict


def test_a_clear_transit_win():
    assert verdict(car_p90=102, transit_p90=71) == "transit"


def test_a_clear_car_win():
    assert verdict(car_p90=40, transit_p90=75) == "car"


@pytest.mark.parametrize("difference", [0, 1, MEANINGFUL_MINUTES - 1])
def test_small_differences_are_a_draw_either_way(difference):
    assert verdict(60, 60 - difference) == "too close to call"
    assert verdict(60 - difference, 60) == "too close to call"


def test_the_threshold_itself_counts_as_a_result():
    assert verdict(60, 60 - MEANINGFUL_MINUTES) == "transit"
    assert verdict(60 - MEANINGFUL_MINUTES, 60) == "car"


def test_one_sided_coverage_is_reported_not_guessed():
    assert verdict(car_p90=55, transit_p90=None) == "car only"
    assert verdict(car_p90=None, transit_p90=55) == "transit only"


def test_no_data_at_all():
    assert verdict(None, None) == "unknown"
