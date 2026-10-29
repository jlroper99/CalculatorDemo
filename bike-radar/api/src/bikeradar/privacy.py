"""Location privacy rules applied before any point leaves the API (PRD constraints, features/003).

Points within `radius_m` of a ride's first or last pass are never emitted, since rides usually
start and end near home or work. Privacy-zone polygons are added in M3.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

EARTH_RADIUS_M = 6_371_008.8

LatLon = tuple[float, float]


def haversine_m(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def endpoint_mask(points: Sequence[LatLon | None], radius_m: float) -> list[bool]:
    """True for each point that must be hidden. `points` are in ride time order.

    The anchors are the first and last points that have coordinates. A point without
    coordinates has nothing to hide and is reported as not masked.
    """
    located = [p for p in points if p is not None]
    if not located:
        return [False] * len(points)
    anchors = (located[0], located[-1])
    return [p is not None and any(haversine_m(p, a) <= radius_m for a in anchors) for p in points]
