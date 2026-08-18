"""Getting to the airports without a car, assembled from stringline.

Every journey here is subway, then a link, then the terminal:

    JFK   A                 -> Howard Beach-JFK Airport   -> AirTrain
          E, J, Z           -> Sutphin Blvd-Archer Av     -> AirTrain
    LGA   7                 -> 74 St-Broadway             -> Q70+ bus
          E, F, M, R        -> Jackson Hts-Roosevelt Av   -> Q70+ bus

Only the subway ride is measured. The wait for the subway is inferred from
stringline's median wait; the transfer, the link wait and the link ride are
modelled. The two kinds of number are kept apart all the way to the page.

On combining them. Percentiles do not add - the sum of two 90th percentiles sits
above the 90th percentile of the sum, because two legs rarely have their bad day
together. Everything that can be convolved is: waits, transfers and link rides
are distributions and combine exactly.

One junction is added rather than convolved: the measured ride against the
modelled overhead. stringline publishes p50 and p90 for a pair but not the
histogram behind them, and a histogram cannot be invented from two percentiles.
Adding overstates the tail, so these door-to-door figures are conservative - the
real 90th percentile is somewhat lower. For a number whose job is deciding when
to leave for a flight, erring long is the safe direction. Tighten it when
stringline persists its histograms.

The M60+ to LaGuardia is deliberately not assembled. Its junction is the 4/5/6
at Lexington Avenue, which stringline calls "125 St" - a name shared by four
unrelated stations on four different lines. Picking the right one needs a
station-id join this module does not do, and guessing would be worse than
leaving it out. Its measured bus leg is still published in bus.json.
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

# --------------------------------------------------------------------------
# Assumptions. Modelled, never measured, and each a range so it can be
# convolved rather than added.
#
# Sources disagree on the AirTrain fare - $8.75 and $9.25 both appear for 2026 -
# so it is carried as a range and must be confirmed with the Port Authority
# before publishing. The Q70+ has been fare-free at times; confirm that too.
# --------------------------------------------------------------------------

TRANSFER = (3, 8)
"""Subway platform to link platform, with luggage."""

AIRTRAIN_WAIT = (0, 10)
"""AirTrain runs every 4 to 10 minutes."""

Q70_WAIT = (0, 12)
"""Q70+ headway, assumed. Worth replacing with the MTA's published headway."""

AIRTRAIN_FARE_USD = (8.75, 9.25)
SUBWAY_FARE_USD = 2.90

LINKS = {
    "JFK": [
        {
            "routes": ["A"],
            "connector": "Howard Beach-JFK Airport",
            "link": "AirTrain",
            "link_ride": (10, 15),
            "link_wait": AIRTRAIN_WAIT,
        },
        {
            "routes": ["E", "J", "Z"],
            "connector": "Sutphin Blvd-Archer Av-JFK Airport",
            "link": "AirTrain",
            "link_ride": (8, 12),
            "link_wait": AIRTRAIN_WAIT,
        },
    ],
    "LGA": [
        {
            "routes": ["7"],
            "connector": "74 St-Broadway",
            "link": "Q70+",
            "link_wait": Q70_WAIT,
        },
        {
            "routes": ["E", "F", "M", "R"],
            "connector": "Jackson Hts-Roosevelt Av",
            "link": "Q70+",
            "link_wait": Q70_WAIT,
        },
    ],
}


def uniform(low: int, high: int) -> list[int]:
    return from_samples(range(int(low), int(high) + 1), max_minutes=MAX_MINUTES)


def wait_from_median(median_minutes: float) -> list[int]:
    """A median wait implies a headway of twice that, and a wait spread evenly
    across it. Coarse, but it keeps the shape - treating a median as a constant
    would quietly delete the tail of every journey it appears in."""
    headway = max(1, int(round(median_minutes * 2)))
    return uniform(0, headway)


def bus_ride_ranges(bus_path: Path) -> dict[str, tuple[int, int]]:
    """Q70+ ride time per block, as a range, from the measured bus leg.

    These come from figures already averaged over a month, a weekday and an
    hour, so the range is narrower than what a rider meets. It flatters the bus,
    and the page has to say so.
    """
    if not bus_path.exists():
        raise FileNotFoundError(f"{bus_path} not found - run `python -m data_prep.bus_times`")
    bus = json.loads(bus_path.read_text())
    leg = next(item for item in bus["legs"] if item["route"] == "Q70+")
    ranges = {}
    for block, values in leg["blocks"].items():
        spread = values["spread_of_monthly_weekday_means"]
        ranges[block] = (int(spread["low"]), max(int(spread["high"]), int(spread["low"]) + 1))
    return ranges


def load_route(route: str, directory: Path) -> dict:
    path = directory / "routes" / f"{route}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Point --stringline at a stringline checkout."
        )
    return json.loads(path.read_text())


def journeys_for_link(route: str, data: dict, link: dict, bus_ranges) -> dict[str, dict]:
    connector = link["connector"]
    found: dict[str, dict] = {}

    for direction in data["directions"].values():
        names = [s["name"] for s in direction["stations"]]
        if connector not in names:
            continue
        target = names.index(connector)

        for i, station in enumerate(direction["stations"][:target]):
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

                link_ride = link.get("link_ride") or (bus_ranges or {}).get(block)
                if link_ride is None:
                    continue

                overhead = convolve(
                    convolve(wait_from_median(median_wait), uniform(*TRANSFER)),
                    convolve(uniform(*link["link_wait"]), uniform(*link_ride)),
                )
                blocks[block] = {
                    "n": ride["n"],
                    "ride_p50": ride["p50"],
                    "ride_p90": ride["p90"],
                    "overhead_p50": percentile(overhead, 0.5),
                    "overhead_p90": percentile(overhead, 0.9),
                    "door_p50": ride["p50"] + percentile(overhead, 0.5),
                    "door_p90": ride["p90"] + percentile(overhead, 0.9),
                }

            if blocks:
                found[station["name"]] = {
                    "route": route,
                    "connector": connector,
                    "link": link["link"],
                    "blocks": blocks,
                }

    return found


def _typical(journey: dict) -> float:
    values = [b["door_p50"] for b in journey["blocks"].values()]
    return sum(values) / len(values)


def build(directory: Path, bus_path: Path) -> dict:
    bus_ranges = bus_ride_ranges(bus_path)
    airports: dict[str, dict] = {}

    for airport, links in LINKS.items():
        journeys: dict[str, dict] = {}
        for link in links:
            ranges = None if link.get("link_ride") else bus_ranges
            for route in link["routes"]:
                data = load_route(route, directory)
                for name, journey in journeys_for_link(route, data, link, ranges).items():
                    existing = journeys.get(name)
                    if existing is None or _typical(journey) < _typical(existing):
                        journeys[name] = journey
        airports[airport] = journeys
        print(f"{airport}  {len(journeys):>4} stations with a measured ride to a link")

    system = json.loads((directory / "system.json").read_text())

    return {
        "source": "stringline subway rides plus modelled link legs",
        "corpus": {
            "days": system.get("days_used"),
            "first": system.get("first"),
            "last": system.get("last"),
        },
        "min_samples": MIN_SAMPLES,
        "blocks": BLOCK_NAMES,
        "combination": (
            "Waits, transfers and link rides are convolved. The measured subway "
            "ride is added to the modelled overhead, which overstates the tail, "
            "so door-to-door figures are conservative."
        ),
        "assumptions": {
            "transfer_minutes": TRANSFER,
            "airtrain_wait_minutes": AIRTRAIN_WAIT,
            "q70_wait_minutes": Q70_WAIT,
            "q70_ride_minutes_by_block": bus_ranges,
            "airtrain_fare_usd": AIRTRAIN_FARE_USD,
            "subway_fare_usd": SUBWAY_FARE_USD,
            "note": (
                "Modelled, not observed. The Q70+ ride range comes from figures "
                "already averaged over month, weekday and hour, so it is "
                "narrower than a rider's experience. Confirm both fares before "
                "publishing."
            ),
        },
        "airports": airports,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stringline", type=Path, default=STRINGLINE)
    parser.add_argument("--bus", type=Path, default=OUT / "bus.json")
    args = parser.parse_args(argv)

    payload = build(args.stringline, args.bus)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "transit.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote     {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
