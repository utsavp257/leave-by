"""Which taxi zone a subway station stands in.

The two halves of this project are indexed differently. Car times come by taxi
zone, of which there are 265 and which is how the trip records describe a place.
Rail times come by subway station, because that is what stringline measures. To
put them side by side, each station has to be located in a zone.

That is a point-in-polygon test and nothing more, so it is done here in plain
Python rather than by taking on a geospatial stack for one join. The zone
polygons are small, there are a few hundred stations, and the whole thing runs in
under a second.

The station list joins to stringline cleanly: stringline's ids carry a direction
suffix, so `H03S` and `H03N` are the southbound and northbound platforms of GTFS
stop `H03`. Dropping the last character gives the key.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data"

ZONES_URL = "https://data.cityofnewyork.us/resource/8meu-9t5y.json?$limit=500"
STATIONS_URL = "https://data.ny.gov/resource/39hk-dx4f.json?$limit=2000"


def _cached(name: str, url: str) -> list[dict]:
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        response = requests.get(url, timeout=120)
        response.raise_for_status()
        path.write_bytes(response.content)
    return json.loads(path.read_text())


def point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting: count crossings of a horizontal ray to the right.

    A point on the boundary may fall either way. That is fine here - zone
    borders run down the middle of streets and no station sits exactly on one.
    """
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            crossing_x = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if crossing_x > x:
                inside = not inside
    return inside


def point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """A polygon is an exterior ring followed by any number of holes."""
    if not polygon:
        return False
    if not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])


def point_in_geometry(x: float, y: float, geometry: dict) -> bool:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return point_in_polygon(x, y, coordinates)
    if kind == "MultiPolygon":
        return any(point_in_polygon(x, y, polygon) for polygon in coordinates)
    return False


def _bounds(geometry: dict):
    xs, ys = [], []
    stack = [geometry.get("coordinates")]
    while stack:
        item = stack.pop()
        if not isinstance(item, list):
            continue
        if item and isinstance(item[0], (int, float)):
            xs.append(item[0])
            ys.append(item[1])
        else:
            stack.extend(item)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def load_zones() -> list[dict]:
    zones = []
    for row in _cached("taxi_zones.json", ZONES_URL):
        geometry = row.get("the_geom")
        if not geometry:
            continue
        box = _bounds(geometry)
        if box is None:
            continue
        zones.append(
            {
                "location_id": int(row["locationid"]),
                "zone": row.get("zone", ""),
                "borough": row.get("borough", ""),
                "geometry": geometry,
                "bounds": box,
            }
        )
    if not zones:
        raise RuntimeError("no taxi zone polygons parsed")
    return zones


def load_stations() -> list[dict]:
    stations = []
    for row in _cached("subway_stations.json", STATIONS_URL):
        try:
            stations.append(
                {
                    "gtfs_stop_id": row["gtfs_stop_id"],
                    "name": row["stop_name"],
                    "borough": row.get("borough", ""),
                    "routes": (row.get("daytime_routes") or "").split(),
                    "lon": float(row["gtfs_longitude"]),
                    "lat": float(row["gtfs_latitude"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not stations:
        raise RuntimeError("no subway stations parsed")
    return stations


def zone_for(lon: float, lat: float, zones: list[dict]) -> int | None:
    """The zone containing a point, or None if it falls outside every one."""
    for zone in zones:
        min_x, min_y, max_x, max_y = zone["bounds"]
        if not (min_x <= lon <= max_x and min_y <= lat <= max_y):
            continue
        if point_in_geometry(lon, lat, zone["geometry"]):
            return zone["location_id"]
    return None


def stations_by_zone() -> dict[int, list[dict]]:
    """Group subway stations by the taxi zone they stand in."""
    zones = load_zones()
    grouped: dict[int, list[dict]] = {}
    placed = 0
    for station in load_stations():
        location_id = zone_for(station["lon"], station["lat"], zones)
        if location_id is None:
            continue
        grouped.setdefault(location_id, []).append(station)
        placed += 1
    if not placed:
        raise RuntimeError("no station fell inside any zone - check coordinate order")
    return grouped


if __name__ == "__main__":
    grouped = stations_by_zone()
    total = sum(len(v) for v in grouped.values())
    print(f"{total} stations placed across {len(grouped)} taxi zones")
