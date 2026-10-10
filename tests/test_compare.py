import math
from datetime import timedelta

import pytest
from conftest import T0, rec

from crosscheck.compare import Coverage, describe, overlap_coverage, pair_metrics, summarize
from crosscheck.match import match

KM_PER_DEG_LAT = 111.195


def test_residual_signs_are_a_minus_b():
    a = rec("cwa", "a", dt_s=1.5, lat=24.0, lon=121.6, depth=30, mag=5.0, mag_type="ml")
    b = rec("usgs", "b", dt_s=0.0, lat=24.0, lon=121.5, depth=25, mag=4.8, mag_type="mww")
    (p,) = match([a], [b]).pairs
    m = pair_metrics(p)
    assert m.dt_s == pytest.approx(1.5)
    assert m.d_depth_km == pytest.approx(5.0)  # A (CWA) deeper -> positive
    assert m.d_mag == pytest.approx(0.2)
    assert m.mag_pair == "ml-mww"
    assert m.azimuth_deg == pytest.approx(90.0, abs=0.1)  # A lies east of B
    assert m.d_east_km > 0 and abs(m.d_north_km) < 0.01
    assert math.hypot(m.d_east_km, m.d_north_km) == pytest.approx(m.dist_km)


def test_missing_depth_or_mag_gives_none():
    a = rec("cwa", "a", depth=None, mag=None)
    b = rec("usgs", "b")
    (p,) = match([a], [b]).pairs
    m = pair_metrics(p)
    assert m.d_depth_km is None and m.d_mag is None


def test_describe():
    s = describe([1.0, 2.0, 3.0, 4.0, 100.0, None])
    assert s["n"] == 5
    assert s["median"] == 3.0
    assert s["mad"] == 1.0  # robust to the outlier
    assert s["mean"] == pytest.approx(22.0)
    assert describe([]) == {"n": 0}
    assert describe([2.0])["std"] is None


def test_magnitude_never_pooled_across_types():
    a = [rec("cwa", "a1", mag=5.0), rec("cwa", "a2", dt_s=1000, mag=5.0)]
    b = [rec("usgs", "b1", mag=4.8, mag_type="mww"), rec("usgs", "b2", dt_s=1000, mag=4.5, mag_type="mb")]
    s = summarize(match(a, b), None)
    by_type = s["all_pairs"]["d_mag_by_type"]
    assert set(by_type) == {"ml-mww", "ml-mb"}
    assert by_type["ml-mww"]["mean"] == pytest.approx(0.2)
    assert by_type["ml-mb"]["mean"] == pytest.approx(0.5)


def test_mean_offset_vector():
    d = 5 / KM_PER_DEG_LAT
    a = [rec("cwa", f"a{i}", dt_s=100 * i, lat=24.0 - d) for i in range(3)]  # all 5 km south
    b = [rec("usgs", f"b{i}", dt_s=100 * i, lat=24.0) for i in range(3)]
    mo = summarize(match(a, b), None)["all_pairs"]["mean_offset"]
    assert mo["length_km"] == pytest.approx(5.0, abs=0.01)
    assert mo["azimuth_deg"] == pytest.approx(180.0, abs=0.1)


def test_completeness_inside_coverage_only():
    a = [
        rec("cwa", "matched", mag=5.0),
        rec("cwa", "missed", dt_s=500, mag=5.0),
        rec("cwa", "small", dt_s=900, mag=3.0),  # below cutoff
        rec("cwa", "outside", dt_s=700, lat=30.0, mag=6.0),  # outside bbox
    ]
    b = [rec("usgs", "b1", mag=4.9), rec("usgs", "b_late", dt_s=950, mag=3.5)]
    cov = Coverage(T0, T0 + timedelta(seconds=1000), (118.0, 20.0, 124.0, 27.0))
    comp = summarize(match(a, b), cov, min_mag=4.5)["completeness"]
    assert comp["a"]["events"] == 2 and comp["a"]["matched"] == 1
    assert comp["a"]["unmatched"] == ["cwa:cwa-test:missed"]
    assert comp["b"]["events"] == 1 and comp["b"]["match_rate"] == 1.0
    assert comp["warnings"] == []


def test_truncation_warning():
    a = [rec("cwa", "a1", mag=6.0), rec("cwa", "a2", dt_s=500, mag=6.1)]
    b = [rec("usgs", "b1", mag=6.0, mag_type="mww")]
    cov = overlap_coverage(a, b, (118.0, 20.0, 124.0, 27.0))
    comp = summarize(match(a, b), cov, min_mag=6.0)["completeness"]
    # Both inputs bottom out at M6.0, right at the cutoff.
    assert [w["input"] for w in comp["warnings"]] == ["a", "b"]
    assert comp["warnings"][1]["input_min_mag"] == 6.0

    many = [rec("usgs", "b1", mag=6.0, mag_type="mww"), rec("usgs", "tiny", dt_s=1, lat=26.0, mag=2.0)]
    comp = summarize(match(a, many), overlap_coverage(a, many, (118, 20, 124, 27)), min_mag=6.0)["completeness"]
    assert "b" not in [w["input"] for w in comp["warnings"]]


def test_overlap_coverage():
    a = [rec("cwa", "a1", dt_s=0), rec("cwa", "a2", dt_s=100)]
    b = [rec("usgs", "b1", dt_s=50), rec("usgs", "b2", dt_s=200)]
    cov = overlap_coverage(a, b, (118, 20, 124, 27))
    assert cov.start == T0 + timedelta(seconds=50)
    assert cov.end == T0 + timedelta(seconds=100)
    assert overlap_coverage(a, [rec("usgs", "late", dt_s=1000)], (118, 20, 124, 27)) is None
    assert overlap_coverage([], b, (118, 20, 124, 27)) is None
