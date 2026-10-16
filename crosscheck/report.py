"""Write comparison results as CSV (one row per pair), JSON (summary) and Markdown."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

from .compare import SCALE_MARGIN, PairMetrics, pair_metrics
from .match import MatchResult

PAIR_TABLE_MAX = 30  # list every pair in report.md when there are this few


def write_pairs_csv(result: MatchResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(PairMetrics)]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in result.pairs:
            row = asdict(pair_metrics(p))
            w.writerow({k: round(v, 6) + 0.0 if isinstance(v, float) else v for k, v in row.items()})


def write_summary_json(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")


def render_markdown(
    summary: dict,
    a_label: str,
    b_label: str,
    sweep_rows: Optional[list[dict]] = None,
    result: Optional[MatchResult] = None,
    attribution: Optional[str] = None,
) -> str:
    cfg = summary["config"]
    allp = summary["all_pairs"]
    labels = {"a": a_label, "b": b_label}
    L = [
        f"# {a_label} vs {b_label}",
        "",
        f"Residuals are **{a_label} minus {b_label}**. Matching gate: "
        f"|dt| <= {cfg['time_window_s']:g} s and distance <= {cfg['dist_window_km']:g} km, "
        "one-to-one, magnitude not used to match.",
        "",
        f"- Matched pairs: **{allp['pairs']}** ({summary['ambiguous_pairs']} flagged ambiguous)",
    ]
    cov = summary.get("coverage")
    if cov:
        L.append(f"- Overlap: {cov['start']} to {cov['end']} ({len(cov['segments'])} region/time segment(s))")
        for name in cov["inferred_inputs"]:
            L.append(
                f"- **Coverage of {labels[name]} was inferred** from its first and last events, so misses "
                "near the ends of that span are not counted. Fetch or parse with this tool to record the "
                "real coverage, or pass --start/--end."
            )
    else:
        L.append("- The inputs do not overlap in time and region, so completeness is not reported.")

    L += ["", "## Location, depth and timing", ""]
    L += _stats_table(
        [
            ("Origin time (s)", allp["dt_s"]),
            ("Epicenter distance (km)", allp["dist_km"]),
            ("Depth (km)", allp["d_depth_km"]),
        ]
    )
    res = summary.get("time_resolution", {})
    for name in ("a", "b"):
        if res.get(name) == "1 s":
            L += [
                "",
                f"{labels[name]} origin times are whole seconds, so origin-time differences under about 1 s "
                f"are not resolvable. If {labels[name]} truncates rather than rounds (not known), "
                f"its times carry a constant offset of about -0.5 s that averaging will not remove.",
            ]
    if "mean_offset" in allp:
        mo = allp["mean_offset"]
        L += [
            "",
            f"Mean epicenter offset ({a_label} relative to {b_label}): "
            f"{_f(mo['length_km'])} km toward {mo['azimuth_deg']:.0f}° "
            f"(east {_f(mo['east_km'], sign=True)} km, north {_f(mo['north_km'], sign=True)} km).",
        ]
    L += ["", "## Magnitude, by magnitude-type pair", ""]
    if allp["d_mag_by_type"]:
        L += _stats_table([(k, v) for k, v in allp["d_mag_by_type"].items()])
        L += ["", "Different magnitude types are different scales; differences are not errors by themselves."]
    else:
        L.append("No pairs with magnitudes on both sides.")
    L += ["", f"## By {a_label} depth (shallow <= 35 km)", ""]
    for cls, blk in summary["by_depth_of_a"].items():
        L.append(f"**{cls}** ({blk['pairs']} pairs)")
        L.append("")
        L += _stats_table(
            [("Epicenter distance (km)", blk["dist_km"]), ("Depth (km)", blk["d_depth_km"])]
            + [(f"Magnitude {k}", v) for k, v in blk["d_mag_by_type"].items()]
        )
        L.append("")
    if result is not None and 0 < len(result.pairs) <= PAIR_TABLE_MAX:
        L += _pair_table(result)
    if "completeness" in summary:
        L += _completeness_section(summary["completeness"], labels)
    if sweep_rows:
        L += ["", "## Window sensitivity", "", "| Time window (s) | Distance window (km) | Pairs | Ambiguous |", "|---:|---:|---:|---:|"]
        for r in sweep_rows:
            L.append(f"| {r['time_window_s']:g} | {r['dist_window_km']:g} | {r['pairs']} | {r['ambiguous']} |")
    if attribution:
        L += ["", "## Data attribution", "", attribution]
    L.append("")
    return "\n".join(L)


def _completeness_section(comp: dict, labels: dict) -> list[str]:
    mm = comp["min_mag"]
    L = ["## Completeness inside the overlap", ""]
    L.append(
        f"Events at or above magnitude {mm:g} on each catalog's own scale."
        if mm is not None
        else "All events (no magnitude cutoff)."
    )
    L += [
        "",
        "| Catalog | Events | Matched | Match rate | Smallest magnitude present | Unmatched outside the overlap (not judged) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("a", "b"):
        side = comp[name]
        rate = f"{side['match_rate']:.1%}" if side["match_rate"] is not None else "n/a"
        floor = _f(side["input_min_mag"]) if side["input_min_mag"] is not None else "n/a"
        L.append(
            f"| {labels[name]} | {side['events']} | {side['matched']} | {rate} | {floor} | "
            f"{side['unmatched_outside_overlap']} |"
        )
    for w in comp.get("warnings", []):
        own, other = labels[w["input"]], labels[w["other"]]
        why = (
            f"was downloaded or published with a minimum magnitude of {w['floor']:g}"
            if w["kind"] == "declared-floor"
            else f"has no events below M{w['floor']:g} inside the overlap (a download limit or its detection threshold)"
        )
        L += [
            "",
            f"> **Warning:** the {own} input {why}. Two magnitude scales can rate one quake up to about "
            f"{SCALE_MARGIN:g} apart, so {other} events below about M{w['suggest_min_mag']:g} may have no partner "
            f"for that reason alone; their match rate says nothing about agreement. "
            f"Re-run with --min-mag {w['suggest_min_mag']:g} or higher to judge completeness above it.",
        ]
    for name in ("a", "b"):
        side = comp[name]
        if side["unmatched_count"]:
            shown = side["unmatched"]
            L += ["", f"Unmatched in {labels[name]} ({side['unmatched_count']}):", ""]
            L += [f"- {k}" for k in shown]
            if side["unmatched_count"] > len(shown):
                L.append(f"- ... and {side['unmatched_count'] - len(shown)} more")
    return L


def _pair_table(result: MatchResult) -> list[str]:
    L = [
        "## Pairs",
        "",
        "| A | B | dt (s) | distance (km) | toward (°) | depth diff (km) | magnitudes | mag diff |",
        "|---|---|---:|---:|---:|---:|---|---:|",
    ]
    for p in result.pairs:
        m = pair_metrics(p)
        mags = f"{_f(m.a_mag)} vs {_f(m.b_mag)} ({m.mag_pair})"
        L.append(
            f"| {m.a_key} | {m.b_key} | {_f(m.dt_s)} | {_f(m.dist_km)} | {m.azimuth_deg:.0f} | "
            f"{_f(m.d_depth_km)} | {mags} | {_f(m.d_mag)} |"
        )
    L.append("")
    return L


def _stats_table(rows: list[tuple[str, dict]]) -> list[str]:
    out = ["| Quantity | n | mean | median | std | MAD | min | max |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, s in rows:
        if not s or s.get("n", 0) == 0:
            out.append(f"| {name} | 0 | | | | | | |")
            continue
        out.append(
            f"| {name} | {s['n']} | {_f(s['mean'])} | {_f(s['median'])} | {_f(s['std'])} | "
            f"{_f(s['mad'])} | {_f(s['min'])} | {_f(s['max'])} |"
        )
    return out


def _f(x, sign: bool = False) -> str:
    """Two decimals; never prints '-0.00' for a value that rounds to zero."""
    if x is None:
        return ""
    v = round(x, 2) + 0.0
    return f"{v:+.2f}" if sign else f"{v:.2f}"
