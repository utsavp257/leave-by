"""The one comparison on this page that has to match somebody else's method.

Todd Schneider measured Midtown to JFK leaving between ten and eleven in the
morning, on weekdays, and got 38 minutes across taxi trips from 2009 to mid-2015.
To put a number beside that it has to be the same cell: the same origin zone, the
same single hour, the same day types.

The main corpus cannot answer it. That aggregates into five parts of the day, so
its midday figure covers ten in the morning to four in the afternoon and is
worse than Todd's hour by construction. Rather than quietly compare a six-hour
block against a one-hour measurement, this fetches the hour directly.

It is deliberately narrow - one origin, one destination, one hour - so it costs a
handful of column-projected reads rather than a corpus rebuild. The output is a
few numbers that the page reads instead of carrying them hard-coded, so the claim
in the headline is derived from data like everything else on it.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import duckdb

from data_prep.tlc import BASE, months

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

MIDTOWN = 161
JFK = 132
HOUR = 10
"""Ten in the morning: the hour Todd reported."""

TODD_MINUTES = 38
TODD_WINDOW = "2009 to mid-2015"


def fetch(con, source: str, month: str) -> list[float]:
    if source == "fhvhv":
        url = f"{BASE}/fhvhv_tripdata_{month}.parquet"
        pickup, duration = "pickup_datetime", "trip_time"
    else:
        url = f"{BASE}/yellow_tripdata_{month}.parquet"
        pickup = "tpep_pickup_datetime"
        duration = "date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime)"

    rows = con.execute(
        f"""
        SELECT ({duration}) / 60.0 AS minutes
        FROM read_parquet('{url}')
        WHERE DOLocationID = {JFK} AND PULocationID = {MIDTOWN}
          AND hour({pickup}) = {HOUR}
          AND dayofweek({pickup}) BETWEEN 1 AND 5
          AND ({duration}) > 0 AND ({duration}) < 60 * 60 * 6
        """
    ).fetchall()
    return [row[0] for row in rows]


def build(windows: dict, pause: float) -> dict:
    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")

    result = {"hour": HOUR, "origin": "Midtown Center", "airport": "JFK",
              "todd_minutes": TODD_MINUTES, "todd_window": TODD_WINDOW,
              "months": [], "modes": {}}

    for source, (start, end) in windows.items():
        samples: list[float] = []
        used: list[str] = []
        for year, month in months(start, end):
            label = f"{year:04d}-{month:02d}"
            try:
                got = fetch(con, source, label)
            except duckdb.HTTPException as exc:
                print(f"{source} {label}  unavailable ({exc.__class__.__name__})")
                continue
            if got:
                samples.extend(got)
                used.append(label)
                print(f"{source} {label}  {len(got):>5} trips")
            time.sleep(pause)

        if not samples:
            raise RuntimeError(f"{source}: no trips found for hour {HOUR}")
        result["modes"][source] = {
            "median": round(statistics.median(samples)),
            "trips": len(samples),
            "months": used,
            "window": f"{used[0]} to {used[-1]}" if used else None,
        }
        result["months"] = sorted(set(result["months"]) | set(used))

    for source, values in result["modes"].items():
        change = values["median"] / TODD_MINUTES - 1
        print(f"{source:<7} median {values['median']} min over {values['trips']:,} trips "
              f"({change:+.0%} against Todd's {TODD_MINUTES})")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Separate windows per source, because the two are not equally common on
    # this one route. Ride-hail does the Midtown-to-JFK ten o'clock run about a
    # hundred and thirty times a month; yellow cabs manage thirty. Yellow needs a
    # longer window to reach a median worth quoting, and can afford one - its
    # monthly file is a seventh the size.
    parser.add_argument("--fhvhv", nargs=2, default=["2026-01", "2026-05"])
    parser.add_argument("--yellow", nargs=2, default=["2025-01", "2026-05"])
    parser.add_argument("--pause", type=float, default=4.0)
    args = parser.parse_args(argv)

    payload = build({"fhvhv": tuple(args.fhvhv), "yellow": tuple(args.yellow)}, args.pause)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "todd.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
