"""The fare sum has to survive TLC changing its own schema.

Two things move between months. `cbd_congestion_fee` does not exist before
congestion pricing starts in 2025, and `airport_fee` has shipped under different
capitalisation. A fixed SQL string binds happily against one month and throws a
binder error against the next, which is how a forty-month backfill dies four
seconds in.
"""

import pytest

from data_prep.tlc import SOURCES, fare_expression

FHVHV = SOURCES["fhvhv"]
YELLOW = SOURCES["yellow"]

MODERN = {
    "base_passenger_fare": "base_passenger_fare",
    "tolls": "tolls",
    "bcf": "bcf",
    "sales_tax": "sales_tax",
    "congestion_surcharge": "congestion_surcharge",
    "airport_fee": "airport_fee",
    "cbd_congestion_fee": "cbd_congestion_fee",
}


def test_a_modern_month_uses_every_component():
    expression, missing = fare_expression(FHVHV, MODERN)
    assert missing == []
    for column in MODERN:
        assert column in expression


def test_a_2023_month_drops_the_congestion_fee_and_says_so():
    before_tolling = {k: v for k, v in MODERN.items() if k != "cbd_congestion_fee"}
    expression, missing = fare_expression(FHVHV, before_tolling)
    assert missing == ["cbd_congestion_fee"]
    assert "cbd_congestion_fee" not in expression
    assert "base_passenger_fare" in expression


def test_capitalisation_is_followed_not_assumed():
    """TLC has shipped this column as `Airport_fee`. Emitting the lower-cased
    name would fail to bind even though the column is right there."""
    odd = dict(MODERN)
    del odd["airport_fee"]
    odd["airport_fee"] = "Airport_fee"
    expression, missing = fare_expression(FHVHV, odd)
    assert missing == []
    assert "coalesce(Airport_fee,0)" in expression


def test_a_missing_required_column_is_an_error_not_a_zero():
    """Silently treating the base fare as zero would produce a plausible column
    of very cheap trips rather than an obvious failure."""
    with pytest.raises(RuntimeError, match="base_passenger_fare"):
        fare_expression(FHVHV, {"tolls": "tolls"})


def test_yellow_subtracts_the_tip():
    expression, missing = fare_expression(
        YELLOW, {"total_amount": "total_amount", "tip_amount": "tip_amount"}
    )
    assert missing == []
    assert "- coalesce(tip_amount,0)" in expression


def test_yellow_without_a_tip_column_still_builds():
    expression, missing = fare_expression(YELLOW, {"total_amount": "total_amount"})
    assert missing == ["tip_amount"]
    assert expression == "coalesce(total_amount,0)"


def test_the_unit_guard_accepts_ordinary_noise_and_rejects_a_unit_change():
    """May 2026 has a median trip_time of 2674s against a 2649s timestamp gap -
    a ratio of 1.0 with about twenty seconds of reporting noise. An absolute
    tolerance rejected that month; a ratio does not, while still catching the
    minutes-reported-as-seconds mistake the check exists for."""
    from data_prep.tlc import unit_ratio_ok

    assert unit_ratio_ok(1.0)
    assert unit_ratio_ok(2674 / 2649)
    assert not unit_ratio_ok(1 / 60)
    assert not unit_ratio_ok(60.0)
    assert not unit_ratio_ok(None)
