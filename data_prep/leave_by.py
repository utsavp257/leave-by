"""The comparison: from your neighbourhood, which way, and when to leave.

Car times are indexed by taxi zone, transit times by subway station. This joins
them - stations are located in zones by point-in-polygon - and for each zone and
part of the day reports both modes side by side.

The headline number is a leave-by time rather than a travel time. Nobody plans a
flight around a typical journey; they plan around the journey they can rely on.
So the figure carried forward is the 90th percentile: leave this many minutes
before you must arrive, and you make it on nine days out of ten.

Two honesty rules are enforced here rather than left to the page.

First, the modes are not equally well measured, and the record says which is
which. Car figures are trip-level percentiles over millions of trips. JFK
transit is a measured subway ride plus modelled link legs, combined
conservatively. LGA transit inherits a bus leg averaged over month, weekday and
hour, which is much weaker again. Each comparison carries the weaker of its two
sides in `evidence`.

Second, no winner is declared on a difference smaller than five minutes. The
inputs do not support that precision, and a page that says "the train wins by
two minutes" is claiming something it cannot know.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data_prep import geo, zones as zones_module
from data_prep.blocks import BLOCK_NAMES
from data_prep.transit_times import TRANSIT_FARE_USD

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

AIRPORT_ZONES = {"JFK": "132", "LGA": "138", "EWR": "1"}

MEANINGFUL_MINUTES = 5
"""Below this the two modes are called a draw. The inputs are not precise
enough to separate them and pretending otherwise would be false confidence."""

EVIDENCE = {
    "car": "trip-level percentiles from millions of recorded trips",
    "JFK": "measured subway ride plus modelled link legs, combined conservatively",
    "LGA": "as JFK, but the bus leg is averaged over month, weekday and hour "
           "and so understates how unpredictable it is",
}


def verdict(car_p90: int | None, transit_p90: int | None) -> str:
    if car_p90 is None and transit_p90 is None:
        return "unknown"
    if transit_p90 is None:
        return "car only"
    if car_p90 is None:
        return "transit only"
    difference = car_p90 - transit_p90
    if abs(difference) < MEANINGFUL_MINUTES:
        return "too close to call"
    return "transit" if difference > 0 else "car"


def build(car_path: Path, transit_path: Path) -> dict:
    car = json.loads(car_path.read_text())
    transit = json.loads(transit_path.read_text())
    grouped = geo.stations_by_zone()
    zone_names = zones_module.load()

    results: dict[str, dict] = {}
    matched_stations = 0
    zones_with_transit = 0

    for airport, zone_id in AIRPORT_ZONES.items():
        available = transit["airports"].get(airport, {})
        car_cells = car["cells"].get(zone_id, {})
        per_zone: dict[str, dict] = {}

        for origin, cells in car_cells.items():
            stations = grouped.get(int(origin), [])
            options = {
                station["name"]: available[station["name"]]
                for station in stations
                if station["name"] in available
            }
            best = None
            if options:
                best_name = min(
                    options,
                    key=lambda n: sum(
                        b["door_p50"] for b in options[n]["blocks"].values()
                    ) / max(1, len(options[n]["blocks"])),
                )
                best = {"station": best_name, **options[best_name]}
                matched_stations += 1

            blocks = {}
            for block in BLOCK_NAMES:
                car_cell = cells.get(block)
                transit_cell = best["blocks"].get(block) if best else None
                if car_cell is None and transit_cell is None:
                    continue
                car_p90 = car_cell["p90"] if car_cell else None
                transit_p90 = transit_cell["door_p90"] if transit_cell else None
                blocks[block] = {
                    "car": (
                        {
                            "p50": car_cell["p50"],
                            "p90": car_p90,
                            "n": car_cell["n"],
                            "fare": car_cell.get("fare"),
                        }
                        if car_cell
                        else None
                    ),
                    "transit": (
                        {
                            "p50": transit_cell["door_p50"],
                            "p90": transit_p90,
                            "fare": TRANSIT_FARE_USD.get(airport),
                        }
                        if transit_cell
                        else None
                    ),
                    "leave_by": min(
                        v for v in (car_p90, transit_p90) if v is not None
                    ),
                    "verdict": verdict(car_p90, transit_p90),
                }

            if not blocks:
                continue
            if best:
                zones_with_transit += 1

            entry = {
                "zone": zone_names.get(int(origin), {}).get("name", origin),
                "borough": zone_names.get(int(origin), {}).get("borough", ""),
                "blocks": blocks,
                "evidence": {
                    "car": EVIDENCE["car"],
                    "transit": EVIDENCE.get(airport) if best else None,
                },
            }
            if best:
                entry["via"] = {
                    "station": best["station"],
                    "route": best["route"],
                    "link": best["link"],
                    "connector": best["connector"],
                }
            per_zone[origin] = entry

        results[airport] = per_zone
        with_transit = sum(1 for v in per_zone.values() if "via" in v)
        print(f"{airport}  {len(per_zone):>4} origin zones, {with_transit:>4} with a transit option")

    return {
        "built_from": {
            "car": {"months": car["months"], "weekday_trips": car["weekday_trips"]},
            "transit": transit["corpus"],
        },
        "leave_by_quantile": "p90",
        "transit_fare_usd": TRANSIT_FARE_USD,
        "meaningful_minutes": MEANINGFUL_MINUTES,
        "blocks": BLOCK_NAMES,
        "evidence": EVIDENCE,
        "note": (
            "Leave-by times are 90th percentiles: right on nine days in ten. "
            "Transit figures are conservative, so where transit wins it wins by "
            "at least as much as shown. EWR has no assembled transit option."
        ),
        "airports": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--car", type=Path, default=OUT / "car.json")
    parser.add_argument("--transit", type=Path, default=OUT / "transit.json")
    args = parser.parse_args(argv)

    payload = build(args.car, args.transit)
    path = OUT / "leaveby.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote  {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
