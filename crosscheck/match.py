"""Decide which records in two catalogs describe the same earthquake.

Method (see docs/METHOD.md for sources):
- Gate: |origin-time difference| <= time window AND great-circle epicentral
  distance <= distance window. The defaults, 16 s and 100 km, are the values
  USGS uses (PDL DefaultAssociator, libcomcat associate()); PDL applies the
  100 km as a lat/lon box, we apply it as a circle.
- Magnitude is NOT a gate. CWA reports ML while USGS reports mb/Mww etc.;
  differences of ~0.5 between scales are expected for some Taiwan events.
- One-to-one: each record pairs with at most one record from the other
  catalog. Within each cluster of mutually reachable records the pairing
  first maximises the number of matches, then minimises the total of a
  PDL-style normalized cost
  cost = sqrt((dt / time_window)^2 + (distance / dist_window)^2).
- A match is flagged ambiguous when some other candidate for either record
  is nearly as good (runner-up cost <= ambiguity_ratio * cost).
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from .geo import distance_km
from .model import QuakeRecord

_INFEASIBLE = 1e6  # far above any feasible cost (each is <= sqrt(2))
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_US = timedelta(microseconds=1)


def _micros(t: datetime) -> int:
    """Exact integer microseconds since the epoch (floats lose exactness at the gate edges)."""
    return (t - _EPOCH) // _US


@dataclass(frozen=True)
class MatchConfig:
    time_window_s: float = 16.0
    dist_window_km: float = 100.0
    ambiguity_ratio: float = 1.5


@dataclass
class Pair:
    a: QuakeRecord
    b: QuakeRecord
    dt_s: float  # a minus b
    dist_km: float
    cost: float
    runner_up_cost: Optional[float]
    ambiguous: bool


@dataclass
class MatchResult:
    pairs: list[Pair]
    unmatched_a: list[QuakeRecord]
    unmatched_b: list[QuakeRecord]
    config: MatchConfig = field(default_factory=MatchConfig)


def match(
    a: Sequence[QuakeRecord],
    b: Sequence[QuakeRecord],
    config: MatchConfig = MatchConfig(),
) -> MatchResult:
    T, D = config.time_window_s, config.dist_window_km
    if not (T > 0 and D > 0 and math.isfinite(T) and math.isfinite(D)):
        raise ValueError("time and distance windows must be positive")
    if not (config.ambiguity_ratio >= 1 and math.isfinite(config.ambiguity_ratio)):
        raise ValueError("ambiguity ratio must be >= 1")
    t_us = round(T * 1e6)
    b_sorted = sorted(range(len(b)), key=lambda j: b[j].origin_time)
    b_times = [_micros(b[j].origin_time) for j in b_sorted]

    # Candidate edges inside the gate: (i, j) -> (cost, dt, dist)
    edges: dict[tuple[int, int], tuple[float, float, float]] = {}
    for i, ra in enumerate(a):
        t = _micros(ra.origin_time)
        lo = bisect.bisect_left(b_times, t - t_us)
        hi = bisect.bisect_right(b_times, t + t_us)
        for k in range(lo, hi):
            j = b_sorted[k]
            dt = (t - b_times[k]) / 1e6
            d = distance_km(ra.lat, ra.lon, b[j].lat, b[j].lon)
            if d <= D:
                edges[(i, j)] = (math.hypot(dt / T, d / D), dt, d)

    chosen = _assign(edges)

    by_a: dict[int, list[float]] = {}
    by_b: dict[int, list[float]] = {}
    for (i, j), (c, _, _) in edges.items():
        by_a.setdefault(i, []).append(c)
        by_b.setdefault(j, []).append(c)

    pairs = []
    for i, j in sorted(chosen, key=lambda ij: a[ij[0]].origin_time):
        c, dt, d = edges[(i, j)]
        others = sorted(by_a[i]) + sorted(by_b[j])
        others.remove(c)  # the chosen edge appears once in each list
        others.remove(c)
        runner = min(others) if others else None
        ambiguous = runner is not None and runner <= config.ambiguity_ratio * c + 1e-12
        pairs.append(Pair(a[i], b[j], dt, d, c, runner, ambiguous))

    used_a = {i for i, _ in chosen}
    used_b = {j for _, j in chosen}
    return MatchResult(
        pairs=pairs,
        unmatched_a=[r for i, r in enumerate(a) if i not in used_a],
        unmatched_b=[r for j, r in enumerate(b) if j not in used_b],
        config=config,
    )


def _assign(edges: dict[tuple[int, int], tuple[float, float, float]]) -> list[tuple[int, int]]:
    """Optimal one-to-one assignment, solved separately per connected cluster."""
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in edges:
        ra, rb = find(("a", i)), find(("b", j))
        if ra != rb:
            parent[ra] = rb

    clusters: dict[tuple[str, int], list[tuple[int, int]]] = {}
    for i, j in edges:
        clusters.setdefault(find(("a", i)), []).append((i, j))

    chosen = []
    for cluster_edges in clusters.values():
        if len(cluster_edges) == 1:
            chosen.append(cluster_edges[0])
            continue
        rows = sorted({i for i, _ in cluster_edges})
        cols = sorted({j for _, j in cluster_edges})
        ri = {v: n for n, v in enumerate(rows)}
        ci = {v: n for n, v in enumerate(cols)}
        cost = np.full((len(rows), len(cols)), _INFEASIBLE)
        for i, j in cluster_edges:
            cost[ri[i], ci[j]] = edges[(i, j)][0]
        r_idx, c_idx = linear_sum_assignment(cost)
        for r, c in zip(r_idx, c_idx):
            if cost[r, c] < _INFEASIBLE:
                chosen.append((rows[r], cols[c]))
    return chosen


def sweep(
    a: Sequence[QuakeRecord],
    b: Sequence[QuakeRecord],
    time_windows_s: Sequence[float] = (16, 30, 60, 120),
    dist_windows_km: Sequence[float] = (50, 100, 150),
    ambiguity_ratio: float = MatchConfig.ambiguity_ratio,
) -> list[dict]:
    """How the number of matches depends on the window choice."""
    rows = []
    for T in time_windows_s:
        for D in dist_windows_km:
            r = match(a, b, MatchConfig(time_window_s=T, dist_window_km=D, ambiguity_ratio=ambiguity_ratio))
            rows.append(
                {
                    "time_window_s": T,
                    "dist_window_km": D,
                    "pairs": len(r.pairs),
                    "ambiguous": sum(p.ambiguous for p in r.pairs),
                }
            )
    return rows
