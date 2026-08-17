"""The five parts of the day, borrowed from stringline.

These are not equal slices of the clock. They are the blocks a rider would
recognise - the early hours, the morning, the long middle, the evening rush,
and the night - and stringline already publishes its subway numbers cut this
way.

The car data is timestamped to the second and could be cut far finer. It is cut
to these blocks anyway, because a comparison is only honest at the resolution of
its coarser side. Hourly cars set against block-level trains would invite a
reader to draw conclusions the train data cannot support.
"""

from __future__ import annotations

BLOCKS: list[tuple[str, int, int]] = [
    ("early", 0, 420),
    ("am", 420, 600),
    ("midday", 600, 960),
    ("pm", 960, 1140),
    ("evening", 1140, 1440),
]
"""Name, start and end in minutes from midnight. Start inclusive, end exclusive.
Copied from stringline's site/data/system.json - a test asserts they still
agree, because a silent divergence here would compare two different afternoons.
"""

BLOCK_NAMES: list[str] = [name for name, _, _ in BLOCKS]


def block_at(hour: int, minute: int = 0) -> str:
    """Which block a local wall-clock time falls in."""
    if not 0 <= hour <= 23:
        raise ValueError(f"hour out of range: {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute out of range: {minute}")

    since_midnight = hour * 60 + minute
    for name, start, end in BLOCKS:
        if start <= since_midnight < end:
            return name
    raise ValueError(f"no block covers {hour:02d}:{minute:02d}")


def block_bounds(name: str) -> tuple[int, int]:
    """Start and end of a block, in minutes from midnight."""
    for block_name, start, end in BLOCKS:
        if block_name == name:
            return start, end
    raise KeyError(name)


def sql_block_expression(timestamp_column: str) -> str:
    """The same block boundaries as a SQL CASE, for pushing the work into
    DuckDB rather than pulling millions of timestamps back to Python."""
    minutes = f"(hour({timestamp_column}) * 60 + minute({timestamp_column}))"
    arms = "\n".join(
        f"        WHEN {minutes} >= {start} AND {minutes} < {end} THEN '{name}'"
        for name, start, end in BLOCKS
    )
    return f"CASE\n{arms}\n    END"
