"""Turn matched pairs into accuracy measurements.

Every residual is signed "A minus B". With the CLI defaults, A = CWA and
B = USGS, so a positive depth residual means CWA put the quake deeper.

Magnitude residuals are only ever grouped by magnitude-type pair (e.g.
"ml-mww"). Different magnitude scales measure different things, so pooling
them would turn a scale difference into a fake "error".
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional, Sequence

from .geo import bearing_deg, offset_en_km
from .match import MatchResult, Pair
from .model import QuakeRecord

SHALLOW_MAX_KM = 35.0  # shallow/deep split used by Guan et al. (2020) for Taiwan ML
# Magnitude scales for the same quake can differ by ~0.5 (Taiwan ML vs Mw for
# deep events), so an input whose smallest event is within this of the
# completeness cutoff may have been truncated near it.
TRUNCATION_MARGIN = 0.5


@dataclass
class PairMetrics:
    a_key: str
    b_key: str
    a_time: str
    dt_s: float
    dist_km: float
    azimuth_deg: float  # direction from the B epicenter to the A epicenter
    d_east_km: float
    d_north_km: float
    d_depth_km: Optional[float]
    a_depth_km: Optional[float]
    b_depth_km: Optional[float]
    a_mag: Optional[float]
    b_mag: Optional[float]
    mag_pair: str  # "<A type>-<B type>"
    d_mag: Optional[float]
    ambiguous: bool


def pair_metrics(p: Pair) -> PairMetrics:
    e, n = offset_en_km(p.b.lat, p.b.lon, p.a.lat, p.a.lon)
    dd = None
    if p.a.depth_km is not None and p.b.depth_km is not None:
        dd = p.a.depth_km - p.b.depth_km
    dm = None
    if p.a.mag is not None and p.b.mag is not None:
        dm = p.a.mag - p.b.mag
    return PairMetrics(
        a_key=p.a.key,
        b_key=p.b.key,
        a_time=p.a.origin_time.isoformat(),
        dt_s=p.dt_s,
        dist_km=p.dist_km,
        azimuth_deg=bearing_deg(p.b.lat, p.b.lon, p.a.lat, p.a.lon),
        d_east_km=e,
        d_north_km=n,
        d_depth_km=dd,
        a_depth_km=p.a.depth_km,
        b_depth_km=p.b.depth_km,
        a_mag=p.a.mag,
        b_mag=p.b.mag,
        mag_pair=f"{p.a.mag_type or '?'}-{p.b.mag_type or '?'}",
        d_mag=dm,
        ambiguous=p.ambiguous,
    )


def describe(values: Sequence[Optional[float]]) -> dict:
    """n, mean, median, sample std, MAD (median absolute deviation), min, max."""
    v = [x for x in values if x is not None and not math.isnan(x)]
    if not v:
        return {"n": 0}
    med = statistics.median(v)
    return {
        "n": len(v),
        "mean": statistics.fmean(v),
        "median": med,
        "std": statistics.stdev(v) if len(v) > 1 else None,
        "mad": statistics.median([abs(x - med) for x in v]),
        "min": min(v),
        "max": max(v),
    }


@dataclass
class Coverage:
    """Where and when both catalogs are expected to report. Completeness is only judged inside it."""

    start: datetime
    end: datetime
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max

    def contains(self, r: QuakeRecord) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        return (
            self.start <= r.origin_time <= self.end
            and lat_min <= r.lat <= lat_max
            and lon_min <= r.lon <= lon_max
        )


def overlap_coverage(
    a: Sequence[QuakeRecord],
    b: Sequence[QuakeRecord],
    bbox: tuple[float, float, float, float],
) -> Optional[Coverage]:
    """The time span both inputs cover, inside bbox. None if they don't overlap."""
    if not a or not b:
        return None
    start = max(min(r.origin_time for r in a), min(r.origin_time for r in b))
    end = min(max(r.origin_time for r in a), max(r.origin_time for r in b))
    if start > end:
        return None
    return Coverage(start, end, bbox)


def summarize(
    result: MatchResult,
    coverage: Optional[Coverage],
    min_mag: Optional[float] = None,
) -> dict:
    metrics = [pair_metrics(p) for p in result.pairs]
    unambiguous = [m for m in metrics if not m.ambiguous]

    def block(ms: list[PairMetrics]) -> dict:
        out = {
            "pairs": len(ms),
            "dt_s": describe([m.dt_s for m in ms]),
            "dist_km": describe([m.dist_km for m in ms]),
            "d_depth_km": describe([m.d_depth_km for m in ms]),
        }
        if ms:
            me = statistics.fmean(m.d_east_km for m in ms)
            mn = statistics.fmean(m.d_north_km for m in ms)
            out["mean_offset"] = {
                "east_km": me,
                "north_km": mn,
                "length_km": math.hypot(me, mn),
                "azimuth_deg": math.degrees(math.atan2(me, mn)) % 360.0,
            }
        by_type: dict[str, list[float]] = {}
        for m in ms:
            if m.d_mag is not None:
                by_type.setdefault(m.mag_pair, []).append(m.d_mag)
        out["d_mag_by_type"] = {k: describe(v) for k, v in sorted(by_type.items())}
        return out

    def depth_class(m: PairMetrics) -> Optional[str]:
        if m.a_depth_km is None:
            return None
        return "shallow" if m.a_depth_km <= SHALLOW_MAX_KM else "deep"

    summary = {
        "config": asdict(result.config),
        "all_pairs": block(metrics),
        "unambiguous_pairs": block(unambiguous),
        "by_depth_of_a": {
            cls: block([m for m in metrics if depth_class(m) == cls]) for cls in ("shallow", "deep")
        },
        "ambiguous_pairs": len(metrics) - len(unambiguous),
    }
    if coverage is not None:
        summary["coverage"] = {
            "start": coverage.start.isoformat(),
            "end": coverage.end.isoformat(),
            "bbox": list(coverage.bbox),
        }
        summary["completeness"] = _completeness(result, coverage, min_mag)
    return summary


def _completeness(result: MatchResult, cov: Coverage, min_mag: Optional[float]) -> dict:
    def side(matched: list[QuakeRecord], unmatched: list[QuakeRecord]) -> dict:
        def keep(r: QuakeRecord) -> bool:
            if not cov.contains(r):
                return False
            return min_mag is None or (r.mag is not None and r.mag >= min_mag)

        m = [r for r in matched if keep(r)]
        u = [r for r in unmatched if keep(r)]
        total = len(m) + len(u)
        mags = [r.mag for r in matched + unmatched if cov.contains(r) and r.mag is not None]
        return {
            "events": total,
            "matched": len(m),
            "match_rate": (len(m) / total) if total else None,
            "unmatched": [r.key for r in sorted(u, key=lambda r: r.origin_time)],
            "input_min_mag": min(mags) if mags else None,
        }

    a_side = side([p.a for p in result.pairs], result.unmatched_a)
    b_side = side([p.b for p in result.pairs], result.unmatched_b)
    warnings = []
    if min_mag is not None:
        # If one input stops near the cutoff (e.g. it was downloaded with
        # minmagnitude), quakes the other catalog rates just above the cutoff
        # may be missing from it simply because its own scale rated them lower.
        for name, own, other in (("a", a_side, "b"), ("b", b_side, "a")):
            floor = own["input_min_mag"]
            if floor is not None and floor > min_mag - TRUNCATION_MARGIN:
                warnings.append(
                    {"kind": "possible-truncation", "input": name, "other": other,
                     "input_min_mag": floor, "cutoff": min_mag}
                )
    return {
        "min_mag": min_mag,
        "note": "min_mag is applied to each catalog's own magnitude scale",
        "a": a_side,
        "b": b_side,
        "warnings": warnings,
    }
