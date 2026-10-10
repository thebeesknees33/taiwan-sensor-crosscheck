"""Great-circle distance and bearing on a spherical Earth.

A sphere is accurate to about 0.5% of the distance, i.e. under 0.5 km at the
100 km matching limit and tens of metres for the few-km offsets we measure.
That is well below CWA's 0.01 degree (~1.1 km) report precision, so a full
ellipsoidal geodesic is not needed.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def offset_en_km(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    """East and north components (km) of the offset from point 1 to point 2."""
    d = distance_km(lat1, lon1, lat2, lon2)
    b = math.radians(bearing_deg(lat1, lon1, lat2, lon2))
    return d * math.sin(b), d * math.cos(b)
