from datetime import timedelta

from conftest import T0, rec

from crosscheck.coverage import Coverage, Segment, inferred, info_path, merge, read_coverage, write_info

BOX = (118.0, 20.0, 124.0, 27.0)


def seg(a, b, bbox=BOX, m=None):
    return Segment(T0 + timedelta(seconds=a), T0 + timedelta(seconds=b), bbox, m)


def test_intersection_and_touching_spans():
    s = seg(0, 100, BOX, 3.0).intersect(seg(50, 200, (119, 21, 125, 28), 6.0))
    assert (s.start, s.end) == (T0 + timedelta(seconds=50), T0 + timedelta(seconds=100))
    assert s.bbox == (119, 21, 124, 27) and s.min_mag == 6.0
    assert seg(0, 100).intersect(seg(100, 200)) is None  # consecutive years only touch
    assert seg(0, 100).intersect(seg(300, 400)) is None
    assert seg(0, 100).intersect(seg(0, 100, (130, 30, 140, 40))) is None
    assert seg(50, 50).intersect(seg(0, 100)) is not None  # a genuine single instant survives


def test_inferred_ignores_events_outside_the_region():
    recs = [rec("x", "a", dt_s=10), rec("x", "b", dt_s=500), rec("x", "far", dt_s=9000, lat=40.0)]
    c = inferred(recs, BOX, "A")
    assert not c.declared and c.end == T0 + timedelta(seconds=500)
    assert inferred([rec("x", "far", lat=40.0)], BOX, "A") is None


def test_merge_requires_every_file_declared():
    a, b = Coverage([seg(0, 10)]), Coverage([seg(20, 30)])
    assert len(merge([a, b]).segments) == 2
    assert merge([a, None]) is None


def test_sidecar_roundtrip(tmp_path):
    out = tmp_path / "x.jsonl"
    cov = Coverage([seg(0, 10, BOX, 3.0)])
    path = write_info(out, [rec("cwa", "a")], cov)
    assert path == info_path(out) == tmp_path / "x.info.json"
    back = read_coverage(out)
    assert back.segments == cov.segments and back.declared
    assert "Open Government Data License" in path.read_text(encoding="utf-8")
    assert read_coverage(tmp_path / "missing.jsonl") is None
