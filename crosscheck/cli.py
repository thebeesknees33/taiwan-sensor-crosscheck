"""Command line: fetch or parse sources, compare two catalogs, export CoT.

    crosscheck fetch usgs --start 2026-01-01 --end 2026-10-01 --out out/usgs.jsonl
    crosscheck fetch cwa --product catalog --years 2026 --out out/cwa.jsonl
    crosscheck parse cwa saved/E-A0015-001.zip --out out/cwa-reports.jsonl
    crosscheck compare out/cwa.jsonl out/usgs.jsonl --min-mag 4.5 --sweep
    crosscheck cot out/cwa.jsonl --out-dir out/cot
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__
from .compare import Coverage, overlap_coverage, summarize
from .match import MatchConfig, match, sweep
from .model import QuakeRecord, read_jsonl, write_jsonl
from .report import render_markdown, write_pairs_csv, write_summary_json
from .sources import TAIWAN_BBOX


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 2
    return args.func(args) or 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crosscheck", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers()

    f = sub.add_parser("fetch", help="download live data (saves raw responses too)")
    fsub = f.add_subparsers()
    fu = fsub.add_parser("usgs", help="USGS ComCat via the FDSN event service")
    fu.add_argument("--start", required=True, type=_time, help="UTC date/time, e.g. 2026-01-01")
    fu.add_argument("--end", required=True, type=_time)
    fu.add_argument("--bbox", type=_bbox, default=TAIWAN_BBOX, help="lon_min,lat_min,lon_max,lat_max")
    fu.add_argument("--min-mag", type=float)
    _out_args(fu, "out/usgs.jsonl")
    fu.set_defaults(func=cmd_fetch_usgs)

    fc = fsub.add_parser("cwa", help="Taiwan CWA reports or catalog")
    fc.add_argument("--product", choices=["catalog", "significant", "small"], default="catalog")
    fc.add_argument("--years", type=_years, help="catalog years, e.g. 2015 or 2015-2017,2020")
    fc.add_argument("--rest", action="store_true", help="use the REST API (needs CWA_API_KEY) instead of S3")
    fc.add_argument("--limit", type=int, help="REST only: number of reports")
    _out_args(fc, "out/cwa.jsonl")
    fc.set_defaults(func=cmd_fetch_cwa)

    pa = sub.add_parser("parse", help="convert saved files to JSONL records")
    psub = pa.add_subparsers()
    pu = psub.add_parser("usgs", help="saved ComCat GeoJSON")
    pu.add_argument("files", nargs="+", type=Path)
    pu.add_argument("--out", type=Path, default=Path("out/usgs.jsonl"))
    pu.set_defaults(func=cmd_parse_usgs)
    pc = psub.add_parser("cwa", help="saved CWA zip/XML/JSON (auto-detected)")
    pc.add_argument("files", nargs="+", type=Path)
    pc.add_argument("--years", type=_years, help="keep only these years (by UTC origin time)")
    pc.add_argument(
        "--product",
        choices=["cwa-report-significant", "cwa-report-small"],
        help="label for report files whose name doesn't contain E-A0015/E-A0016",
    )
    pc.add_argument("--out", type=Path, default=Path("out/cwa.jsonl"))
    pc.set_defaults(func=cmd_parse_cwa)

    c = sub.add_parser("compare", help="match two catalogs and measure their differences")
    c.add_argument("a", type=Path, help="JSONL of catalog A (residuals are A minus B)")
    c.add_argument("b", type=Path, help="JSONL of catalog B")
    c.add_argument("--a-label", default="CWA")
    c.add_argument("--b-label", default="USGS")
    c.add_argument("--time-window", type=float, default=16.0, help="seconds (default 16)")
    c.add_argument("--dist-window", type=float, default=100.0, help="km (default 100)")
    c.add_argument("--ambiguity-ratio", type=float, default=1.5)
    c.add_argument("--min-mag", type=float, help="magnitude cutoff for completeness, each on its own scale")
    c.add_argument("--bbox", type=_bbox, default=TAIWAN_BBOX, help="region for completeness")
    c.add_argument("--start", type=_time, help="completeness window start (default: overlap of inputs)")
    c.add_argument("--end", type=_time)
    c.add_argument("--sweep", action="store_true", help="also report match counts for other windows")
    c.add_argument("--out-dir", type=Path, default=Path("out/compare"))
    c.set_defaults(func=cmd_compare)

    t = sub.add_parser("cot", help="export records as Cursor-on-Target XML")
    t.add_argument("input", type=Path)
    t.add_argument("--out-dir", type=Path, default=Path("out/cot"))
    t.add_argument("--stale-hours", type=float, default=24.0)
    t.add_argument("--type", dest="cot_type", default="b-m-p-s-m")
    t.add_argument("--send", metavar="HOST[:PORT]", help="also stream to a TAK server over plain TCP (port 8088 default)")
    t.set_defaults(func=cmd_cot)
    return p


def _out_args(p, default_out: str) -> None:
    p.add_argument("--out", type=Path, default=Path(default_out))
    p.add_argument("--raw-dir", type=Path, default=Path("out/raw"), help="where raw responses are kept")


# ---------------------------------------------------------------- commands


def cmd_fetch_usgs(a) -> int:
    from .sources import usgs

    recs = usgs.fetch_events(a.start, a.end, a.bbox, a.min_mag, raw_dir=a.raw_dir / "usgs")
    return _save(recs, a.out)


def cmd_fetch_cwa(a) -> int:
    from .sources import cwa

    raw = a.raw_dir / "cwa"
    if a.product == "catalog":
        if a.rest:
            print("the catalog is only available from S3; ignoring --rest", file=sys.stderr)
        recs = cwa.fetch_catalog(a.years, raw_dir=raw)
    elif a.rest:
        recs = cwa.fetch_reports_rest(a.product, limit=a.limit, raw_dir=raw)
    else:
        recs = cwa.fetch_reports_s3(a.product, raw_dir=raw)
    if a.years and a.product == "catalog":
        recs = [r for r in recs if r.origin_time.year in a.years]
    return _save(recs, a.out)


def cmd_parse_usgs(a) -> int:
    from .sources import usgs

    recs: list[QuakeRecord] = []
    for path in a.files:
        recs.extend(usgs.parse_geojson(path.read_bytes()))
    return _save(_dedupe(recs), a.out)


def cmd_parse_cwa(a) -> int:
    from .sources import cwa

    recs: list[QuakeRecord] = []
    for path in a.files:
        recs.extend(cwa.parse_file(path, a.product))
    if a.years:
        recs = [r for r in recs if r.origin_time.year in a.years]
    return _save(_dedupe(recs), a.out)


def cmd_compare(a) -> int:
    A = list(read_jsonl(a.a))
    B = list(read_jsonl(a.b))
    cfg = MatchConfig(a.time_window, a.dist_window, a.ambiguity_ratio)
    result = match(A, B, cfg)
    if a.start or a.end:
        cov = overlap_coverage(A, B, a.bbox)
        start = a.start or (cov.start if cov else None)
        end = a.end or (cov.end if cov else None)
        cov = Coverage(start, end, a.bbox) if start and end else None
    else:
        cov = overlap_coverage(A, B, a.bbox)
    summary = summarize(result, cov, a.min_mag)
    rows = sweep(A, B) if a.sweep else None
    if rows:
        summary["sweep"] = rows
    a.out_dir.mkdir(parents=True, exist_ok=True)
    write_pairs_csv(result, a.out_dir / "pairs.csv")
    write_summary_json(summary, a.out_dir / "summary.json")
    md = render_markdown(summary, a.a_label, a.b_label, rows)
    (a.out_dir / "report.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"wrote {a.out_dir}/report.md, summary.json, pairs.csv", file=sys.stderr)
    return 0


def cmd_cot(a) -> int:
    from . import cot

    recs = list(read_jsonl(a.input))
    n = cot.write_files(recs, a.out_dir, stale_hours=a.stale_hours, cot_type=a.cot_type)
    print(f"wrote {n} CoT files to {a.out_dir}", file=sys.stderr)
    if a.send:
        host, _, port = a.send.partition(":")
        sent = cot.send_tcp(recs, host, int(port or 8088), stale_hours=a.stale_hours, cot_type=a.cot_type)
        print(f"sent {sent} events to {host}:{port or 8088}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- helpers


def _save(recs: list[QuakeRecord], out: Path) -> int:
    n = write_jsonl(recs, out)
    print(f"wrote {n} records to {out}", file=sys.stderr)
    return 0


def _dedupe(recs: list[QuakeRecord]) -> list[QuakeRecord]:
    seen: dict[str, QuakeRecord] = {}
    for r in recs:
        seen.setdefault(r.key, r)
    return sorted(seen.values(), key=lambda r: r.origin_time)


def _time(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _bbox(s: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox needs 4 numbers: lon_min,lat_min,lon_max,lat_max")
    lon_min, lat_min, lon_max, lat_max = parts
    if lon_min >= lon_max or lat_min >= lat_max:
        raise argparse.ArgumentTypeError("bbox min must be below max")
    return lon_min, lat_min, lon_max, lat_max


def _years(s: str) -> set[int]:
    out: set[int] = set()
    for part in s.split(","):
        lo, _, hi = part.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out


if __name__ == "__main__":
    sys.exit(main())
