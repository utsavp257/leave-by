"""Getting to JFK by train, assembled from stringline's published aggregates.

Two rail routes reach JFK, and both connect through the AirTrain:

    A       to Howard Beach-JFK Airport
    E, J, Z to Sutphin Blvd-Archer Av-JFK Airport

A door-to-door journey is five things, not one: waiting for the subway, riding
it, walking to the AirTrain, waiting for the AirTrain, and riding that. Only the
middle one is measured. The rest are modelled, and this module keeps the two
kinds of number apart so the page can too.

On combining them. Percentiles do not add - the sum of two 90th percentiles sits
above the 90th percentile of the sum, because two legs rarely have their bad day
at the same moment. Everything that can be convolved properly is: the waits and
the AirTrain legs are modelled as distributions and combined exactly.

That leaves one junction where percentiles are added rather than convolved: the
measured ride against the modelled overhead. It is done that way because
stringline currently publishes only p50 and p90 for a pair, not the underlying
histogram, and a histogram cannot be invented from two percentiles.

The direction of that error is worth stating plainly, because it decides whether
the shortcut is acceptable. Adding overstates the tail, so the door-to-door
figures here are **conservative** - the real journey's 90th percentile is
somewhat below what this reports. For a number whose whole purpose is deciding
when to leave for a flight, erring long is the safe direction. It should still be
tightened once stringline persists its histograms.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data_prep.blocks import BLOCK_NAMES
from data_prep.histogram import MAX_MINUTES, convolve, from_samples, percentile

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"
STRINGLINE = ROOT.parent / "stringline" / "site" / "data"

MIN_SAMPLES = 30

# Where each route meets the AirTrain.
CONNECTORS = {
    "A": "Howard Beach-JFK Airport",
    "E": "Sutphin Blvd-Archer Av-JFK Airport",
    "J": "Sutphin Blvd-Archer Av-JFK Airport",
    "Z": "Sutphin Blvd-Archer Av-JFK Airport",
}

# --------------------------------------------------------------------------
# Assumptions. Every number below is modelled, not measured, and each is a
# range rather than a point so it can be convolved rather than added.
#
# Sources disagree on the AirTrain fare - $8.75 and $9.25 both appear for 2026 -
# so the fare is carried through as a range and must be confirmed against the
# Port Authority before anything is published.
# --------------------------------------------------------------------------

AIRTRAIN_RIDE = {
    "Howard Beach-JFK Airport": (10, 15),
    "Sutphin Blvd-Archer Av-JFK Airport": (8, 12),
}
"""Minutes from the connector to the terminals. Published guidance, not
observation: Jamaica is quoted at 8-12 minutes and Howard Beach at 10-15."""

AIRTRAIN_WAIT = (0, 10)
"""AirTrain runs every 4 to 10 minutes, so a passenger arriving at random waits
somewhere in this range."""

TRANSFER = (3, 8)
"""Walking from the subway platform to the AirTrain platform, with luggage."""

AIRTRAIN_FARE_USD = (8.75, 9.25)
SUBWAY_FARE_USD = 2.90


def uniform(low: int, high: int) -> list[int]:
    """A leg known only as a range, treated as equally likely across it."""
    return from_samples(range(low, high + 1), max_minutes=MAX_MINUTES)


def wait_from_median(median_minutes: float) -> list[int]:
    """Turn a median wait into a distribution.

    A passenger who turns up without consulting a timetable waits somewhere
    between nothing and a full headway, roughly evenly. That makes the median
    wait half the headway, so a median of w implies a headway near 2w and a wait
    spread over 0 to 2w. Coarse, but honest about the shape, and far better than
    treating a median as though every wait were identical.
    """
    headway = max(1, int(round(median_minutes * 2)))
    return uniform(0, headway)


def load_route(route: str, directory: Path) -> dict:
    path = directory / "routes" / f"{route}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Point --stringline at a stringline checkout."
        )
    return json.loads(path.read_text())


def journeys_for_route(route: str, data: dict) -> dict[str, dict]:
    """Every station on this route from which the connector lies ahead."""
    connector = CONNECTORS[route]
    found: dict[str, dict] = {}

    for direction in data["directions"].values():
        stations = direction["stations"]
        names = [s["name"] for s in stations]
        if connector not in names:
            continue
        target = names.index(connector)

        overhead_tail = convolve(
            convolve(uniform(*TRANSFER), uniform(*AIRTRAIN_WAIT)),
            uniform(*AIRTRAIN_RIDE[connector]),
        )

        for i, station in enumerate(stations[:target]):
            pair = direction["pairs"].get(f"{i}-{target}")
            if pair is None:
                continue
            waits = direction["waits"].get(str(i), {})

            blocks = {}
            for block in BLOCK_NAMES:
                ride = pair.get(block)
                if not ride or ride.get("n", 0) < MIN_SAMPLES:
                    continue
                median_wait = waits.get(block)
                if median_wait is None:
                    continue

                overhead = convolve(wait_from_median(median_wait), overhead_tail)
                blocks[block] = {
                    "n": ride["n"],
                    "ride_p50": ride["p50"],
                    "ride_p90": ride["p90"],
                    "overhead_p50": percentile(overhead, 0.5),
                    "overhead_p90": percentile(overhead, 0.9),
                    # Additive at this one junction, and therefore an
                    # over-estimate. See the module docstring.
                    "door_p50": ride["p50"] + percentile(overhead, 0.5),
                    "door_p90": ride["p90"] + percentile(overhead, 0.9),
                }

            if not blocks:
                continue

            name = station["name"]
            candidate = {
                "route": route,
                "connector": connector,
                "km": round(stations[target]["km"] - station["km"], 2),
                "blocks": blocks,
            }
            # A station served in both directions, or by several routes, keeps
            # whichever option is quickest across the day.
            existing = found.get(name)
            if existing is None or _typical(candidate) < _typical(existing):
                found[name] = candidate

    return found


def _typical(journey: dict) -> float:
    values = [b["door_p50"] for b in journey["blocks"].values()]
    return sum(values) / len(values)


def build(directory: Path) -> dict:
    journeys: dict[str, dict] = {}
    for route in CONNECTORS:
        for name, journey in journeys_for_route(route, load_route(route, directory)).items():
            existing = journeys.get(name)
            if existing is None or _typical(journey) < _typical(existing):
                journeys[name] = journey

    system = json.loads((directory / "system.json").read_text())

    print(f"stations      {len(journeys)} with a measured ride to an AirTrain connector")
    by_route: dict[str, int] = {}
    for journey in journeys.values():
        by_route[journey["route"]] = by_route.get(journey["route"], 0) + 1
    for route, count in sorted(by_route.items()):
        print(f"  via {route:<3}       {count}")

    return {
        "airport": "JFK",
        "source": "stringline",
        "corpus": {
            "days": system.get("days_used"),
            "first": system.get("first"),
            "last": system.get("last"),
        },
        "min_samples": MIN_SAMPLES,
        "blocks": BLOCK_NAMES,
        "combination": (
            "Waits and AirTrain legs are convolved. The measured ride is added to "
            "the modelled overhead, which overstates the tail, so door-to-door "
            "figures are conservative."
        ),
        "assumptions": {
            "airtrain_ride_minutes": AIRTRAIN_RIDE,
            "airtrain_wait_minutes": AIRTRAIN_WAIT,
            "transfer_minutes": TRANSFER,
            "airtrain_fare_usd": AIRTRAIN_FARE_USD,
            "subway_fare_usd": SUBWAY_FARE_USD,
            "note": (
                "Modelled, not observed. Sources disagree on the AirTrain fare; "
                "confirm against the Port Authority before publishing."
            ),
        },
        "stations": journeys,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stringline", type=Path, default=STRINGLINE)
    args = parser.parse_args(argv)

    payload = build(args.stringline)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "rail.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote         {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
