"""Time blocks have to match stringline's exactly, because the whole comparison
depends on the car side and the rail side describing the same hours.
"""

import pytest

from data_prep.blocks import BLOCKS, block_at, block_bounds


def test_the_blocks_are_stringlines_blocks():
    # Lifted from stringline's site/data/system.json. If these ever disagree,
    # the comparison in this project is measuring two different afternoons.
    assert BLOCKS == [
        ("early", 0, 420),
        ("am", 420, 600),
        ("midday", 600, 960),
        ("pm", 960, 1140),
        ("evening", 1140, 1440),
    ]


def test_the_blocks_tile_the_whole_day_without_gaps_or_overlap():
    assert BLOCKS[0][1] == 0
    assert BLOCKS[-1][2] == 1440
    for (_, _, end), (_, start, _) in zip(BLOCKS, BLOCKS[1:]):
        assert end == start


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (0, 0, "early"),
        (6, 59, "early"),
        (7, 0, "am"),
        (9, 59, "am"),
        (10, 0, "midday"),
        (15, 59, "midday"),
        (16, 0, "pm"),
        (18, 59, "pm"),
        (19, 0, "evening"),
        (23, 59, "evening"),
    ],
)
def test_block_at_puts_each_boundary_on_the_later_side(hour, minute, expected):
    assert block_at(hour, minute) == expected


def test_block_at_rejects_impossible_clock_times():
    with pytest.raises(ValueError):
        block_at(24, 0)
    with pytest.raises(ValueError):
        block_at(12, 60)
    with pytest.raises(ValueError):
        block_at(-1, 0)


def test_block_bounds_returns_minutes_from_midnight():
    assert block_bounds("pm") == (960, 1140)


def test_block_bounds_rejects_unknown_names():
    with pytest.raises(KeyError):
        block_bounds("rush")
