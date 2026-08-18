"""Taxi zones as drawable shapes.

The page needs a map of New York small enough to ship inside a static site, so
the published polygons go through three reductions before they are written out.

Simplified. Douglas-Peucker at a tolerance of roughly twenty metres, which is
finer than any line the map draws at screen size and cuts the vertex count by an
order of magnitude.

Trimmed. A zone can be a multipolygon of a dozen parts, most of them slivers of
marsh or a pier a few metres across. Parts below a thousandth of their zone's
area are dropped; they are invisible at any zoom this page offers.

Projected. Longitude is scaled by the cosine of New York's latitude so the city
is not stretched sideways, then everything is fitted to a thousand-unit box.
That is an equirectangular projection, which is wrong for a continent and
perfectly adequate for forty kilometres of coastline.

Newark Airport is left out. It is a zone in the lookup table, but it sits ten
miles west in New Jersey, and including it stretches the frame so far that the
city shrinks into a corner. It is a destination on this page and never an
origin, so nothing is lost by dropping it from a map of where people start.

Output is one JSON file of SVG path strings keyed by zone id, plus a viewBox
fitted to what is actually drawn.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from data_prep import geo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data"

TOLERANCE = 0.0002
"""Degrees. About twenty metres at this latitude."""

MIN_PART_FRACTION = 0.001
"""Drop a polygon part smaller than this share of its zone's largest part."""

VIEWBOX = 1000
PRECISION = 1

ZOOM = 1.0
"""The published frame is the true bounding box. Zooming is the reader's
choice, made in the page, not baked into the data."""

OFF_MAP = {1}
"""Newark Airport: real, but far outside the frame this map wants."""


def perpendicular_distance(point, start, end) -> float:
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / math.hypot(dx, dy)


def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker, iteratively so a long coastline cannot blow the stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst, index = 0.0, None
        for i in range(first + 1, last):
            d = perpendicular_distance(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))

    return [p for p, k in zip(points, keep) if k]


def ring_area(ring: list) -> float:
    """Shoelace. Sign is ignored; only relative size matters here."""
    total = 0.0
    for i in range(len(ring)):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % len(ring)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def polygons_of(geometry: dict) -> list:
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [coordinates]
    if kind == "MultiPolygon":
        return coordinates
    return []


def build() -> dict:
    zones = [z for z in geo.load_zones() if z["location_id"] not in OFF_MAP]

    # One projection for the whole city, so every zone shares a coordinate space.
    lats = [(b[1] + b[3]) / 2 for b in (z["bounds"] for z in zones)]
    scale_x = math.cos(math.radians(sum(lats) / len(lats)))

    min_x = min(z["bounds"][0] for z in zones) * scale_x
    max_x = max(z["bounds"][2] for z in zones) * scale_x
    min_y = min(z["bounds"][1] for z in zones)
    max_y = max(z["bounds"][3] for z in zones)
    span = max(max_x - min_x, max_y - min_y)

    def project(lon, lat):
        x = (lon * scale_x - min_x) / span * VIEWBOX
        # SVG y grows downward, so north has to be flipped.
        y = (max_y - lat) / span * VIEWBOX
        return round(x, PRECISION), round(y, PRECISION)

    shapes: dict[str, dict] = {}
    kept_points = dropped_points = dropped_parts = 0

    for zone in zones:
        parts = polygons_of(zone["geometry"])
        if not parts:
            continue

        areas = [ring_area(p[0]) for p in parts]
        largest = max(areas) if areas else 0
        commands: list[str] = []
        weighted_x = weighted_y = weight = 0.0

        for part, area in zip(parts, areas):
            if largest and area < largest * MIN_PART_FRACTION:
                dropped_parts += 1
                continue
            # Exterior ring only. Holes in a taxi zone are a rounding artefact
            # at this scale and cost more to draw than they convey.
            ring = part[0]
            dropped_points += len(ring)
            reduced = simplify([(p[0], p[1]) for p in ring], TOLERANCE)
            if len(reduced) < 3:
                continue
            kept_points += len(reduced)

            projected = [project(lon, lat) for lon, lat in reduced]
            commands.append(
                "M" + "L".join(f"{x} {y}" for x, y in projected) + "Z"
            )
            for x, y in projected:
                weighted_x += x * area
                weighted_y += y * area
            weight += area * len(projected)

        if not commands:
            continue

        shapes[str(zone["location_id"])] = {
            "d": "".join(commands),
            "name": zone["zone"],
            "borough": zone["borough"],
            "c": [round(weighted_x / weight, 1), round(weighted_y / weight, 1)] if weight else None,
        }

    # Fit the viewBox to the ink rather than the projection square, so the city
    # fills the card instead of floating in the middle of it.
    xs, ys = [], []
    for shape in shapes.values():
        for chunk in shape["d"].replace("Z", "").split("M"):
            for pair in chunk.split("L"):
                pair = pair.strip()
                if not pair:
                    continue
                x, y = pair.split(" ")
                xs.append(float(x)); ys.append(float(y))
    # A modest crop. The city runs diagonally from Staten Island in the
    # south-west to the Bronx in the north-east, so its bounding box has two
    # corners of open water in it and the map reads smaller than the card it
    # sits in. Insetting the frame eats that water first. Anything the crop
    # would actually cut is listed below, so the trade is visible rather than
    # discovered later.
    left, top = min(xs), min(ys)
    width, height = max(xs) - left, max(ys) - top
    inset = (1 - 1 / ZOOM) / 2
    box = [
        round(left + width * inset, 1),
        round(top + height * inset, 1),
        round(width / ZOOM, 1),
        round(height / ZOOM, 1),
    ]

    clipped = []
    for zid, shape in shapes.items():
        pts = [
            tuple(float(v) for v in pair.split(" "))
            for chunk in shape["d"].replace("Z", "").split("M")
            for pair in chunk.split("L")
            if pair.strip()
        ]
        outside = sum(
            1 for x, y in pts
            if x < box[0] or y < box[1] or x > box[0] + box[2] or y > box[1] + box[3]
        )
        if outside:
            clipped.append((shape["name"], outside / len(pts)))

    print(f"zones      {len(shapes)}")
    print(f"viewbox    {box}  (zoom {ZOOM})")
    if clipped:
        worst = sorted(clipped, key=lambda c: -c[1])[:6]
        print(f"clipped    {len(clipped)} zones touch the frame edge:")
        for name, share in worst:
            print(f"             {name[:38]:<40} {share:.0%} of its outline")
    print(f"vertices   {dropped_points:,} -> {kept_points:,}")
    print(f"parts      {dropped_parts:,} slivers dropped")

    return {"viewbox": box, "zones": shapes}


def main() -> int:
    payload = build()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "map.json"
    path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote      {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
