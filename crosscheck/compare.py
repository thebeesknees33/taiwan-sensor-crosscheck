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

from .coverage import GLOBAL_BBOX, Coverage, Segment, inferred
from .geo import bearing_deg, offset_en_km
from .match import MatchResult, Pair
from .model import QuakeRecord

SHALLOW_MAX_KM = 35.0  # shallow/deep split used by Guan et al. (2020) for Taiwan ML
# Two magnitude scales can rate the same quake differently: Guan et al. (2020)
# report Taiwan ML around 0.2 above Mw for shallow quakes and around 0.5 above
# it for deep quakes with ML > 6. Near a magnitude floor, events within this
# margin may lack a partner because of the scale difference alone.
SCALE_MARGIN = 0.5
LIST_LIMIT = 50  # unmatched keys listed per side in summary.json


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


def time_resolution(records: Sequence[QuakeRecord]) -> Optional[str]:
    """Coarsest unit every origin time is a whole multiple of: '1 s', '1 ms' or 'sub-ms'."""
    if not records:
        return None
    if all(r.origin_time.microsecond == 0 for r in records):
        return "1 s"
    if all(r.origin_time.microsecond % 1000 == 0 for r in records):
        return "1 ms"
    return "sub-ms"


# ---------------------------------------------------------------- coverage


def resolve_coverage(
    a: Sequence[QuakeRecord],
    b: Sequence[QuakeRecord],
    cov_a: Optional[Coverage],
    cov_b: Optional[Coverage],
    fallback_bbox: tuple[float, float, float, float],
    bbox: Optional[tuple[float, float, float, float]] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> tuple[Optional[Coverage], Optional[Coverage], Optional[Coverage]]:
    """Coverage of A, of B, and where both overlap (optionally narrowed by the user).

    A missing coverage is inferred from that input's first and last events
    inside ``fallback_bbox`` and marked as not declared.
    """
    region = bbox or fallback_bbox
    cov_a = cov_a if cov_a is not None else inferred(a, region, "A")
    cov_b = cov_b if cov_b is not None else inferred(b, region, "B")
    if cov_a is None or cov_b is None:
        return cov_a, cov_b, None
    joint = cov_a.intersect(cov_b)
    if joint.segments and (bbox or start or end):
        user = Segment(start or joint.start, end or joint.end, bbox or GLOBAL_BBOX, None, "command line")
        joint = joint.intersect(Coverage([user]))
    return cov_a, cov_b, joint if joint.segments else None


# ---------------------------------------------------------------- summary


def summarize(
    result: MatchResult,
    joint: Optional[Coverage],
    min_mag: Optional[float] = None,
    cov_a: Optional[Coverage] = None,
    cov_b: Optional[Coverage] = None,
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

    a_all = [p.a for p in result.pairs] + result.unmatched_a
    b_all = [p.b for p in result.pairs] + result.unmatched_b
    summary = {
        "config": asdict(result.config),
        "all_pairs": block(metrics),
        "unambiguous_pairs": block(unambiguous),
        "by_depth_of_a": {
            cls: block([m for m in metrics if depth_class(m) == cls]) for cls in ("shallow", "deep")
        },
        "ambiguous_pairs": len(metrics) - len(unambiguous),
        "time_resolution": {"a": time_resolution(a_all), "b": time_resolution(b_all)},
    }
    if joint is not None:
        summary["coverage"] = {
            "declared": joint.declared,
            "inferred_inputs": [n for n, c in (("a", cov_a), ("b", cov_b)) if c is not None and not c.declared],
            "start": joint.start.isoformat() if joint.start else None,
            "end": joint.end.isoformat() if joint.end else None,
            "segments": [s.to_dict() for s in joint.segments],
        }
        summary["completeness"] = _completeness(result, joint, min_mag, cov_a, cov_b)
    return summary


def _completeness(
    result: MatchResult,
    joint: Coverage,
    min_mag: Optional[float],
    cov_a: Optional[Coverage],
    cov_b: Optional[Coverage],
) -> dict:
    def above(r: QuakeRecord) -> bool:
        return min_mag is None or (r.mag is not None and r.mag >= min_mag)

    def side(pairs: list[tuple[QuakeRecord, QuakeRecord]], unmatched: list[QuakeRecord]) -> dict:
        # A pair counts on both sides when either member is inside the overlap,
        # so a sub-second edge can't split a match.
        m = [r for r, partner in pairs if (joint.contains(r) or joint.contains(partner)) and above(r)]
        u = [r for r in unmatched if joint.contains(r) and above(r)]
        outside = [r for r in unmatched if not joint.contains(r) and above(r)]
        inside_mags = [r.mag for r, _ in pairs if joint.contains(r) and r.mag is not None]
        inside_mags += [r.mag for r in unmatched if joint.contains(r) and r.mag is not None]
        total = len(m) + len(u)
        u_sorted = sorted(u, key=lambda r: r.origin_time)
        return {
            "events": total,
            "matched": len(m),
            "match_rate": (len(m) / total) if total else None,
            "unmatched": [r.key for r in u_sorted][:LIST_LIMIT],
            "unmatched_count": len(u),
            "unmatched_outside_overlap": len(outside),
            "input_min_mag": min(inside_mags) if inside_mags else None,
        }

    a_side = side([(p.a, p.b) for p in result.pairs], result.unmatched_a)
    b_side = side([(p.b, p.a) for p in result.pairs], result.unmatched_b)
    return {
        "min_mag": min_mag,
        "note": "min_mag is applied to each catalog's own magnitude scale",
        "a": a_side,
        "b": b_side,
        "warnings": floor_warnings(a_side, b_side, cov_a, cov_b, min_mag),
    }


def floor_warnings(
    a_side: dict,
    b_side: dict,
    cov_a: Optional[Coverage],
    cov_b: Optional[Coverage],
    min_mag: Optional[float],
) -> list[dict]:
    """Flag magnitude ranges where missing partners say nothing about agreement.

    If input X has nothing below magnitude f (because it was downloaded with
    a limit, or because that is all it detects), quakes the other catalog
    rates below about f + SCALE_MARGIN may lack a partner for that reason
    alone. A declared floor (a download limit or a catalog's published range)
    is used when known; otherwise the smallest event actually present.
    """
    out = []
    sides = {"a": (a_side, cov_a), "b": (b_side, cov_b)}
    for name, other in (("a", "b"), ("b", "a")):
        own, cov = sides[name]
        other_side, _ = sides[other]
        declared = cov.declared_floor() if cov is not None and cov.declared else None
        floor = declared if declared is not None else own["input_min_mag"]
        low = min_mag if min_mag is not None else other_side["input_min_mag"]
        if floor is None or low is None or low >= floor + SCALE_MARGIN:
            continue
        out.append(
            {
                "kind": "declared-floor" if declared is not None else "observed-floor",
                "input": name,
                "other": other,
                "floor": floor,
                "low": low,
                "suggest_min_mag": round(floor + SCALE_MARGIN, 2),
            }
        )
    return out
