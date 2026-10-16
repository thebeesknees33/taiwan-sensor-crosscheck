import math
from datetime import timedelta

import pytest
from conftest import T0, rec

from crosscheck.compare import describe, pair_metrics, resolve_coverage, summarize, time_resolution
from crosscheck.coverage import Coverage, Segment
from crosscheck.match import match

KM_PER_DEG_LAT = 111.195
BOX = (118.0, 20.0, 124.0, 27.0)


def cov(start_s, end_s, bbox=BOX, min_mag=None, label="test"):
    return Coverage([Segment(T0 + timedelta(seconds=start_s), T0 + timedelta(seconds=end_s), bbox, min_mag, label)])


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
    (p,) = match([rec("cwa", "a", depth=None, mag=None)], [rec("usgs", "b")]).pairs
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
    by_type = summarize(match(a, b), None)["all_pairs"]["d_mag_by_type"]
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
        rec("cwa", "outside", dt_s=700, lat=30.0, mag=6.0),  # outside the region
    ]
    b = [rec("usgs", "b1", mag=4.9), rec("usgs", "b_late", dt_s=950, mag=3.5)]
    joint = cov(0, 1000)
    comp = summarize(match(a, b), joint, 4.5, joint, joint)["completeness"]
    assert comp["a"]["events"] == 2 and comp["a"]["matched"] == 1
    assert comp["a"]["unmatched"] == ["cwa:cwa-test:missed"]
    assert comp["a"]["unmatched_outside_overlap"] == 1
    assert comp["b"]["events"] == 1 and comp["b"]["match_rate"] == 1.0


def test_pair_counts_on_both_sides_at_the_window_edge():
    # The CWA event is 0.4 s before the window starts but its USGS partner is
    # inside: the pair must count for both catalogs, not split.
    a = [rec("cwa", "edge", dt_s=-0.4, mag=5.0), rec("cwa", "late", dt_s=500, mag=5.0)]
    b = [rec("usgs", "edge", dt_s=0.0, mag=5.0), rec("usgs", "late", dt_s=500.2, mag=5.0)]
    joint = cov(0, 1000)
    comp = summarize(match(a, b), joint, 4.5, joint, joint)["completeness"]
    assert comp["a"]["matched"] == comp["b"]["matched"] == 2


def test_misses_at_the_end_are_counted_with_declared_coverage():
    # USGS was queried for the whole span but its last quake is early; a CWA
    # quake after that is a real miss and must be counted.
    a = [rec("cwa", "jan", dt_s=10, mag=6.0), rec("cwa", "dec", dt_s=900, mag=6.0)]
    b = [rec("usgs", "jan", dt_s=11, mag=6.0)]
    A_cov, B_cov, joint = resolve_coverage(a, b, cov(0, 1000), cov(0, 1000), BOX)
    comp = summarize(match(a, b), joint, 6.5, A_cov, B_cov)["completeness"]
    assert comp["a"]["events"] == 0  # cutoff 6.5 excludes both
    comp = summarize(match(a, b), joint, 6.0, A_cov, B_cov)["completeness"]
    assert comp["a"]["unmatched"] == ["cwa:cwa-test:dec"]

    # Without declared coverage the span is inferred from the events, and the
    # December miss falls outside it; the summary says coverage was inferred.
    A_cov, B_cov, joint = resolve_coverage(a, b, None, None, BOX)
    s = summarize(match(a, b), joint, 6.0, A_cov, B_cov)
    assert s["coverage"]["inferred_inputs"] == ["a", "b"]
    assert s["completeness"]["a"]["unmatched_outside_overlap"] == 1


def test_declared_floor_warning():
    a = [rec("cwa", "a1", mag=6.0), rec("cwa", "a2", dt_s=500, mag=3.0)]
    b = [rec("usgs", "b1", mag=6.0, mag_type="mww")]
    b_cov = cov(0, 1000, min_mag=6.0, label="USGS FDSN query")
    a_cov = cov(0, 1000, min_mag=3.0, label="CWA catalog")
    joint = a_cov.intersect(b_cov)
    w = summarize(match(a, b), joint, 6.0, a_cov, b_cov)["completeness"]["warnings"]
    assert [(x["kind"], x["input"], x["suggest_min_mag"]) for x in w] == [("declared-floor", "b", 6.5)]
    assert summarize(match(a, b), joint, 6.5, a_cov, b_cov)["completeness"]["warnings"] == []
    # No cutoff at all: CWA's events go down to 3.0, far below USGS's 6.0 limit.
    w = summarize(match(a, b), joint, None, a_cov, b_cov)["completeness"]["warnings"]
    assert [x["input"] for x in w] == ["b"]


def test_observed_floor_warning_without_declared_coverage():
    a = [rec("cwa", "a1", mag=4.2), rec("cwa", "a2", dt_s=500, mag=3.0)]
    b = [rec("usgs", "b1", mag=4.0, mag_type="mb"), rec("usgs", "b2", dt_s=700, mag=5.0, mag_type="mb")]
    A_cov, B_cov, joint = resolve_coverage(a, b, None, None, BOX)
    w = summarize(match(a, b), joint, None, A_cov, B_cov)["completeness"]["warnings"]
    assert [(x["kind"], x["input"], x["floor"]) for x in w] == [("observed-floor", "b", 4.0)]
    assert summarize(match(a, b), joint, 4.5, A_cov, B_cov)["completeness"]["warnings"] == []


def test_resolve_coverage_intersections():
    a_cov = Coverage(
        [
            Segment(T0, T0 + timedelta(days=1), (118, 20, 124, 27), 3.0, "y1"),
            Segment(T0 + timedelta(days=1), T0 + timedelta(days=2), (119, 21, 123, 26), 3.0, "y2"),
        ]
    )
    b_cov = cov(0, 2 * 86400, (117, 19, 125, 28), None, "usgs")
    _, _, joint = resolve_coverage([], [], a_cov, b_cov, BOX)
    assert [s.bbox for s in joint.segments] == [(118, 20, 124, 27), (119, 21, 123, 26)]
    # A quake at 123.5E on day 2 is outside that year's declared region.
    assert not joint.contains(rec("usgs", "x", dt_s=1.5 * 86400, lon=123.5))
    assert joint.contains(rec("usgs", "x", dt_s=0.5 * 86400, lon=123.5))
    # Narrowing from the command line.
    _, _, narrow = resolve_coverage([], [], a_cov, b_cov, BOX, bbox=(120, 22, 122, 25), start=T0 + timedelta(hours=1))
    assert all(s.bbox == (120, 22, 122, 25) for s in narrow.segments)
    assert narrow.start == T0 + timedelta(hours=1)
    # No overlap at all.
    _, _, none = resolve_coverage([], [], a_cov, cov(10 * 86400, 11 * 86400), BOX)
    assert none is None


def test_time_resolution():
    whole = [rec("cwa", "a", dt_s=1), rec("cwa", "b", dt_s=2)]
    ms = [rec("usgs", "c", dt_s=1.25)]
    assert time_resolution(whole) == "1 s"
    assert time_resolution(ms) == "1 ms"
    assert time_resolution([rec("x", "d", dt_s=0.0000015)]) == "sub-ms"
    assert time_resolution([]) is None
