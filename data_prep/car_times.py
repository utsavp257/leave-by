"""Car travel times to the airports, ready for the page.

Reads whatever months have been cached by `data_prep.tlc`, merges their
histograms, and writes percentiles per airport, origin neighbourhood and part of
the day.

Uber and Lyft are combined. They were checked separately first and they are the
same to within a couple of minutes at both the median and the tail, which is what
two fleets sharing the same roads ought to look like. Splitting them in the
output would imply a distinction the data does not support - they differ on
price, not on risk. The split survives in the cache for anyone who wants to
re-check that.

The floor of thirty observations per cell is stringline's, kept deliberately so
that both halves of the eventual comparison are filtered the same way.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import duckdb

from data_prep import zones as zones_module
from data_prep.blocks import BLOCK_NAMES
from data_prep.histogram import MAX_MINUTES, mean, percentile, total
from data_prep.tlc import AIRPORTS, CACHE, MAX_FARE, SOURCES

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

MIN_SAMPLES = 30
"""Below this a cell is not reported. Matches stringline."""

QUANTILES = (0.5, 0.9, 0.95)


def cached_months(source: str) -> list[Path]:
    return sorted(p for p in CACHE.glob(f"{source}_*.parquet") if not p.stem.endswith("_fare"))


def cached_fares(source: str) -> list[Path]:
    return sorted(CACHE.glob(f"{source}_*_fare.parquet"))


def load_histograms(paths: list[Path]):
    """Merge the cached months into histograms per airport, origin and block."""
    if not paths:
        raise RuntimeError(
            "no cached months found - run `python -m data_prep.tlc <YYYY-MM>` first"
        )

    con = duckdb.connect()
    files = ", ".join(f"'{p}'" for p in paths)
    rows = con.execute(
        f"""
        SELECT airport, origin, block, minutes, sum(n) AS n
        FROM read_parquet([{files}])
        GROUP BY ALL
        """
    ).fetchall()

    size = MAX_MINUTES + 1
    per_block: dict[tuple[int, int, str], list[int]] = defaultdict(lambda: [0] * size)
    per_day: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0] * size)

    for airport, origin, block, minutes, n in rows:
        n = int(n)
        per_block[(airport, origin, block)][minutes] += n
        per_day[(airport, origin)][minutes] += n

    return per_block, per_day


def load_fares(paths: list[Path]):
    """Fare histograms in whole dollars, keyed the same way as the times."""
    if not paths:
        return {}, {}
    con = duckdb.connect()
    files = ", ".join(f"'{p}'" for p in paths)
    rows = con.execute(
        f"""
        SELECT airport, origin, block, dollars, sum(n) AS n
        FROM read_parquet([{files}])
        GROUP BY ALL
        """
    ).fetchall()

    size = MAX_FARE + 1
    per_block: dict[tuple, list[int]] = defaultdict(lambda: [0] * size)
    per_day: dict[tuple, list[int]] = defaultdict(lambda: [0] * size)
    for airport, origin, block, dollars, n in rows:
        n = int(n)
        per_block[(airport, origin, block)][dollars] += n
        per_day[(airport, origin)][dollars] += n
    return per_block, per_day


def summarise(counts: list[int], fare_counts: list[int] | None = None) -> dict:
    summary = {"n": total(counts), "mean": round(mean(counts), 1)}
    for q in QUANTILES:
        summary[f"p{int(q * 100)}"] = percentile(counts, q)
    if fare_counts and total(fare_counts):
        # The median, not the average. These files carry every service tier, so
        # an average is pulled up by Black, SUV and surge and prices a journey
        # no ordinary reader is taking. Tips are excluded upstream.
        summary["fare"] = percentile(fare_counts, 0.5)
        summary["fare_p90"] = percentile(fare_counts, 0.9)
    return summary


def build(source: str) -> dict:
    paths = cached_months(source)
    per_block, per_day = load_histograms(paths)
    fare_block, fare_day = load_fares(cached_fares(source))
    zone_names = zones_module.load()

    origins = sorted(
        {origin for _, origin in per_day if zones_module.is_reportable(origin, zone_names)}
    )

    cells: dict[str, dict[str, dict[str, dict]]] = {}
    reported = 0
    thin = 0

    for airport in AIRPORTS:
        per_airport: dict[str, dict[str, dict]] = {}
        for origin in origins:
            whole_day = per_day.get((airport, origin))
            if whole_day is None or total(whole_day) < MIN_SAMPLES:
                continue

            entry = {"day": summarise(whole_day, fare_day.get((airport, origin)))}
            for block in BLOCK_NAMES:
                counts = per_block.get((airport, origin, block))
                if counts is None or total(counts) < MIN_SAMPLES:
                    thin += 1
                    continue
                entry[block] = summarise(counts, fare_block.get((airport, origin, block)))

            per_airport[str(origin)] = entry
            reported += 1
        cells[str(airport)] = per_airport

    trips = sum(total(counts) for counts in per_day.values())

    print(f"months        {len(paths)}  ({paths[0].stem[-7:]} to {paths[-1].stem[-7:]})")
    print(f"weekday trips {trips:,}")
    print(f"cells         {reported:,} airport-origin pairs reported")
    print(f"thin blocks   {thin:,} skipped for fewer than {MIN_SAMPLES} trips")

    return {
        "source": source,
        "months": [p.stem.split("_")[-1] for p in paths],
        "weekday_trips": trips,
        "min_samples": MIN_SAMPLES,
        "max_minutes": MAX_MINUTES,
        "quantiles": [f"p{int(q * 100)}" for q in QUANTILES],
        "blocks": BLOCK_NAMES,
        "airports": {str(k): v for k, v in AIRPORTS.items()},
        "zones": {
            str(origin): zone_names[origin]
            for origin in origins
            if any(str(origin) in cells[str(a)] for a in AIRPORTS)
        },
        "cells": cells,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=sorted(SOURCES), default="fhvhv")
    args = parser.parse_args(argv)

    payload = build(args.source)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "car.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote         {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
