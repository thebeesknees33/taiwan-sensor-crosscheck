import json
from datetime import datetime, timezone

import pytest

from crosscheck.sources import usgs


def load(fixtures, name):
    return usgs.parse_geojson((fixtures / "usgs" / name).read_bytes())


def by_id(records):
    return {r.source_id: r for r in records}


def test_fdsn_2015_taiwan_event_fields(fixtures):
    recs = by_id(load(fixtures, "fdsn-2015-m6plus.geojson"))
    assert len(recs) == 156
    r = recs["us200027ps"]
    # time 1429494178380 ms
    assert r.origin_time == datetime(2015, 4, 20, 1, 42, 58, 380000, tzinfo=timezone.utc)
    assert (r.lat, r.lon, r.depth_km) == (24.2026, 122.3158, 29.0)
    assert (r.mag, r.mag_type, r.mag_type_raw) == (6.4, "mww", "mww")
    assert r.status == "reviewed"
    assert r.extra["sources"] == ["pt", "at", "us", "gcmt"]
    assert r.extra["place"] == "64km SE of Su'ao, Taiwan"


def test_taiwan_region_event_can_be_labelled_japan(fixtures):
    r = by_id(load(fixtures, "fdsn-2015-m6plus.geojson"))["us200027ru"]
    assert "Japan" in r.extra["place"]
    assert 118 <= r.lon <= 124 and 20 <= r.lat <= 27  # selection must use coordinates


def test_null_magnitude_and_negative_depth(fixtures):
    recs = by_id(load(fixtures, "fdsn-2018-null-mag-negative-depth.geojson"))
    assert recs["nc72955525"].mag is None
    assert recs["nc72955525"].mag_type is None
    assert recs["nc72955530"].depth_km == -0.68
    assert recs["nc72955530"].mag_type == "md"


def test_null_depth(fixtures):
    recs = load(fixtures, "fdsn-1904-1912-null-depth.geojson")
    assert len(recs) == 85
    assert sum(r.depth_km is None for r in recs) == 25
    assert all(r.origin_time.year < 1970 for r in recs)  # negative epoch milliseconds


def test_summary_feed(fixtures):
    recs = load(fixtures, "summary-all-day-2018.geojson")
    assert len(recs) == 188
    assert {r.status for r in recs} == {"automatic", "reviewed"}


def test_single_feature_and_bad_input(fixtures):
    doc = json.loads((fixtures / "usgs" / "fdsn-2015-m6plus.geojson").read_text())
    one = usgs.parse_geojson(doc["features"][0])
    assert len(one) == 1 and one[0].source_id == doc["features"][0]["id"]
    with pytest.raises(ValueError):
        usgs.parse_geojson({"type": "Polygon"})


# ------------------------------------------------------------ fetching (no network)


class FakeResp:
    def __init__(self, body, url="https://example.test/", status=200):
        self.content = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status_code = status
        self.headers = {"Date": "Sat, 10 Oct 2026 00:00:00 GMT"}
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Answers /count by time window and /query with a slice of a real response."""

    def __init__(self, features, max_allowed):
        self.features = features
        self.max_allowed = max_allowed
        self.calls = []

    def _in(self, params):
        s = datetime.fromisoformat(params["starttime"]).replace(tzinfo=timezone.utc).timestamp() * 1000
        e = datetime.fromisoformat(params["endtime"]).replace(tzinfo=timezone.utc).timestamp() * 1000
        return [f for f in self.features if s <= f["properties"]["time"] <= e]

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        hits = self._in(params)
        if url.endswith("count"):
            return FakeResp({"count": len(hits), "maxAllowed": self.max_allowed}, url)
        return FakeResp({"type": "FeatureCollection", "features": hits}, url)


def test_fetch_splits_windows_over_the_limit(fixtures, monkeypatch, tmp_path):
    monkeypatch.setattr(usgs.time, "sleep", lambda s: None)
    doc = json.loads((fixtures / "usgs" / "fdsn-2015-m6plus.geojson").read_text())
    sess = FakeSession(doc["features"], max_allowed=40)
    recs = usgs.fetch_events(
        datetime(2015, 1, 1), datetime(2016, 1, 1), bbox=(-180, -90, 180, 90), raw_dir=tmp_path, session=sess
    )
    assert len(recs) == 156
    assert len({r.source_id for r in recs}) == 156
    assert recs == sorted(recs, key=lambda r: r.origin_time)
    queries = [c for c in sess.calls if c[0].endswith("query")]
    assert len(queries) >= 4  # 156 events / 40 per request
    url, params, headers = queries[0]
    assert params["format"] == "geojson" and params["eventtype"] == "earthquake"
    assert params["orderby"] == "time-asc"
    assert "taiwan-sensor-crosscheck" in headers["User-Agent"]
    assert list(tmp_path.glob("*.meta.json"))  # raw responses kept for audit


def test_fetch_passes_bbox_and_min_mag(monkeypatch):
    monkeypatch.setattr(usgs.time, "sleep", lambda s: None)
    sess = FakeSession([], max_allowed=20000)
    assert usgs.fetch_events(datetime(2026, 1, 1), datetime(2026, 2, 1), min_mag=4.5, session=sess) == []
    params = sess.calls[0][1]
    assert (params["minlongitude"], params["minlatitude"], params["maxlongitude"], params["maxlatitude"]) == (
        118.0, 20.0, 124.0, 27.0,
    )
    assert params["minmagnitude"] == 4.5
