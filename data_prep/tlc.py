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
import sys
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
    fare: str
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
        fare=(
            "coalesce(base_passenger_fare,0) + coalesce(tolls,0) + coalesce(bcf,0)"
            " + coalesce(sales_tax,0) + coalesce(congestion_surcharge,0)"
            " + coalesce(airport_fee,0) + coalesce(cbd_congestion_fee,0)"
        ),
        company="hvfhs_license_num",
    ),
    "yellow": Source(
        name="yellow",
        prefix="yellow_tripdata",
        pickup="tpep_pickup_datetime",
        dropoff="tpep_dropoff_datetime",
        duration_seconds="date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)",
        # total_amount includes the tip, so it is taken back out.
        fare="coalesce(total_amount,0) - coalesce(tip_amount,0)",
    ),
}


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    return con


def verify_units(con, source: Source, url: str, tolerance: float = 0.02) -> None:
    """Confirm the duration column really is seconds.

    Compares it against the gap between the two timestamps on trips long enough
    that rounding cannot explain a mismatch. If the column ever changes unit, or
    a source swaps minutes for seconds, this fails loudly here rather than
    producing a plausible-looking answer that is wrong by a factor of sixty.
    """
    row = con.execute(
        f"""
        SELECT count(*) AS n,
               avg(abs(({source.duration_seconds})
                   - date_diff('second', {source.pickup}, {source.dropoff}))) AS gap
        FROM read_parquet('{url}')
        WHERE {source.pickup} IS NOT NULL
          AND {source.dropoff} IS NOT NULL
          AND ({source.duration_seconds}) > 600
        LIMIT 1
        """
    ).fetchone()

    n, gap = row
    if not n:
        raise RuntimeError(f"{url}: no usable rows to check units against")
    if gap is None or gap > 600 * tolerance:
        raise RuntimeError(
            f"{url}: {source.duration_seconds} disagrees with the timestamps by "
            f"{gap:.0f} seconds on average. It may no longer be in seconds - "
            f"check the data dictionary before trusting any output."
        )


def fetch_month(con, source: Source, year: int, month: int) -> int:
    """Pull one month's airport arrivals into the cache. Returns rows written."""
    url = source.url(year, month)
    verify_units(con, source, url)

    company = f"{source.company} AS company," if source.company else "'' AS company,"
    airport_ids = ", ".join(str(i) for i in AIRPORTS)
    out = CACHE / f"{source.name}_{year:04d}-{month:02d}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)

    con.execute(
        f"""
        COPY (
            SELECT
                DOLocationID AS airport,
                PULocationID AS origin,
                {company}
                {sql_block_expression(source.pickup)} AS block,
                least(cast(floor(({source.duration_seconds}) / 60.0) AS INTEGER),
                      {MAX_MINUTES}) AS minutes,
                count(*) AS n
            FROM read_parquet('{url}')
            WHERE DOLocationID IN ({airport_ids})
              AND PULocationID IS NOT NULL
              AND dayofweek({source.pickup}) BETWEEN 1 AND 5
              AND ({source.duration_seconds}) > 0
              AND ({source.duration_seconds}) < 60 * 60 * 6
              AND ({source.fare}) BETWEEN 0 AND 500
            GROUP BY ALL
        ) TO '{out}' (FORMAT PARQUET)
        """
    )

    fares = CACHE / f"{source.name}_{year:04d}-{month:02d}_fare.parquet"
    con.execute(
        f"""
        COPY (
            SELECT
                DOLocationID AS airport,
                PULocationID AS origin,
                {sql_block_expression(source.pickup)} AS block,
                least(cast(round({source.fare}) AS INTEGER), {MAX_FARE}) AS dollars,
                count(*) AS n
            FROM read_parquet('{url}')
            WHERE DOLocationID IN ({airport_ids})
              AND PULocationID IS NOT NULL
              AND dayofweek({source.pickup}) BETWEEN 1 AND 5
              AND ({source.duration_seconds}) > 0
              AND ({source.duration_seconds}) < 60 * 60 * 6
              AND ({source.fare}) BETWEEN 0 AND 500
            GROUP BY ALL
        ) TO '{fares}' (FORMAT PARQUET)
        """
    )

    written = con.execute(
        f"SELECT count(*), sum(n) FROM read_parquet('{out}')"
    ).fetchone()
    return written


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
    args = parser.parse_args(argv)

    source = SOURCES[args.source]
    con = connect()

    for year, month in months(args.start, args.end or args.start):
        out = CACHE / f"{source.name}_{year:04d}-{month:02d}.parquet"
        if out.exists() and not args.force:
            print(f"{source.name} {year}-{month:02d}  cached")
            continue
        try:
            rows, trips = fetch_month(con, source, year, month)
        except duckdb.IOException as exc:
            # A month that is not published yet is expected, not an error. TLC
            # runs about two months behind.
            print(f"{source.name} {year}-{month:02d}  unavailable ({exc.__class__.__name__})")
            continue
        print(f"{source.name} {year}-{month:02d}  {rows:>7,} bins  {trips:>9,} trips")

    return 0


if __name__ == "__main__":
    sys.exit(main())
