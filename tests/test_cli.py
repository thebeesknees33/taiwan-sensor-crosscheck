import json
from datetime import datetime, timezone

import argparse
import pytest

from crosscheck import cli
from crosscheck.http import Fetched, save_raw


def test_argument_validation():
    with pytest.raises(argparse.ArgumentTypeError):
        cli._years("2017-2015")
    with pytest.raises(argparse.ArgumentTypeError):
        cli._years("20x5")
    assert cli._years("2015-2017,2020") == {2015, 2016, 2017, 2020}
    for bad in ("nan,20,124,27", "118,20,124", "124,20,118,27", "118,20,200,27"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._bbox(bad)
    with pytest.raises(SystemExit):
        cli.main(["compare", "a.jsonl", "b.jsonl", "--time-window", "0"])


@pytest.mark.parametrize(
    "arg,expected",
    [
        ("localhost", ("localhost", 8088)),
        ("tak.lan:8089", ("tak.lan", 8089)),
        ("::1", ("::1", 8088)),
        ("[::1]:9000", ("::1", 9000)),
        ("[fe80::1]", ("fe80::1", 8088)),
    ],
)
def test_send_address_parsing(arg, expected):
    assert cli._hostport(arg) == expected


@pytest.mark.parametrize("bad", ["localhost:abc", "localhost:99999", "localhost:0", "[::1", ":8088"])
def test_send_address_errors(bad):
    with pytest.raises(argparse.ArgumentTypeError):
        cli._hostport(bad)


def test_bad_send_address_fails_before_writing_files(tmp_path, fixtures):
    out = tmp_path / "u.jsonl"
    cli.main(["parse", "usgs", str(fixtures / "usgs" / "fdsn-2015-m6plus.geojson"), "--out", str(out)])
    with pytest.raises(SystemExit):
        cli.main(["cot", str(out), "--out-dir", str(tmp_path / "cot"), "--send", "host:abc"])
    assert not (tmp_path / "cot").exists()


def test_compare_rejects_reversed_window(tmp_path, fixtures):
    out = tmp_path / "u.jsonl"
    cli.main(["parse", "usgs", str(fixtures / "usgs" / "fdsn-2015-m6plus.geojson"), "--out", str(out)])
    rc = cli.main(["compare", str(out), str(out), "--start", "2015-09-01", "--end", "2015-06-01",
                   "--out-dir", str(tmp_path / "c")])
    assert rc == 1


def test_parse_skips_sidecars_and_names_bad_files(tmp_path, fixtures, capsys):
    raw = tmp_path / "raw"
    body = (fixtures / "cwa" / "E-A0015-001.zip").read_bytes()
    save_raw(Fetched("https://s3.test/E-A0015-001.zip", 200, body, {}, datetime.now(timezone.utc)), raw, "E-A0015-001.zip")
    files = sorted(str(p) for p in raw.iterdir())
    assert any(f.endswith(".meta.json") for f in files)
    out = tmp_path / "r.jsonl"
    assert cli.main(["parse", "cwa", *files, "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 16
    assert "skipping 1 sidecar" in capsys.readouterr().err

    bad = tmp_path / "notes.json"
    bad.write_text("{}", encoding="utf-8")
    assert cli.main(["parse", "cwa", str(bad), "--out", str(tmp_path / "x.jsonl")]) == 1
    assert "notes.json" in capsys.readouterr().err


def fake_fetch(files):
    def fetch(url, **kw):
        name = url.rsplit("/", 1)[-1].split("?")[0]
        return Fetched(url, 200, files[name], {}, datetime.now(timezone.utc))

    return fetch


def test_fetch_cwa_catalog_writes_coverage_and_warns_missing_years(tmp_path, fixtures, monkeypatch, capsys):
    import zipfile

    from crosscheck.sources import cwa

    zpath = tmp_path / "E-A0073-002.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("CWA-EQ-Catalog-2015.xml", (fixtures / "cwa" / "CWA-EQ-Catalog-2015.xml").read_bytes())
    files = {"E-A0073-002.zip": zpath.read_bytes(), "E-A0073-001.json": (fixtures / "cwa" / "E-A0073-001.json").read_bytes()}
    monkeypatch.setattr(cwa, "fetch", fake_fetch(files))
    out = tmp_path / "cwa.jsonl"
    assert cli.main(["fetch", "cwa", "--product", "catalog", "--years", "2015-2016", "--out", str(out)]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1626
    info = json.loads((tmp_path / "cwa.info.json").read_text(encoding="utf-8"))
    assert info["coverage"]["declared"] and info["coverage"]["segments"][0]["label"] == "CWA-EQ-Catalog-2015"
    assert "Open Government Data License" in info["attribution"]
    assert "no records for year(s) 2016" in capsys.readouterr().err


def test_fetch_usgs_records_query_coverage(tmp_path, fixtures, monkeypatch):
    from crosscheck.sources import usgs

    body = (fixtures / "usgs" / "fdsn-2015-m6plus.geojson").read_bytes()

    def fetch(url, params=None, **kw):
        if url.endswith("count"):
            return Fetched(url, 200, b'{"count": 156, "maxAllowed": 20000}', {}, datetime.now(timezone.utc))
        return Fetched(url, 200, body, {}, datetime.now(timezone.utc))

    monkeypatch.setattr(usgs, "fetch", fetch)
    monkeypatch.setattr(usgs.time, "sleep", lambda s: None)
    out = tmp_path / "usgs.jsonl"
    assert cli.main(["fetch", "usgs", "--start", "2015-01-01", "--end", "2016-01-01", "--min-mag", "6", "--out", str(out)]) == 0
    seg = json.loads((tmp_path / "usgs.info.json").read_text(encoding="utf-8"))["coverage"]["segments"][0]
    assert seg["bbox"] == [117.0, 19.0, 125.0, 28.0] and seg["min_mag"] == 6.0
    assert seg["start"] == "2015-01-01T00:00:00Z" and seg["end"] == "2016-01-01T00:00:00Z"
    assert cli.main(["fetch", "usgs", "--start", "2016-01-01", "--end", "2015-01-01", "--out", str(out)]) == 1


def test_report_prints_on_a_console_without_cjk(tmp_path, fixtures, monkeypatch):
    # The CWA attribution contains Chinese; a Windows cp1252 console must not crash.
    import io
    import sys

    u, c = tmp_path / "u.jsonl", tmp_path / "c.jsonl"
    cli.main(["parse", "usgs", str(fixtures / "usgs" / "fdsn-2015-m6plus.geojson"), "--out", str(u)])
    cli.main(["parse", "cwa", str(fixtures / "cwa" / "CWA-EQ-Catalog-2015.xml"), "--out", str(c)])
    console = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", console)
    assert cli.main(["compare", str(c), str(u), "--out-dir", str(tmp_path / "out")]) == 0
    console.flush()
    assert b"CWA vs USGS" in console.buffer.getvalue()
    # The file itself keeps the exact text.
    assert "中央氣象署" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_report_never_prints_negative_zero():
    from crosscheck.report import _f

    assert _f(-2.220446049250313e-16) == "0.00"
    assert _f(-0.004) == "0.00" and _f(-0.006) == "-0.01"
    assert _f(-1e-17, sign=True) == "+0.00"
    assert _f(None) == ""
