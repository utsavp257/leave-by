"""Taxi zones, so an origin can be named rather than numbered.

The trip records identify places by a zone id, of which there are roughly 260.
The lookup table that turns those into neighbourhood names is published beside
the trip data and is small enough to cache once and forget.

Zone names are the vocabulary the finished page speaks in - nobody knows where
zone 142 is, everybody knows Lincoln Square - so this is also where the
neighbourhood picker gets its labels.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "taxi_zone_lookup.csv"
URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

AIRPORT_ZONES = {132: "JFK", 138: "LGA", 1: "EWR"}


def download(force: bool = False) -> Path:
    if CACHE.exists() and not force:
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(URL, timeout=60)
    response.raise_for_status()
    CACHE.write_bytes(response.content)
    return CACHE


def load() -> dict[int, dict[str, str]]:
    """Zone id to name and borough."""
    path = download()
    zones: dict[int, dict[str, str]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                location_id = int(row["LocationID"])
            except (KeyError, TypeError, ValueError):
                continue
            zone = (row.get("Zone") or "").strip()
            borough = (row.get("Borough") or "").strip()
            # A handful of ids are placeholders for unknown or outside-the-city
            # pickups. They are kept, because dropping them silently would make
            # the trip counts fail to add up, but they are marked.
            zones[location_id] = {
                "name": zone or f"Unknown zone {location_id}",
                "borough": borough or "Unknown",
            }
    if not zones:
        raise RuntimeError(f"{path}: no zones parsed - has the format changed?")
    return zones


def is_reportable(location_id: int, zones: dict[int, dict[str, str]]) -> bool:
    """Whether an origin is a real neighbourhood worth showing a reader.

    Excludes the airports themselves, which would otherwise appear as origins on
    airport-to-airport transfers, and the catch-all zones that carry no
    geography.
    """
    if location_id in AIRPORT_ZONES:
        return False
    zone = zones.get(location_id)
    if zone is None:
        return False
    if zone["borough"] in {"Unknown", "N/A"}:
        return False
    return not zone["name"].startswith("Unknown zone")


if __name__ == "__main__":
    loaded = load()
    print(f"{len(loaded)} zones cached at {CACHE}")
    print(json.dumps({k: loaded[k] for k in list(loaded)[:5]}, indent=2))
