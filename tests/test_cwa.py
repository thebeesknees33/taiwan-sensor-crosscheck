import json
from datetime import datetime, timezone

import pytest

from crosscheck.sources import cwa


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_origin_time_both_formats_are_taiwan_local():
    # Older REST records have no offset; they are Taiwan local time (UTC+8).
    assert cwa.parse_origin_time("2026-04-05 01:14:58") == utc(2026, 4, 4, 17, 14, 58)
    assert cwa.parse_origin_time("2026-04-05T05:23:59+08:00") == utc(2026, 4, 4, 21, 23, 59)
    assert cwa.parse_origin_time(" 2026-01-01T00:00:00Z ") == utc(2026, 1, 1)


def test_significant_reports_zip(fixtures):
    recs = cwa.parse_file(fixtures / "cwa" / "E-A0015-001.zip")
    assert len(recs) == 16
    assert {r.product for r in recs} == {"cwa-report-significant"}
    assert {r.mag_type for r in recs} == {"ml"}
    assert {r.mag_type_raw for r in recs} == {"芮氏規模"}
    r = next(r for r in recs if r.extra["earthquake_no"] == "115068")
    assert r.origin_time == utc(2026, 10, 6, 8, 41, 8)
    assert (r.lat, r.lon, r.depth_km, r.mag) == (22.29, 120.11, 34.1, 4.5)
    assert r.extra["issue_time"] == "2026-10-06T16:44:33+08:00"


def test_small_reports_have_unique_ids_despite_shared_number(fixtures):
    recs = cwa.parse_file(fixtures / "cwa" / "E-A0016-001.zip")
    assert len(recs) == 16
    assert {r.extra["earthquake_no"] for r in recs} == {"115000"}
    assert len({r.source_id for r in recs}) == 16
    assert {r.product for r in recs} == {"cwa-report-small"}


def test_english_report_matches_chinese(fixtures):
    zh = {r.source_id: r for r in cwa.parse_file(fixtures / "cwa" / "E-A0015-001.zip")}
    (en,) = cwa.parse_file(fixtures / "cwa" / "CWA-EQ115068-2026-1006-164108-OD_eng.xml")
    assert en.mag_type_raw == "ML" and en.mag_type == "ml"
    z = zh[en.source_id]  # same language-independent id
    assert (en.origin_time, en.lat, en.lon, en.depth_km, en.mag) == (z.origin_time, z.lat, z.lon, z.depth_km, z.mag)


def test_rest_response(fixtures):
    recs = cwa.parse_file(fixtures / "cwa" / "rest-E-A0015-001-kuotunyu.json")
    assert len(recs) == 5
    r = next(r for r in recs if r.extra["earthquake_no"] == "115048")
    assert r.product == "cwa-report-significant"  # from result.resource_id
    assert r.origin_time == utc(2026, 7, 1, 23, 6, 6)
    assert (r.lat, r.lon, r.depth_km, r.mag, r.mag_type) == (23.64, 121.48, 5.0, 4.0, "ml")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("rest-record-115031-kiang.json", utc(2026, 4, 4, 17, 14, 58)),  # old naive format
        ("rest-record-115032-kiang.json", utc(2026, 4, 4, 21, 23, 59)),  # new ISO format
    ],
)
def test_rest_records_old_and_new_time_formats(fixtures, name, expected):
    eq = json.loads((fixtures / "cwa" / name).read_text(encoding="utf-8"))
    r = cwa._report_record(eq, "cwa-report-significant", None, None)
    assert r.origin_time == expected


def test_rest_failure_is_an_error():
    with pytest.raises(ValueError):
        cwa.parse_rest_json({"success": "false", "result": {}, "records": {}})
    with pytest.raises(ValueError, match="pre-2023"):
        cwa.parse_rest_json({"success": "true", "records": {"earthquake": []}})


def test_catalog_json(fixtures):
    recs = cwa.parse_file(fixtures / "cwa" / "E-A0073-001.json")
    assert len(recs) == 1507  # CatalogInfo RecordNumber
    r = recs[0]
    assert r.product == "cwa-catalog"
    assert r.origin_time == utc(2026, 1, 1, 0, 16, 17)
    assert (r.lat, r.lon, r.depth_km, r.mag, r.mag_type) == (22.369, 119.399, 62.4, 3.4, "ml")
    assert r.status == "F"
    assert r.extra["quality"] == "D"
    assert (r.extra["gap"], r.extra["rms"], r.extra["erh"], r.extra["erz"]) == (216.0, 0.45, 0.5, 0.6)
    assert not any(k.endswith("_unit") for k in r.extra)  # units were the expected ones
    assert len({x.source_id for x in recs}) == len(recs)
    assert min(x.mag for x in recs) >= 3.0


def test_catalog_xml_with_leading_spaces(fixtures):
    recs = cwa.parse_file(fixtures / "cwa" / "CWA-EQ-Catalog-2015.xml")
    assert len(recs) == 1626  # CatalogInfo RecordNumber
    r = recs[0]
    assert r.origin_time == utc(2015, 1, 1, 3, 54, 51)
    assert (r.lat, r.lon, r.depth_km) == (24.264, 121.658, 29.0)
    assert r.mag == 3.0 and r.extra["station_number"] == 81  # "<LocalMagnitude> 3.0", "<StationNumber> 81"
    assert r.extra["erh"] == 0.2 and r.extra["quality"] == "C"


def test_catalog_zip_year_filter(fixtures, tmp_path):
    import zipfile

    src = (fixtures / "cwa" / "CWA-EQ-Catalog-2015.xml").read_bytes()
    zpath = tmp_path / "E-A0073-002.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("CWA-EQ-Catalog-2015.xml", src)
        z.writestr("file.csv", "CWA-EQ-Catalog-2015.xml,2015\n")
    assert len(cwa.parse_file(zpath)) == 1626
    assert cwa.parse_catalog_zip(zpath.read_bytes(), years={2016}) == []


def test_rest_fetch_requires_key_and_redacts_it(monkeypatch, tmp_path, fixtures):
    monkeypatch.delenv("CWA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CWA_API_KEY"):
        cwa.fetch_reports_rest()

    body = (fixtures / "cwa" / "rest-E-A0015-001-kuotunyu.json").read_bytes()

    class Resp:
        status_code = 200
        headers = {}
        content = body
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001?Authorization=CWA-SECRET&format=JSON"

        def raise_for_status(self):
            pass

    class Sess:
        def get(self, url, params=None, headers=None, timeout=None):
            self.params = params
            return Resp()

    s = Sess()
    recs = cwa.fetch_reports_rest(api_key="CWA-SECRET", raw_dir=tmp_path, session=s)
    assert len(recs) == 5 and s.params["Authorization"] == "CWA-SECRET"
    meta = next(tmp_path.glob("*.meta.json")).read_text()
    assert "CWA-SECRET" not in meta and "REDACTED" in meta
