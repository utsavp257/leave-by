"""The SQL form of the block boundaries has to agree with the Python form.

They exist separately because the car side cuts fifty million rows inside DuckDB
while the rail side works on a few hundred stringline aggregates in Python. Two
implementations of one rule is a standing invitation to drift, so this test runs
both over every minute of the day and demands they match.
"""

import duckdb
import pytest

from data_prep.blocks import BLOCK_NAMES, block_at, sql_block_expression


@pytest.fixture(scope="module")
def sql_blocks():
    """Every minute of the day, classified by the SQL expression."""
    expression = sql_block_expression("t")
    rows = duckdb.sql(
        f"""
        WITH minutes AS (
            SELECT TIMESTAMP '2026-04-01 00:00:00' + INTERVAL (i) MINUTE AS t
            FROM range(0, 1440) AS r(i)
        )
        SELECT hour(t) AS h, minute(t) AS m, {expression} AS block FROM minutes
        """
    ).fetchall()
    return {(h, m): block for h, m, block in rows}


def test_sql_and_python_agree_on_every_minute_of_the_day(sql_blocks):
    assert len(sql_blocks) == 1440
    mismatches = [
        (h, m, block, block_at(h, m))
        for (h, m), block in sql_blocks.items()
        if block != block_at(h, m)
    ]
    assert mismatches == []


def test_sql_never_returns_null(sql_blocks):
    assert all(block is not None for block in sql_blocks.values())


def test_sql_uses_every_block(sql_blocks):
    assert set(sql_blocks.values()) == set(BLOCK_NAMES)
