# leave-by

How long it really takes to reach a New York airport, and which way you should
go — measured from where the traffic actually was, not from what the map says.

One page, three questions:

- **Has it got worse?** The Midtown-to-JFK run that took 38 minutes in Todd
  Schneider's 2009–2015 taxi data now takes about 60. Same 17.2 miles.
- **Should you take the train?** For JFK, subway and AirTrain against a car,
  from your own neighbourhood, at the hour you are leaving.
- **What does a bad day cost you?** The number the page is built around is not
  the typical journey but the ninetieth percentile — the one you plan a flight
  around.

## The idea

A trip to the airport is the one journey where the average is useless. Being
later than usual for most things is an inconvenience; missing a flight is the
whole day. So every figure here is a distribution, and the headline is its tail.

That has a consequence worth stating: the mode that is quicker on a normal
afternoon is not always the mode that gets you there. From Midtown at rush hour
the train beats a car by roughly half an hour at the ninetieth percentile, and
costs about a tenth as much. From most of the outer boroughs, the car wins even
at its worst.

## The data

| what | where from | what it supports |
|---|---|---|
| Car times | TLC trip records — Uber, Lyft and yellow cab | trip-level percentiles |
| Subway rides | observed movements, via [stringline](https://github.com/utsavp257/stringline) | trip-level percentiles |
| LGA bus leg | MTA bus route segment speeds | typical times only |
| Newark transit | — | nothing usable |

The three sources are not equally good and the page says so wherever it shows
them. The LaGuardia bus figures are averaged by the MTA over a month, a weekday
and an hour before publication, which hides the worst buses — the error runs in
the direction that flatters the bus, so those bars are marked as weaker
evidence. New Jersey Transit publishes punctuality percentages rather than
journey times, and a percentage cannot be turned into a distribution, so Newark
is car-only rather than guessed at.

### Two traps worth knowing

`trip_time` in the ride-hail files is **seconds**. Read as minutes it divides
every answer by sixty, so it is checked against the gap between the pickup and
dropoff timestamps before any month is accepted.

`average_travel_time` in the bus segment data is **minutes**, despite single
digit values on short hops that look like seconds. Read as seconds it implies a
900 mph bus. It is checked against `road_distance / average_road_speed`.

### Percentiles do not add

A door-to-door journey is a wait, plus a ride, plus a walk, plus another wait.
The 90th percentile of the total is **not** the sum of the legs' 90th
percentiles — two legs rarely have their bad day at the same moment, so adding
them overstates the tail. Everything that can be convolved here is. One junction
is still added, because stringline publishes percentiles rather than the
histograms behind them, and that makes the transit figures slightly pessimistic.
Where the train wins, it wins by at least as much as shown.

## Building it

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Airport arrivals, one month at a time. Nothing is downloaded: DuckDB reads
# the parquet over HTTP and pulls only the columns and rows it needs.
.venv/bin/python -m data_prep.tlc 2026-01 2026-04

.venv/bin/python -m data_prep.car_times
.venv/bin/python -m data_prep.bus_times
.venv/bin/python -m data_prep.transit_times   # needs a stringline checkout alongside
.venv/bin/python -m data_prep.leave_by

.venv/bin/python -m pytest tests/ -q
```

A monthly GitHub Action does the same thing, and a manual trigger takes a month
range for backfilling. It runs there rather than locally because the work is
bandwidth rather than processor, and a runner has more of it.

The page is static. Serve `site/` with anything.

## Prior work

[Todd Schneider](https://toddwschneider.com/posts/analyzing-1-1-billion-nyc-taxi-and-uber-trips-with-a-vengeance/)
asked when you should leave for the airport in 2015, using taxi data through
June of that year, and answered it well. This is the half he did not do — the
comparison against the train — over a city that has changed underneath his
numbers. His figures are the reference point throughout.
