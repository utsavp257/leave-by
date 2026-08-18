"""Getting to LaGuardia, which has no train.

LGA is reached by subway plus one bus. Two combinations matter, and in the MTA's
segment data each is a single measured hop from a subway junction to the
terminals:

    Q70+  74 St/Roosevelt Av (7, E, F, M, R) -> LaGuardia Terminal C
    M60+  E 125 St/Lexington Av (4, 5, 6)    -> LaGuardia

The evidence here is weaker than anywhere else in this project, and the module
is written to make that impossible to forget.

What the MTA publishes is `average_travel_time`, and it is averaged twice over.
A row is not a day: it is one month, one day of the week, one hour. The figure
for 5pm on a Tuesday in January 2025 is the mean of every Tuesday-at-5pm bus
that month - around twenty-seven of them, as `bus_trip_count` records.

So the only variation left to observe is between those month-weekday-hour cells,
and it is far narrower than the variation between individual buses. Two rounds of
averaging have removed the bad afternoons that a traveller actually fears.

The error has a direction, which is why this is laboured. Averaging discards the
worst buses, so these figures understate how unpredictable the bus is - they
flatter it. Since the whole argument of the project is that tails should drive
the decision, nothing here is called a percentile, the spread is named for
exactly what it measures, and none of it should be set beside the JFK rail and
car numbers as though it were the same kind of evidence.

The units trap: `average_travel_time` is in minutes, not seconds, despite single
digit values on short segments. It is checked against
`road_distance / average_road_speed` on every fetch.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from data_prep.blocks import BLOCK_NAMES, block_at

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

# Two datasets are needed for a continuous run; the MTA split them at 2025.
DATASETS = ["58t6-89vi", "kufs-yh3x"]
BASE = "https://data.ny.gov/resource/{dataset}.json"

WEEKDAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}

# route_id, direction and stop_order of the single airport-bound segment, plus
# the subway station that feeds it. Select Bus Service routes carry a "+".
LEGS = [
    {
        "route_id": "Q70+",
        "direction": "N",
        "stop_order": 2,
        "junction": "74 St-Broadway",
        "junction_aliases": ["Jackson Hts-Roosevelt Av", "74 St-Broadway"],
        "terminal": "LaGuardia Terminal C",
    },
    {
        "route_id": "M60+",
        "direction": "E",
        "stop_order": 9,
        "junction": "125 St",
        "junction_aliases": ["125 St"],
        "terminal": "LaGuardia",
    },
]

FARE_NOTE = "The Q70+ LaGuardia Link is free, so reaching LGA costs one subway swipe."


def query(dataset: str, leg: dict) -> list[dict]:
    params = {
        "$select": (
            "timestamp,day_of_week,hour_of_day,road_distance,"
            "average_travel_time,average_road_speed,bus_trip_count"
        ),
        "$where": (
            f"route_id='{leg['route_id']}' AND direction='{leg['direction']}' "
            f"AND stop_order={leg['stop_order']} AND average_travel_time IS NOT NULL"
        ),
        "$limit": 50000,
    }
    url = BASE.format(dataset=dataset) + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as handle:
        return json.load(handle)


def verify_units(rows: list[dict], dataset: str, leg: dict) -> None:
    """average_travel_time must equal distance over speed, in minutes."""
    checked = 0
    for row in rows:
        try:
            distance = float(row["road_distance"])
            speed = float(row["average_road_speed"])
            stated = float(row["average_travel_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if speed <= 0:
            continue
        implied = distance / speed * 60
        if abs(implied - stated) > max(0.5, 0.05 * implied):
            raise RuntimeError(
                f"{dataset} {leg['route_id']}: average_travel_time {stated} does "
                f"not match road_distance/average_road_speed ({implied:.2f} min). "
                f"The unit may have changed - check before trusting any output."
            )
        checked += 1
    if checked < 10:
        raise RuntimeError(f"{dataset} {leg['route_id']}: too few rows to verify units")


def collect(leg: dict) -> dict:
    per_block: dict[str, list[float]] = defaultdict(list)
    buses_per_block: dict[str, list[int]] = defaultdict(list)
    buses = 0
    months: set[str] = set()

    for dataset in DATASETS:
        rows = query(dataset, leg)
        if not rows:
            continue
        verify_units(rows, dataset, leg)
        for row in rows:
            if row.get("day_of_week") not in WEEKDAYS:
                continue
            block = block_at(int(row["hour_of_day"]))
            count = int(row.get("bus_trip_count") or 0)
            per_block[block].append(float(row["average_travel_time"]))
            buses_per_block[block].append(count)
            buses += count
            months.add(row["timestamp"][:7])

    blocks = {}
    for block in BLOCK_NAMES:
        values = per_block.get(block)
        if not values or len(values) < 10:
            continue
        ordered = sorted(values)
        counts = buses_per_block[block]
        blocks[block] = {
            # One cell is one month, one weekday, one hour.
            "cells": len(ordered),
            "buses_per_cell": round(sum(counts) / len(counts), 1),
            "typical": round(statistics.median(ordered), 1),
            # Not a percentile of journeys. Each value entering this spread is
            # already an average of roughly `buses_per_cell` buses, so the real
            # spread between buses is wider than anything shown here.
            "spread_of_monthly_weekday_means": {
                "low": round(ordered[int(0.1 * (len(ordered) - 1))], 1),
                "high": round(ordered[int(0.9 * (len(ordered) - 1))], 1),
                "worst_cell": round(ordered[-1], 1),
            },
        }

    return {
        "route": leg["route_id"],
        "junction": leg["junction"],
        "junction_aliases": leg["junction_aliases"],
        "terminal": leg["terminal"],
        "buses_observed": buses,
        "months": len(months),
        "blocks": blocks,
    }


def build() -> dict:
    legs = [collect(leg) for leg in LEGS]
    for leg in legs:
        typical = {b: v["typical"] for b, v in leg["blocks"].items()}
        print(f"{leg['route']:<6} {leg['junction']:<22} {leg['months']:>3} months  {typical}")

    return {
        "airport": "LGA",
        "source": "MTA bus route segment speeds",
        "datasets": DATASETS,
        "evidence": (
            "Each figure is an average over a month, a day of the week and an "
            "hour - roughly twenty-seven buses per cell. The spread shown is "
            "between those cells, not between buses, so it is much narrower "
            "than what a traveller experiences and it flatters the bus. Not "
            "comparable with the trip-level percentiles used for JFK."
        ),
        "fare_note": FARE_NOTE,
        "blocks": BLOCK_NAMES,
        "legs": legs,
    }


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    payload = build()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "bus.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote  {path} ({path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
