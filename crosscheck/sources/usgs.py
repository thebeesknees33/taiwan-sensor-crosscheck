"""USGS ComCat earthquakes via the FDSN event web service (GeoJSON).

Format notes, all checked against real saved responses (see docs/SOURCES.md):
- geometry.coordinates is [lon, lat, depth_km]; depth can be negative or null.
- properties.time / updated are signed epoch milliseconds, UTC.
- mag and magType can be null; magType case varies ("mww", "Mfa").
- ids / sources / types are comma lists with leading and trailing commas.
- 'place' text changes over time and can name Japan for Taiwan-region
  events, so selection is always by coordinates.
- 'updated' is the last update, not first publication, so it is no use for
  latency; we record our own retrieved_at instead.

Licence: USGS-authored data is a US Government work (public domain in the
US, per USGS policy; not checked against a primary terms page here). ComCat
also carries solutions authored by other agencies (e.g. gcmt, iscgem and
regional networks), whose terms were not checked.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlsplit

import requests

from ..coverage import GLOBAL_BBOX, Coverage, Segment
from ..http import fetch
from ..model import QuakeRecord, normalize_mag_type
from . import TAIWAN_FETCH_BBOX

FDSN_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/"
MAX_PER_QUERY = 20000  # ComCat's maxAllowed per request
MIN_SECONDS_BETWEEN_REQUESTS = 1.0


def parse_geojson(
    data: bytes | str | dict,
    retrieved_at: Optional[datetime] = None,
    earthquakes_only: bool = True,
) -> list[QuakeRecord]:
    """Parse a ComCat FeatureCollection (summary feed or FDSN query) or a single Feature."""
    doc = json.loads(data) if isinstance(data, (bytes, str)) else data
    if doc.get("type") == "Feature":
        features = [doc]
    elif doc.get("type") == "FeatureCollection":
        features = doc.get("features") or []
    else:
        raise ValueError("not a GeoJSON Feature or FeatureCollection")

    out = []
    for f in features:
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        p = f.get("properties") or {}
        if earthquakes_only and p.get("type") not in (None, "earthquake"):
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2 or coords[0] is None or coords[1] is None or p.get("time") is None:
            continue
        depth = coords[2] if len(coords) > 2 else None
        out.append(
            QuakeRecord(
                source="usgs",
                product="usgs-comcat",
                source_id=str(f.get("id")),
                origin_time=_from_ms(p["time"]),
                lat=float(coords[1]),
                lon=float(coords[0]),
                depth_km=float(depth) if depth is not None else None,
                mag=float(p["mag"]) if p.get("mag") is not None else None,
                mag_type=normalize_mag_type(p.get("magType")),
                mag_type_raw=p.get("magType"),
                status=p.get("status"),
                url=p.get("url"),
                retrieved_at=retrieved_at,
                extra={
                    "ids": _split_list(p.get("ids")),
                    "sources": _split_list(p.get("sources")),
                    "net": p.get("net"),
                    "updated": _iso_or_none(p.get("updated")),
                    "place": p.get("place"),
                    "event_type": p.get("type"),
                    "nst": p.get("nst"),
                    "gap": p.get("gap"),
                    "rms": p.get("rms"),
                    "dmin": p.get("dmin"),
                },
            )
        )
    return out


def coverage_from_geojson(data: bytes | str | dict) -> Optional[Coverage]:
    """Coverage of a saved FDSN query response, read from its metadata.url.

    Returns None when the response does not say what was asked for (summary
    feeds, single events, radius queries).
    """
    doc = json.loads(data) if isinstance(data, (bytes, str)) else data
    url = (doc.get("metadata") or {}).get("url") or ""
    parts = urlsplit(url)
    if not parts.path.endswith("/fdsnws/event/1/query"):
        return None
    q = {k: v[-1] for k, v in parse_qs(parts.query).items()}
    if "starttime" not in q or "endtime" not in q:
        return None
    if any(k in q for k in ("latitude", "longitude", "maxradius", "maxradiuskm", "lat", "lon")):
        return None  # circular region: not representable as a box
    box_keys = ("minlongitude", "minlatitude", "maxlongitude", "maxlatitude")
    if all(k in q for k in box_keys):
        bbox = tuple(float(q[k]) for k in box_keys)
    elif any(k in q for k in box_keys):
        return None
    else:
        bbox = GLOBAL_BBOX
    min_mag = float(q["minmagnitude"]) if "minmagnitude" in q else None
    seg = Segment(_parse_query_time(q["starttime"]), _parse_query_time(q["endtime"]), bbox, min_mag, "USGS FDSN query")
    return Coverage([seg])


def fetch_events(
    start: datetime,
    end: datetime,
    bbox: tuple[float, float, float, float] = TAIWAN_FETCH_BBOX,
    min_mag: Optional[float] = None,
    raw_dir: Optional[Path] = None,
    session: Optional[requests.Session] = None,
) -> list[QuakeRecord]:
    """Query ComCat for earthquakes in a time window and bounding box.

    Windows holding more than ComCat's per-request limit are split in half
    until each piece fits. Results are de-duplicated by event id.
    """
    sess = session or requests.Session()
    seen: dict[str, QuakeRecord] = {}
    for rec in _fetch_window(_utc(start), _utc(end), bbox, min_mag, raw_dir, sess):
        seen.setdefault(rec.source_id, rec)
    return sorted(seen.values(), key=lambda r: r.origin_time)


def query_coverage(
    start: datetime, end: datetime, bbox: tuple[float, float, float, float], min_mag: Optional[float]
) -> Coverage:
    return Coverage([Segment(_utc(start), _utc(end), bbox, min_mag, "USGS FDSN query")])


def _fetch_window(start, end, bbox, min_mag, raw_dir, sess) -> Iterable[QuakeRecord]:
    params = _query_params(start, end, bbox, min_mag)
    count_resp = fetch(FDSN_BASE + "count", params=params, session=sess)
    info = json.loads(count_resp.body)
    count = int(info.get("count", 0))
    limit = int(info.get("maxAllowed", MAX_PER_QUERY))
    time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)
    if count == 0:
        return []
    if count > limit:
        if end - start <= timedelta(minutes=1):
            raise RuntimeError(f"{count} events in one minute exceed ComCat's limit of {limit}")
        mid = start + (end - start) / 2
        return [
            *_fetch_window(start, mid, bbox, min_mag, raw_dir, sess),
            *_fetch_window(mid, end, bbox, min_mag, raw_dir, sess),
        ]
    got = fetch(
        FDSN_BASE + "query",
        params={**params, "limit": limit, "orderby": "time-asc"},
        raw_dir=raw_dir,
        name=f"usgs-{start:%Y%m%dT%H%M%S}-{end:%Y%m%dT%H%M%S}.geojson",
        session=sess,
    )
    time.sleep(MIN_SECONDS_BETWEEN_REQUESTS)
    return parse_geojson(got.body, retrieved_at=got.retrieved_at)


def _query_params(start, end, bbox, min_mag) -> dict:
    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "format": "geojson",
        "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.strftime("%Y-%m-%dT%H:%M:%S"),
        "minlatitude": lat_min,
        "maxlatitude": lat_max,
        "minlongitude": lon_min,
        "maxlongitude": lon_max,
        "eventtype": "earthquake",
    }
    if min_mag is not None:
        params["minmagnitude"] = min_mag
    return params


def _from_ms(ms) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=int(ms))


def _iso_or_none(ms) -> Optional[str]:
    return _from_ms(ms).isoformat() if ms is not None else None


def _split_list(s: Optional[str]) -> list[str]:
    return [x for x in (s or "").split(",") if x]


def _utc(t: datetime) -> datetime:
    if t.tzinfo is None:
        return t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def _parse_query_time(s: str) -> datetime:
    """FDSN starttime/endtime: a date or date-time, UTC unless an offset is given."""
    return _utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
