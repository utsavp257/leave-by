"""Airport trip times from the city's trip records, one month at a time.

The files live on a CDN as parquet, and the ride-hail ones run to half a
gigabyte a month. None of them get downloaded. DuckDB reads them over HTTP and
only pulls the columns and row groups a query touches, so asking for trips that
ended at JFK costs a fraction of the file and takes seconds.

What comes back is not trips but counts: for each airport, origin zone, part of
the day and whole minute of travel time, how many trips there were. That is a
histogram in long form, it merges across months by addition, and it is small
enough to keep in the repository.

Two sources, because from Manhattan a yellow cab is a real choice and from
anywhere else it mostly is not:

    fhvhv   Uber and Lyft. HV0003 is Uber, HV0005 is Lyft.
    yellow  Yellow medallion taxis.

Fares get the same treatment as times, in a second file: counts per whole
dollar rather than a running total. That is deliberate. These files carry every
service tier, so an average is dragged upwards by Uber Black, SUVs and surge,
and would price a journey no ordinary reader is taking. A median from a
histogram is robust to all three, and merges across months the same way the
travel times do.

A note on trip_time. In the ride-hail files it is seconds, which is easy to
misread as minutes and would quietly divide every answer by sixty. Rather than
trust that, `verify_units` checks the column against the gap between the pickup
and dropoff timestamps before any month is accepted.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from data_prep.blocks import sql_block_expression
from data_prep.histogram import MAX_MINUTES

MAX_FARE = 300
"""Dollars. The final bucket means "this much or more"."""

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "tlc"
BASE = "https://d37ci6vzurychx.cloudfront.net/trip-data"

AIRPORTS = {132: "JFK", 138: "LGA", 1: "EWR"}
"""Destination zone ids, from taxi_zone_lookup.csv."""

COMPANIES = {"HV0003": "Uber", "HV0005": "Lyft"}
"""Ride-hail licence numbers still operating. HV0002 (Juno) and HV0004 (Via)
appear in older files and are both defunct."""


@dataclass(frozen=True)
class Source:
    name: str
    prefix: str
    pickup: str
    dropoff: str
    # Seconds of travel time. Yellow has no such column and it is derived.
    duration_seconds: str
    # What the rider is charged, tips excluded - a tip is a choice, not a fare.
    # Named columns rather than a SQL string, because which of them exist
    # depends on the month. See `fare_expression`.
    fare_add: tuple
    fare_sub: tuple = ()
    required: str = ""
    company: str | None = None

    def url(self, year: int, month: int) -> str:
        return f"{BASE}/{self.prefix}_{year:04d}-{month:02d}.parquet"


SOURCES = {
    "fhvhv": Source(
        name="fhvhv",
        prefix="fhvhv_tripdata",
        pickup="pickup_datetime",
        dropoff="dropoff_datetime",
        duration_seconds="trip_time",
        fare_add=(
            "base_passenger_fare", "tolls", "bcf", "sales_tax",
            "congestion_surcharge", "airport_fee", "cbd_congestion_fee",
        ),
        required="base_passenger_fare",
        company="hvfhs_license_num",
    ),
    "yellow": Source(
        name="yellow",
        prefix="yellow_tripdata",
        pickup="tpep_pickup_datetime",
        dropoff="tpep_dropoff_datetime",
        duration_seconds="date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)",
        # total_amount includes the tip, so it is taken back out.
        fare_add=("total_amount",),
        fare_sub=("tip_amount",),
        required="total_amount",
    ),
}


def columns_of(con, url: str) -> dict[str, str]:
    """Lower-cased column name to its actual spelling in this file.

    Reads the parquet footer only, so it costs a range request rather than a
    download.
    """
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{url}')").fetchall()
    return {row[0].lower(): row[0] for row in rows}


def fare_expression(source: Source, available: dict[str, str]) -> tuple[str, list[str]]:
    """Build the fare sum from the columns this month actually has.

    TLC's schema moves. `cbd_congestion_fee` only appears once congestion
    pricing starts in 2025, and `airport_fee` has shipped as both `airport_fee`
    and `Airport_fee` in different months. A fixed SQL string binds fine against
    one month and fails against the next, so the expression is assembled per
    file and the missing pieces are reported rather than assumed to be zero.
    """
    if source.required and source.required.lower() not in available:
        raise RuntimeError(
            f"{source.name}: no {source.required} column - the schema has changed "
            f"in a way this pipeline cannot interpret."
        )

    terms, missing = [], []
    for name in source.fare_add:
        actual = available.get(name.lower())
        terms.append(f"coalesce({actual},0)") if actual else missing.append(name)
    for name in source.fare_sub:
        actual = available.get(name.lower())
        terms.append(f"-coalesce({actual},0)") if actual else missing.append(name)

    return " + ".join(terms).replace("+ -", "- "), missing


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    return con


def fetch_month(con, source: Source, year: int, month: int):
    """Pull one month's airport arrivals into the cache.

    The whole month is read exactly once. An earlier version scanned the remote
    file three times - once to check units, once for travel times, once for
    fares - which is three times the load on a CDN that throttles, and it did
    throttle. Everything now lands in a temporary table first and the checks and
    aggregates run against that.
    """
    url = source.url(year, month)
    available = columns_of(con, url)
    fare, missing = fare_expression(source, available)
    if missing:
        print(f"{source.name} {year}-{month:02d}  no {', '.join(missing)} this month")

    duration = source.duration_seconds
    airport_ids = ", ".join(str(i) for i in AIRPORTS)
    company = f"{source.company} AS company," if source.company else "'' AS company,"

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE trips AS
        SELECT
            DOLocationID AS airport,
            PULocationID AS origin,
            {company}
            {sql_block_expression(source.pickup)} AS block,
            least(cast(floor(({duration}) / 60.0) AS INTEGER), {MAX_MINUTES}) AS minutes,
            least(cast(round({fare}) AS INTEGER), {MAX_FARE}) AS dollars,
            ({duration}) AS seconds,
            date_diff('second', {source.pickup}, {source.dropoff}) AS delta
        FROM read_parquet('{url}')
        WHERE DOLocationID IN ({airport_ids})
          AND PULocationID IS NOT NULL
          AND {source.pickup} IS NOT NULL AND {source.dropoff} IS NOT NULL
          AND ({duration}) > 0 AND ({duration}) < 60 * 60 * 6
          AND ({fare}) BETWEEN 0 AND 500
          AND dayofweek({source.pickup}) BETWEEN 1 AND 5
    """)

    verify_units(con, source, url)

    out = CACHE / f"{source.name}_{year:04d}-{month:02d}.parquet"
    fares_out = CACHE / f"{source.name}_{year:04d}-{month:02d}_fare.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)

    con.execute(f"""COPY (
        SELECT airport, origin, company, block, minutes, count(*) AS n
        FROM trips GROUP BY ALL) TO '{out}' (FORMAT PARQUET)""")
    con.execute(f"""COPY (
        SELECT airport, origin, block, dollars, count(*) AS n
        FROM trips GROUP BY ALL) TO '{fares_out}' (FORMAT PARQUET)""")

    written = con.execute(f"SELECT count(*), sum(n) FROM read_parquet('{out}')").fetchone()
    con.execute("DROP TABLE trips")
    return written


UNIT_RATIO_RANGE = (0.5, 2.0)
"""How far the duration column may drift from the timestamps before it is
treated as a different unit. Wide on purpose: the mistake being caught is
minutes reported as seconds, which shows up as a ratio near 60 or near 1/60,
not as a few seconds of disagreement."""


def unit_ratio_ok(ratio) -> bool:
    if ratio is None:
        return False
    low, high = UNIT_RATIO_RANGE
    return low <= ratio <= high


def verify_units(con, source: Source, url: str) -> None:
    """Confirm the duration column is in the same unit as the timestamps.

    Compares the two as a ratio rather than a difference. An earlier version
    allowed twelve seconds of absolute drift and rejected May 2026, where the
    median trip_time is 2674 seconds against a timestamp delta of 2649 - a ratio
    of exactly 1.0 and about twenty seconds of ordinary reporting noise between
    what the app clocked and what the timestamps say. An absolute tolerance
    cannot tell that apart from a real problem; a ratio can, and it still catches
    the failure that matters, where minutes are reported as seconds and the ratio
    lands near sixty or near a sixtieth.
    """
    n, ratio = con.execute(
        "SELECT count(*), median(seconds / nullif(delta, 0)) FROM trips WHERE seconds > 600"
    ).fetchone()
    if not n:
        raise RuntimeError(f"{url}: no usable rows to check units against")
    if not unit_ratio_ok(ratio):
        raise RuntimeError(
            f"{url}: {source.duration_seconds} is {ratio:.4g}x the gap between the "
            f"timestamps. It is probably no longer in seconds - check the data "
            f"dictionary before trusting any output."
        )


def http_status(exc) -> int | None:
    """The status code behind a DuckDB HTTP error, however it is reported."""
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    found = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(found.group(1)) if found else None


def read_with_retry(read, label: str, attempts: int = 5):
    """Run a remote read, telling "not there" apart from "slow down".

    Shared rather than reimplemented. The distinction was originally worked out
    for the monthly corpus fetch and then quietly lost when a second reader was
    written from scratch, which reported every throttle as a missing month.
    Returns (result, reason): reason is set only when the data is genuinely absent.
    """
    for attempt in range(1, attempts + 1):
        try:
            return read(), None
        except duckdb.HTTPException as exc:
            status = http_status(exc)
            if status == 404:
                return None, "not published yet"
            if attempt == attempts:
                return None, f"HTTP {status} after {attempts} attempts"
            pause = 30 * 2 ** (attempt - 1)
            print(f"{label}  HTTP {status}, retrying in {pause}s", flush=True)
            time.sleep(pause)
    return None, "unreachable"


def fetch_with_retry(con, source: Source, year: int, month: int, attempts: int = 5):
    """Fetch a month, telling "not published yet" apart from "slow down".

    This distinction matters more than it looks. DuckDB's HTTPException is a
    subclass of IOException, so a single `except IOException` swallows a 403 from
    the CDN and reports it as a missing month. Across a long backfill that
    quietly drops data and still exits zero, leaving a corpus with holes in it
    that nothing downstream can detect.

    A 404 is genuinely absent - TLC publishes about two months behind - and is
    reported as skipped. Throttling and server errors are retried with a
    lengthening pause, and if they survive that they are raised, because a
    backfill that silently loses a year is worse than one that stops.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fetch_month(con, source, year, month), None
        except duckdb.HTTPException as exc:
            status = http_status(exc)
            if status == 404:
                return None, "not published yet"
            if attempt == attempts:
                raise RuntimeError(
                    f"{source.name} {year}-{month:02d}: HTTP {status} after "
                    f"{attempts} attempts. Stopping rather than leaving a hole."
                ) from exc
            # 30s, 60s, 120s, 240s. The CDN sheds load for minutes, not
            # seconds, and an impatient retry just confirms it should keep doing so.
            pause = 30 * 2 ** (attempt - 1)
            print(f"{source.name} {year}-{month:02d}  HTTP {status}, retrying in {pause}s")
            time.sleep(pause)
    return None, "unreachable"


def months(start: str, end: str):
    """Inclusive range of YYYY-MM strings."""
    sy, sm = (int(p) for p in start.split("-"))
    ey, em = (int(p) for p in end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("start", help="first month, as YYYY-MM")
    parser.add_argument("end", nargs="?", help="last month, defaults to start")
    parser.add_argument(
        "--source", choices=sorted(SOURCES), default="fhvhv",
    )
    parser.add_argument(
        "--force", action="store_true", help="refetch months already cached",
    )
    parser.add_argument(
        "--pause", type=float, default=4.0,
        help="seconds between months, to stay under the CDN's rate limit",
    )
    args = parser.parse_args(argv)

    source = SOURCES[args.source]
    con = connect()

    fetched = cached = 0
    skipped = []

    for year, month in months(args.start, args.end or args.start):
        out = CACHE / f"{source.name}_{year:04d}-{month:02d}.parquet"
        if out.exists() and not args.force:
            print(f"{source.name} {year}-{month:02d}  cached")
            cached += 1
            continue

        result, reason = fetch_with_retry(con, source, year, month)
        if result is None:
            print(f"{source.name} {year}-{month:02d}  skipped ({reason})")
            skipped.append(f"{year}-{month:02d} ({reason})")
            continue

        rows, trips = result
        print(f"{source.name} {year}-{month:02d}  {rows:>7,} bins  {trips:>9,} trips", flush=True)
        fetched += 1
        if args.pause:
            time.sleep(args.pause)

    print(f"\n{fetched} fetched, {cached} already cached, {len(skipped)} skipped")
    if skipped:
        # Named rather than counted, so a hole in the corpus is visible in the
        # log instead of being inferred later from a thin-looking map.
        print("skipped: " + ", ".join(skipped))

    return 0


if __name__ == "__main__":
    sys.exit(main())
