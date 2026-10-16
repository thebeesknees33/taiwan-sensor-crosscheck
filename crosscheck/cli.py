"""Command line: fetch or parse sources, compare two catalogs, export CoT.

    crosscheck fetch usgs --start 2026-01-01 --end 2026-10-01 --out out/usgs.jsonl
    crosscheck fetch cwa --product catalog --years 2026 --out out/cwa.jsonl
    crosscheck parse cwa saved/E-A0015-001.zip --out out/cwa-reports.jsonl
    crosscheck compare out/cwa.jsonl out/usgs.jsonl --min-mag 4.5 --sweep
    crosscheck cot out/cwa.jsonl --out-dir out/cot
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import __version__
from .compare import resolve_coverage, summarize
from .coverage import CWA_ATTRIBUTION, Coverage, merge, read_coverage, write_info
from .http import FetchError
from .match import MatchConfig, match, sweep
from .model import QuakeRecord, read_jsonl, write_jsonl
from .report import render_markdown, write_pairs_csv, write_summary_json
from .sources import TAIWAN_BBOX, TAIWAN_FETCH_BBOX

SIDECAR_SUFFIXES = (".meta.json", ".info.json")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args) or 0
    except (FetchError, ValueError, RuntimeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crosscheck", description=__doc__.split("\n\n")[0])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers()

    f = sub.add_parser("fetch", help="download live data (saves raw responses too)")
    fsub = f.add_subparsers()
    fu = fsub.add_parser("usgs", help="USGS ComCat via the FDSN event service")
    fu.add_argument("--start", required=True, type=_time, help="UTC date/time, e.g. 2026-01-01")
    fu.add_argument("--end", required=True, type=_time)
    fu.add_argument(
        "--bbox",
        type=_bbox,
        default=TAIWAN_FETCH_BBOX,
        help="lon_min,lat_min,lon_max,lat_max (default: CWA's region plus 1 degree)",
    )
    fu.add_argument("--min-mag", type=float)
    _out_args(fu, "out/usgs.jsonl")
    fu.set_defaults(func=cmd_fetch_usgs)

    fc = fsub.add_parser("cwa", help="Taiwan CWA reports or catalog")
    fc.add_argument("--product", choices=["catalog", "significant", "small"], default="catalog")
    fc.add_argument("--years", type=_years, help="catalog UTC years, e.g. 2015 or 2015-2017,2020")
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
    pc.add_argument("--years", type=_years, help="keep only these UTC years")
    pc.add_argument("--out", type=Path, default=Path("out/cwa.jsonl"))
    pc.set_defaults(func=cmd_parse_cwa)

    c = sub.add_parser("compare", help="match two catalogs and measure their differences")
    c.add_argument("a", type=Path, help="JSONL of catalog A (residuals are A minus B)")
    c.add_argument("b", type=Path, help="JSONL of catalog B")
    c.add_argument("--a-label", default="CWA")
    c.add_argument("--b-label", default="USGS")
    c.add_argument("--time-window", type=_positive, default=16.0, help="seconds (default 16)")
    c.add_argument("--dist-window", type=_positive, default=100.0, help="km (default 100)")
    c.add_argument("--ambiguity-ratio", type=_ratio, default=1.5)
    c.add_argument("--min-mag", type=float, help="magnitude cutoff for completeness, each on its own scale")
    c.add_argument("--bbox", type=_bbox, help="narrow the completeness region")
    c.add_argument("--start", type=_time, help="narrow the completeness window")
    c.add_argument("--end", type=_time)
    c.add_argument("--sweep", action="store_true", help="also report match counts for other windows")
    c.add_argument("--out-dir", type=Path, default=Path("out/compare"))
    c.set_defaults(func=cmd_compare)

    t = sub.add_parser("cot", help="export records as Cursor-on-Target XML")
    t.add_argument("input", type=Path)
    t.add_argument("--out-dir", type=Path, default=Path("out/cot"))
    t.add_argument("--stale-hours", type=_positive, default=24.0)
    t.add_argument("--type", dest="cot_type", default="b-m-p-s-m")
    t.add_argument(
        "--send",
        metavar="HOST[:PORT]",
        type=_hostport,
        help="also stream to a TAK server over plain TCP (port 8088 default; IPv6 as [addr]:port)",
    )
    t.add_argument("--send-interval", type=float, default=0.02, help="seconds between streamed events")
    t.set_defaults(func=cmd_cot)
    return p


def _out_args(p, default_out: str) -> None:
    p.add_argument("--out", type=Path, default=Path(default_out))
    p.add_argument("--raw-dir", type=Path, default=Path("out/raw"), help="where raw responses are kept")


# ---------------------------------------------------------------- commands


def cmd_fetch_usgs(a) -> int:
    from .sources import usgs

    if a.start >= a.end:
        raise ValueError("--start must be before --end")
    recs = usgs.fetch_events(a.start, a.end, a.bbox, a.min_mag, raw_dir=a.raw_dir / "usgs")
    return _save(recs, a.out, usgs.query_coverage(a.start, a.end, a.bbox, a.min_mag))


def cmd_fetch_cwa(a) -> int:
    from .sources import cwa

    raw = a.raw_dir / "cwa"
    cov = None
    if a.product == "catalog":
        if a.rest:
            print("the catalog is only available from S3; ignoring --rest", file=sys.stderr)
        segs: list = []
        recs = cwa.fetch_catalog(a.years, raw_dir=raw, segments=segs)
        cov = Coverage(segs) if segs else None
        if a.years:
            _warn_missing_years(recs, a.years)
    elif a.rest:
        recs = cwa.fetch_reports_rest(a.product, limit=a.limit, raw_dir=raw)
    else:
        recs = cwa.fetch_reports_s3(a.product, raw_dir=raw)
    return _save(recs, a.out, cov)


def cmd_parse_usgs(a) -> int:
    from .sources import usgs

    recs: list[QuakeRecord] = []
    covs: list[Optional[Coverage]] = []
    for path in _data_files(a.files):
        data = path.read_bytes()
        try:
            recs.extend(usgs.parse_geojson(data))
            covs.append(usgs.coverage_from_geojson(data))
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{path.name}: {e}") from None
    return _save(_dedupe(recs), a.out, merge(covs))


def cmd_parse_cwa(a) -> int:
    from .sources import cwa

    recs: list[QuakeRecord] = []
    segs: list = []
    for path in _data_files(a.files):
        recs.extend(cwa.parse_file(path, segs))
    if a.years:
        recs = [r for r in recs if r.origin_time.year in a.years]
        segs = cwa.clip_segments_to_years(segs, a.years)
        _warn_missing_years(recs, a.years)
    # Report files declare no coverage; only a pure catalog input gets one.
    only_catalog = recs and all(r.product == cwa.CATALOG_PRODUCT for r in recs)
    cov = Coverage(segs) if segs and only_catalog else None
    return _save(_dedupe(recs), a.out, cov)


def cmd_compare(a) -> int:
    if a.start and a.end and a.start >= a.end:
        raise ValueError("--start must be before --end")
    A = list(read_jsonl(a.a))
    B = list(read_jsonl(a.b))
    cfg = MatchConfig(a.time_window, a.dist_window, a.ambiguity_ratio)
    result = match(A, B, cfg)
    cov_a, cov_b, joint = resolve_coverage(
        A, B, read_coverage(a.a), read_coverage(a.b), TAIWAN_BBOX, a.bbox, a.start, a.end
    )
    summary = summarize(result, joint, a.min_mag, cov_a, cov_b)
    rows = sweep(A, B, ambiguity_ratio=cfg.ambiguity_ratio) if a.sweep else None
    if rows:
        summary["sweep"] = rows
    attribution = CWA_ATTRIBUTION if any(r.source == "cwa" for r in A + B) else None
    if attribution:
        summary["attribution"] = attribution
    a.out_dir.mkdir(parents=True, exist_ok=True)
    write_pairs_csv(result, a.out_dir / "pairs.csv")
    write_summary_json(summary, a.out_dir / "summary.json")
    md = render_markdown(summary, a.a_label, a.b_label, rows, result, attribution)
    (a.out_dir / "report.md").write_text(md, encoding="utf-8")
    if attribution:
        (a.out_dir / "ATTRIBUTION.txt").write_text(attribution + "\n", encoding="utf-8")
    _print_text(md)
    print(f"wrote {a.out_dir}/report.md, summary.json, pairs.csv", file=sys.stderr)
    return 0


def cmd_cot(a) -> int:
    from . import cot

    recs = list(read_jsonl(a.input))
    n = cot.write_files(recs, a.out_dir, stale_hours=a.stale_hours, cot_type=a.cot_type)
    print(f"wrote {n} CoT files to {a.out_dir}", file=sys.stderr)
    if a.send:
        host, port = a.send
        res = cot.send_tcp(
            recs, host, port, interval_s=a.send_interval, stale_hours=a.stale_hours, cot_type=a.cot_type
        )
        where = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        if res.confirmed:
            print(f"streamed {res.written} events to {where}; the server read all of them and closed the connection", file=sys.stderr)
        else:
            print(
                f"streamed {res.written} events to {where}, but the server did not close the connection "
                "afterwards, so delivery is unconfirmed",
                file=sys.stderr,
            )
            return 1
    return 0


# ---------------------------------------------------------------- helpers


def _save(recs: list[QuakeRecord], out: Path, coverage: Optional[Coverage]) -> int:
    n = write_jsonl(recs, out)
    info = write_info(out, recs, coverage)
    note = "with declared coverage" if coverage else "no declared coverage"
    print(f"wrote {n} records to {out} ({note}; see {info.name})", file=sys.stderr)
    return 0


def _data_files(paths: list[Path]) -> list[Path]:
    """Skip the sidecar files this tool writes next to raw responses and JSONL outputs."""
    keep = [p for p in paths if not p.name.endswith(SIDECAR_SUFFIXES)]
    skipped = len(paths) - len(keep)
    if skipped:
        print(f"skipping {skipped} sidecar file(s) (*.meta.json, *.info.json)", file=sys.stderr)
    return keep


def _warn_missing_years(recs: list[QuakeRecord], years: set[int]) -> None:
    present = {r.origin_time.year for r in recs}
    missing = sorted(y for y in years if y not in present)
    if missing:
        print(
            f"warning: no records for year(s) {', '.join(map(str, missing))} "
            "(CWA adds a finished year to its catalog a few weeks into the next year)",
            file=sys.stderr,
        )


def _dedupe(recs: list[QuakeRecord]) -> list[QuakeRecord]:
    seen: dict[str, QuakeRecord] = {}
    for r in recs:
        seen.setdefault(r.key, r)
    return sorted(seen.values(), key=lambda r: r.origin_time)


def _print_text(text: str) -> None:
    """Print to a console that may not support CJK or other non-ASCII text (e.g. Windows cp1252)."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    sys.stdout.write(text.encode(enc, errors="replace").decode(enc, errors="replace") + "\n")


def _time(s: str) -> datetime:
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date/time: {s!r}") from None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def _bbox(s: str) -> tuple[float, float, float, float]:
    try:
        parts = [float(x) for x in s.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError("bbox needs 4 numbers: lon_min,lat_min,lon_max,lat_max") from None
    if len(parts) != 4 or not all(math.isfinite(x) for x in parts):
        raise argparse.ArgumentTypeError("bbox needs 4 finite numbers: lon_min,lat_min,lon_max,lat_max")
    lon_min, lat_min, lon_max, lat_max = parts
    if lon_min >= lon_max or lat_min >= lat_max:
        raise argparse.ArgumentTypeError("bbox min must be below max")
    if not (-180 <= lon_min and lon_max <= 180 and -90 <= lat_min and lat_max <= 90):
        raise argparse.ArgumentTypeError("bbox must lie within -180..180 and -90..90")
    return lon_min, lat_min, lon_max, lat_max


def _years(s: str) -> set[int]:
    out: set[int] = set()
    for part in s.split(","):
        lo, _, hi = part.strip().partition("-")
        try:
            a, b = int(lo), int(hi or lo)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a year or year range: {part!r}") from None
        if b < a:
            raise argparse.ArgumentTypeError(f"reversed year range: {part!r}")
        out.update(range(a, b + 1))
    return out


def _positive(s: str) -> float:
    v = float(s)
    if not (v > 0 and math.isfinite(v)):
        raise argparse.ArgumentTypeError("must be a positive number")
    return v


def _ratio(s: str) -> float:
    v = float(s)
    if not (v >= 1 and math.isfinite(v)):
        raise argparse.ArgumentTypeError("must be a number >= 1")
    return v


def _hostport(s: str) -> tuple[str, int]:
    """host, host:port, [ipv6], [ipv6]:port or a bare IPv6 address."""
    s = s.strip()
    if s.startswith("["):
        host, sep, rest = s[1:].partition("]")
        if not sep or (rest and not rest.startswith(":")):
            raise argparse.ArgumentTypeError(f"bad address: {s!r}")
        port_s = rest[1:] if rest else ""
    elif s.count(":") > 1:  # bare IPv6, no port
        host, port_s = s, ""
    else:
        host, _, port_s = s.partition(":")
    if not host:
        raise argparse.ArgumentTypeError(f"missing host: {s!r}")
    if not port_s:
        return host, 8088
    if not port_s.isdigit() or not 1 <= int(port_s) <= 65535:
        raise argparse.ArgumentTypeError(f"port must be 1-65535: {port_s!r}")
    return host, int(port_s)


if __name__ == "__main__":
    sys.exit(main())
