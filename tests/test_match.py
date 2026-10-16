import pytest
from conftest import rec

from crosscheck.match import MatchConfig, match, sweep

KM_PER_DEG_LAT = 111.195  # on the 6371.0088 km sphere


def test_pairs_inside_gate():
    a = [rec("cwa", "a1", dt_s=2.0, lat=24.0)]
    b = [rec("usgs", "b1", dt_s=0.0, lat=24.0 + 10 / KM_PER_DEG_LAT)]
    r = match(a, b)
    assert len(r.pairs) == 1
    p = r.pairs[0]
    assert p.dt_s == pytest.approx(2.0)
    assert p.dist_km == pytest.approx(10.0, abs=0.01)
    assert not r.unmatched_a and not r.unmatched_b


@pytest.mark.parametrize(
    "dt_s,dlat_km,matched",
    [
        (16.0, 0, True),  # edges are inclusive
        (16.5, 0, False),
        (0, 99.9, True),
        (0, 100.5, False),
    ],
)
def test_gate_edges(dt_s, dlat_km, matched):
    a = [rec("cwa", "a", dt_s=dt_s, lat=24.0 + dlat_km / KM_PER_DEG_LAT)]
    b = [rec("usgs", "b", lat=24.0)]
    assert (len(match(a, b).pairs) == 1) is matched


def test_gate_edges_are_exact_for_millisecond_times():
    from datetime import datetime, timezone

    from crosscheck.model import QuakeRecord

    def at(source, t):
        return QuakeRecord(source, f"{source}-t", source, t, 24.0, 121.5, 10.0, 4.0, "ml")

    a = at("cwa", datetime(2017, 3, 23, 20, 43, 29, 141000, tzinfo=timezone.utc))
    b = at("usgs", datetime(2017, 3, 23, 20, 43, 27, 120000, tzinfo=timezone.utc))
    assert len(match([a], [b], MatchConfig(time_window_s=2.021)).pairs) == 1  # dt is exactly the window
    # Exactly 16 s apart where float timestamps cross 2**30 s (2004-01-10T13:37:04Z).
    b = at("usgs", datetime(2004, 1, 10, 13, 36, 55, 123000, tzinfo=timezone.utc))
    a = at("cwa", datetime(2004, 1, 10, 13, 37, 11, 123000, tzinfo=timezone.utc))
    (p,) = match([a], [b]).pairs
    assert p.dt_s == 16.0


def test_magnitude_is_not_a_gate():
    a = [rec("cwa", "a", mag=6.5, mag_type="ml")]
    b = [rec("usgs", "b", mag=5.6, mag_type="mww")]
    assert len(match(a, b).pairs) == 1


def test_one_to_one_takes_the_closer_candidate():
    b = [rec("usgs", "b")]
    a = [rec("cwa", "near", dt_s=1), rec("cwa", "far", dt_s=10)]
    r = match(a, b)
    assert [(p.a.source_id, p.b.source_id) for p in r.pairs] == [("near", "b")]
    assert [x.source_id for x in r.unmatched_a] == ["far"]


def test_global_assignment_beats_greedy():
    # a1-b1 is the single closest pair, but a2 can only reach b1. Greedy-by-cost
    # would take a1-b1 and leave a2 unmatched; a1 can also reach b2, so the
    # one-to-one assignment matches both.
    b = [rec("usgs", "b1", dt_s=0), rec("usgs", "b2", dt_s=14)]
    a = [rec("cwa", "a1", dt_s=1), rec("cwa", "a2", dt_s=-12)]
    r = match(a, b)
    got = {(p.a.source_id, p.b.source_id) for p in r.pairs}
    assert got == {("a1", "b2"), ("a2", "b1")}


def test_ambiguity_flag():
    b = [rec("usgs", "b")]
    a = [rec("cwa", "a1", dt_s=4.0), rec("cwa", "a2", dt_s=-4.5)]
    r = match(a, b)
    assert len(r.pairs) == 1 and r.pairs[0].ambiguous
    assert r.pairs[0].runner_up_cost is not None

    clear = match([rec("cwa", "a1", dt_s=1.0), rec("cwa", "a2", dt_s=-12.0)], b)
    assert not clear.pairs[0].ambiguous


def test_empty_and_invalid_inputs():
    assert match([], []).pairs == []
    r = match([rec("cwa", "a")], [])
    assert len(r.unmatched_a) == 1
    with pytest.raises(ValueError):
        match([], [], MatchConfig(time_window_s=0))


def test_sweep_counts_grow_with_window():
    b = [rec("usgs", "b1"), rec("usgs", "b2", dt_s=600)]
    a = [rec("cwa", "a1", dt_s=20), rec("cwa", "a2", dt_s=600, lat=24.0 + 120 / KM_PER_DEG_LAT)]
    rows = {(r["time_window_s"], r["dist_window_km"]): r["pairs"] for r in sweep(a, b)}
    assert rows[(16, 50)] == 0
    assert rows[(30, 50)] == 1
    assert rows[(30, 150)] == 2
