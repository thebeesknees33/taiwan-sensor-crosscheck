"""Write comparison results as CSV (one row per pair), JSON (summary) and Markdown."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, fields
from pathlib import Path
from typing import Optional

from .compare import PairMetrics, pair_metrics
from .match import MatchResult


def write_pairs_csv(result: MatchResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [f.name for f in fields(PairMetrics)]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for p in result.pairs:
            row = asdict(pair_metrics(p))
            w.writerow({k: round(v, 6) if isinstance(v, float) else v for k, v in row.items()})


def write_summary_json(summary: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")


def render_markdown(
    summary: dict,
    a_label: str,
    b_label: str,
    sweep_rows: Optional[list[dict]] = None,
) -> str:
    cfg = summary["config"]
    allp = summary["all_pairs"]
    L = [
        f"# {a_label} vs {b_label}",
        "",
        f"Residuals are **{a_label} minus {b_label}**. Matching gate: "
        f"|dt| <= {cfg['time_window_s']:g} s and distance <= {cfg['dist_window_km']:g} km, "
        "one-to-one, magnitude not used to match.",
        "",
        f"- Matched pairs: **{allp['pairs']}** ({summary['ambiguous_pairs']} flagged ambiguous)",
    ]
    if "coverage" in summary:
        c = summary["coverage"]
        L.append(f"- Overlap window: {c['start']} to {c['end']}, bbox {c['bbox']}")
    L += ["", "## Location, depth and timing", ""]
    L += _stats_table(
        [
            ("Origin time (s)", allp["dt_s"]),
            ("Epicenter distance (km)", allp["dist_km"]),
            ("Depth (km)", allp["d_depth_km"]),
        ]
    )
    if "mean_offset" in allp:
        mo = allp["mean_offset"]
        L += [
            "",
            f"Mean epicenter offset ({a_label} relative to {b_label}): "
            f"{mo['length_km']:.2f} km toward {mo['azimuth_deg']:.0f}° "
            f"(east {mo['east_km']:+.2f} km, north {mo['north_km']:+.2f} km).",
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
    if "completeness" in summary:
        comp = summary["completeness"]
        mm = comp["min_mag"]
        L += ["## Completeness inside the overlap window", ""]
        L.append(
            f"Events at or above magnitude {mm:g} on each catalog's own scale."
            if mm is not None
            else "All events (no magnitude cutoff)."
        )
        L += ["", "| Catalog | Events | Matched | Match rate |", "|---|---:|---:|---:|"]
        for label, side in ((a_label, comp["a"]), (b_label, comp["b"])):
            rate = f"{side['match_rate']:.1%}" if side["match_rate"] is not None else "n/a"
            L.append(f"| {label} | {side['events']} | {side['matched']} | {rate} |")
        labels = {"a": a_label, "b": b_label}
        for w in comp.get("warnings", []):
            L += [
                "",
                f"> **Warning:** the {labels[w['input']]} input has no events below "
                f"M{w['input_min_mag']:g}, close to the cutoff M{w['cutoff']:g}. If it was downloaded "
                f"with a magnitude limit, unmatched {labels[w['other']]} events near the cutoff may "
                f"simply be below that limit on the {labels[w['input']]} scale.",
            ]
        for label, side in ((a_label, comp["a"]), (b_label, comp["b"])):
            if side["unmatched"]:
                shown = side["unmatched"][:50]
                L += ["", f"Unmatched in {label} ({len(side['unmatched'])}):", ""]
                L += [f"- {k}" for k in shown]
                if len(side["unmatched"]) > len(shown):
                    L.append(f"- ... and {len(side['unmatched']) - len(shown)} more (see summary JSON)")
    if sweep_rows:
        L += ["", "## Window sensitivity", "", "| Time window (s) | Distance window (km) | Pairs | Ambiguous |", "|---:|---:|---:|---:|"]
        for r in sweep_rows:
            L.append(f"| {r['time_window_s']:g} | {r['dist_window_km']:g} | {r['pairs']} | {r['ambiguous']} |")
    L.append("")
    return "\n".join(L)


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


def _f(x) -> str:
    return "" if x is None else f"{x:.2f}"
