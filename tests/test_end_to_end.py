"""The first real cross-check: CWA's 2015 catalog vs a saved USGS M6+ 2015 query.

Both inputs are genuine published data (see fixtures/PROVENANCE.md). The
expected numbers below were produced by this code from those files; they are
a regression check, not independently published values.
"""

import csv
import json

import pytest

from crosscheck.cli import main


@pytest.fixture
def run_2015(fixtures, tmp_path):
    usgs = tmp_path / "usgs.jsonl"
    cwa = tmp_path / "cwa.jsonl"
    out = tmp_path / "compare"
    assert main(["parse", "usgs", str(fixtures / "usgs" / "fdsn-2015-m6plus.geojson"), "--out", str(usgs)]) == 0
    assert main(["parse", "cwa", str(fixtures / "cwa" / "CWA-EQ-Catalog-2015.xml"), "--out", str(cwa)]) == 0
    assert main(["compare", str(cwa), str(usgs), "--min-mag", "6.0", "--sweep", "--out-dir", str(out)]) == 0
    return out


def test_2015_pairs(run_2015):
    rows = list(csv.DictReader((run_2015 / "pairs.csv").open(encoding="utf-8")))
    pairs = {r["b_key"].split(":")[-1]: r for r in rows}
    assert set(pairs) == {"usb000tp6y", "us200027ps", "us200027rt", "us200027ru"}
    assert all(r["mag_pair"] == "ml-mww" for r in rows)
    ps = pairs["us200027ps"]  # 2015-04-20 M6.4 off Su'ao
    assert ps["a_key"] == "cwa:cwa-catalog:20150420T014256"
    assert float(ps["dist_km"]) == pytest.approx(23.76, abs=0.01)
    assert float(ps["dt_s"]) == pytest.approx(-2.38, abs=0.01)
    assert float(ps["d_mag"]) == pytest.approx(0.0, abs=1e-9)


def test_2015_summary_and_report(run_2015):
    s = json.loads((run_2015 / "summary.json").read_text(encoding="utf-8"))
    assert s["all_pairs"]["pairs"] == 4
    assert s["ambiguous_pairs"] == 0
    assert s["all_pairs"]["dist_km"]["median"] == pytest.approx(9.46, abs=0.01)
    assert s["time_resolution"] == {"a": "1 s", "b": "1 ms"}
    # Coverage comes from what each file declares: CWA's CatalogInfo and the
    # USGS query URL (which ended at 2015-12-31T00:00Z).
    cov = s["coverage"]
    assert cov["declared"] and cov["inferred_inputs"] == []
    assert cov["start"].startswith("2015-01-01T00:00:00") and cov["end"].startswith("2015-12-31T00:00:00")
    comp = s["completeness"]
    assert comp["b"]["match_rate"] == 1.0
    # One CWA ML>=6 quake has no partner because the USGS file was an M>=6
    # query; the report must warn about that instead of calling it a miss.
    assert comp["a"]["unmatched"] == ["cwa:cwa-catalog:20150323T101352"]
    assert [(w["kind"], w["input"], w["suggest_min_mag"]) for w in comp["warnings"]] == [("declared-floor", "b", 6.5)]
    md = (run_2015 / "report.md").read_text(encoding="utf-8")
    assert "CWA minus USGS" in md and "Warning" in md and "## Pairs" in md
    assert "whole seconds" in md
    assert len(s["sweep"]) == 12
    assert "Open Government Data License" in s["attribution"]
    assert (run_2015 / "ATTRIBUTION.txt").exists()


def test_cot_export_from_cli(run_2015, tmp_path, fixtures):
    usgs = tmp_path / "usgs.jsonl"
    assert main(["cot", str(usgs), "--out-dir", str(tmp_path / "cot")]) == 0
    assert len(list((tmp_path / "cot").glob("*.cot"))) == 156
