"""The histogram is the only place in this project where the statistics can go
quietly wrong, so it gets tested first and hardest.

The property that matters most is the last one: adding two percentiles together
overstates the percentile of the sum. Every door-to-door number in this project
is a wait plus a ride plus a transfer, and the tempting shortcut - add the p90s -
produces a figure that is too pessimistic and has no interpretation at all.
"""

import pytest

from data_prep.histogram import (
    convolve,
    from_samples,
    merge,
    percentile,
    total,
)


def test_from_samples_counts_each_minute():
    h = from_samples([1, 1, 3], max_minutes=5)
    assert h == [0, 2, 0, 1, 0, 0]


def test_from_samples_clips_into_the_final_bin():
    # The last bin means "this long or longer", so a 99 minute trip in a
    # 5 minute histogram lands in bin 5 rather than being dropped.
    h = from_samples([99, 2], max_minutes=5)
    assert h == [0, 0, 1, 0, 0, 1]


def test_from_samples_rejects_negative_durations():
    with pytest.raises(ValueError):
        from_samples([-1], max_minutes=5)


def test_total_counts_observations_not_bins():
    assert total([0, 2, 0, 1]) == 3


def test_merge_adds_elementwise():
    assert merge([1, 0, 2], [0, 3, 1]) == [1, 3, 3]


def test_merge_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        merge([1, 0], [1, 0, 0])


def test_percentile_is_the_first_minute_reaching_the_quantile():
    # Ten observations, one per minute from 0 to 9. The 90th percentile is the
    # first minute whose cumulative count reaches 9 of 10, which is minute 8.
    h = from_samples(range(10), max_minutes=20)
    assert percentile(h, 0.5) == 4
    assert percentile(h, 0.9) == 8
    assert percentile(h, 1.0) == 9


def test_percentile_of_a_single_value():
    h = from_samples([7, 7, 7], max_minutes=20)
    assert percentile(h, 0.5) == 7
    assert percentile(h, 0.99) == 7


def test_percentile_needs_observations():
    with pytest.raises(ValueError):
        percentile([0, 0, 0], 0.5)


def test_percentile_rejects_quantiles_outside_the_unit_interval():
    h = from_samples([1], max_minutes=5)
    with pytest.raises(ValueError):
        percentile(h, 1.5)
    with pytest.raises(ValueError):
        percentile(h, -0.1)


def test_convolve_of_two_point_masses_lands_on_the_sum():
    a = from_samples([3], max_minutes=20)
    b = from_samples([4], max_minutes=20)
    assert percentile(convolve(a, b), 0.5) == 7


def test_convolve_preserves_the_number_of_observations_as_a_product():
    a = from_samples([1, 2], max_minutes=10)
    b = from_samples([3, 4, 5], max_minutes=10)
    assert total(convolve(a, b)) == 6


def test_convolve_clips_into_the_final_bin():
    a = from_samples([4], max_minutes=5)
    b = from_samples([4], max_minutes=5)
    out = convolve(a, b)
    assert len(out) == 6
    assert out[5] == 1


def test_adding_percentiles_overstates_the_percentile_of_the_sum():
    """The reason this project convolves instead of adding.

    Two independent trips, each uniform over 0..10 minutes. Each has a p90 of
    9 minutes, so the shortcut says the pair has a p90 of 18. The real answer,
    from the triangular distribution of the sum, is 16.
    """
    leg = from_samples(range(11), max_minutes=40)
    assert percentile(leg, 0.9) == 9

    both = convolve(leg, leg)
    assert percentile(both, 0.9) == 16

    shortcut = percentile(leg, 0.9) + percentile(leg, 0.9)
    assert percentile(both, 0.9) < shortcut


def test_convolution_is_commutative():
    a = from_samples([1, 2, 9], max_minutes=30)
    b = from_samples([0, 5], max_minutes=30)
    assert convolve(a, b) == convolve(b, a)
