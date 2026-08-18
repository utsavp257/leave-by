"""Is the car fare being counted twice?

Run this when the CDN is willing (it throttles after repeated reads):

    .venv/bin/python -m data_prep.check_fare

Background. The fare on the page is built as

    base_passenger_fare + tolls + bcf + sales_tax
        + congestion_surcharge + airport_fee + cbd_congestion_fee

on the strength of TLC's data dictionary, which describes `base_passenger_fare`
as the fare "before tolls, tips, taxes, and fees". If that description is right,
the sum is what a rider pays and the page is correct.

There is reason to doubt it. A real UberX quote from Herald Square to JFK at
7pm came to $80. In the same zones, in the same part of the day, the built
figures put barely one trip in a hundred at or below $80, with a tenth
percentile above $100. A scheduled fare being cheaper than a live one does not
stretch that far. And the built median of about $152 is close to twice $76,
which is what a double count would look like.

What this prints. Medians of each component and of the two candidate totals,
for the zones around Herald Square in the evening block. Read it like this:

  * `base` alone lands near $80
        -> the dictionary is wrong, the components are already inside the base
           fare, and `Source.fare` in tlc.py should be `base_passenger_fare`
           on its own (plus tolls, which are genuinely separate).

  * `base` lands near $70 and `total` near $80
        -> the sum is right, and the earlier $152 came from somewhere else -
           check the block filter and the zone before changing anything.

  * neither lands near $80
        -> the quote and the data are measuring different things. Check the
           service tier, and whether a scheduled ride is priced differently
           from a hailed one, before touching the pipeline.

Whatever it says, fix `Source.fare` in tlc.py, refetch, and rebuild. Do not
adjust the output to match a single quote.
"""

from __future__ import annotations

import sys

import duckdb

from data_prep.tlc import BASE

# Herald Square and its neighbours, from taxi_zone_lookup.csv.
ZONES = {100: "Garment District", 164: "Midtown South", 186: "Penn Station/Mad Sq W"}
JFK = 132
MONTH = "2026-04"


def main(argv=None) -> int:
    month = (argv or sys.argv[1:] or [MONTH])[0]
    url = f"{BASE}/fhvhv_tripdata_{month}.parquet"

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")

    ids = ", ".join(str(z) for z in ZONES)
    try:
        rows = con.execute(
            f"""
            SELECT PULocationID AS zone,
                   count(*) AS trips,
                   median(base_passenger_fare) AS base,
                   median(tolls) AS tolls,
                   median(bcf + sales_tax + congestion_surcharge) AS taxes,
                   median(airport_fee) AS airport,
                   median(cbd_congestion_fee) AS cbd,
                   median(base_passenger_fare + tolls) AS base_plus_tolls,
                   median(base_passenger_fare + tolls + bcf + sales_tax
                          + congestion_surcharge + airport_fee
                          + cbd_congestion_fee) AS total
            FROM read_parquet('{url}')
            WHERE DOLocationID = {JFK}
              AND PULocationID IN ({ids})
              AND hour(pickup_datetime) BETWEEN 16 AND 18
              AND dayofweek(pickup_datetime) BETWEEN 1 AND 5
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    except duckdb.HTTPException as exc:
        print(f"Could not read {url}: {exc}")
        print("A 403 here is throttling, not a broken link. Wait and retry.")
        return 1

    print(f"To JFK, 4-7pm weekdays, {month}. Medians in dollars.\n")
    header = f"{'zone':<24}{'trips':>6}{'base':>7}{'tolls':>7}{'taxes':>7}{'airport':>8}{'cbd':>6}{'base+toll':>11}{'total':>7}"
    print(header)
    for zone, trips, base, tolls, taxes, airport, cbd, bpt, total in rows:
        print(
            f"{ZONES.get(zone, zone)[:23]:<24}{trips:>6}{base:>7.0f}{tolls:>7.0f}"
            f"{taxes:>7.0f}{airport:>8.2f}{cbd:>6.2f}{bpt:>11.0f}{total:>7.0f}"
        )

    print("\nA real UberX quote for this trip and hour was $80.")
    print("Whichever column lands nearest that is the one the page should use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
