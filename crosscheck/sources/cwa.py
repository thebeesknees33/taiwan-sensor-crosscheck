"""Taiwan Central Weather Administration (CWA) earthquake data.

Three products, all published by CWA:

- Felt earthquake reports (rapid, issued minutes after a quake):
  E-A0015-001 "significant" and E-A0016-001 "small-area". Available keyless
  from CWA's public S3 bucket (zip of the latest 16 XML reports each) or from
  the REST API with a free key (JSON).
- Earthquake catalog (reviewed, M>=3): E-A0073-001 (current year, JSON) and
  E-A0073-002 (zip of one XML per year, 1990 onward).

Format notes, all checked against real saved files (see docs/SOURCES.md):
- OriginTime is Taiwan local time. Older REST records use
  "YYYY-MM-DD HH:MM:SS" with no offset; newer ones and all XML use
  ISO 8601 with "+08:00". Both are converted to UTC here.
- Magnitude is local magnitude ML (Chinese label 芮氏規模, English "ML").
- Small-area reports all carry EarthquakeNo <year>000, so EarthquakeNo alone
  is not an id.
- XML values are text, some with leading spaces; files may start with a BOM.
- Catalog gap/rms/erh/erz carry units (度 degrees, 秒 seconds, 公里 km).

Data license: Taiwan Open Government Data License v1.0, which requires
attribution (see NOTICE.md).
"""

from __future__ import annotations

import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from ..http import fetch
from ..model import QuakeRecord, normalize_mag_type

TAIPEI = timezone(timedelta(hours=8))  # Taiwan has used UTC+8 without DST since 1979

S3_BASE = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Earthquake/"
REST_BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"

PRODUCTS = {
    "E-A0015": "cwa-report-significant",
    "E-A0016": "cwa-report-small",
}
CATALOG_PRODUCT = "cwa-catalog"

# Units CWA uses in the catalog, mapped to the unit we store.
_EXPECTED_UNITS = {"gap": "度", "rms": "秒", "erh": "公里", "erz": "公里"}


# ---------------------------------------------------------------- time


def parse_origin_time(s: str) -> datetime:
    """CWA OriginTime -> aware UTC datetime. Naive values are Taiwan local time."""
    s = s.strip()
    if "T" in s or "+" in s[10:] or s.endswith("Z"):
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    else:
        t = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    if t.tzinfo is None:
        t = t.replace(tzinfo=TAIPEI)
    return t.astimezone(timezone.utc)


# ---------------------------------------------------------------- reports


def parse_rest_json(
    data: bytes | str | dict,
    product: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
) -> list[QuakeRecord]:
    """Parse a REST datastore response for E-A0015-* or E-A0016-*."""
    doc = json.loads(data) if isinstance(data, (bytes, str)) else data
    if str(doc.get("success")).lower() != "true":
        raise ValueError(f"CWA API did not report success: {str(doc)[:200]}")
    resource = (doc.get("result") or {}).get("resource_id", "")
    product = product or _product_for(resource)
    records = doc.get("records") or {}
    quakes = records.get("Earthquake")
    if quakes is None and "earthquake" in records:
        raise ValueError("pre-2023 CWB response format (lower-case keys) is not supported")
    return [_report_record(eq, product, None, retrieved_at) for eq in quakes or []]


def parse_report_xml(
    data: bytes | str,
    product: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
) -> QuakeRecord:
    """Parse one report XML file from CWA's S3 bucket."""
    root = _xml_root(data)
    doc = _xml_to_dict(root)
    dataset = doc.get("dataset") or {}
    eq = dataset.get("Earthquake")
    if eq is None:
        raise ValueError("no <Earthquake> element; not a CWA report XML")
    info = dataset.get("datasetInfo") or {}
    meta = {
        "identifier": doc.get("identifier"),
        "sent": doc.get("sent"),
        "IssueTime": info.get("IssueTime"),
        "language": info.get("datasetLanguage"),
    }
    return _report_record(eq, product or "cwa-report", meta, retrieved_at)


def parse_report_zip(
    data: bytes,
    product: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
) -> list[QuakeRecord]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".xml"))
        return [parse_report_xml(z.read(n), product, retrieved_at) for n in names]


def _report_record(eq: dict, product: str, meta: Optional[dict], retrieved_at) -> QuakeRecord:
    info = eq["EarthquakeInfo"]
    epi = info["Epicenter"]
    mag = info.get("EarthquakeMagnitude") or {}
    t = parse_origin_time(str(info["OriginTime"]))
    number = _text(eq.get("EarthquakeNo"))
    issue = (meta or {}).get("IssueTime") or eq.get("IssueTime")
    return QuakeRecord(
        source="cwa",
        product=product,
        # Language-independent id: the zh and en versions of a report share it.
        source_id=f"{number}-{t:%Y%m%dT%H%M%S}",
        origin_time=t,
        lat=_num(epi["EpicenterLatitude"]),
        lon=_num(epi["EpicenterLongitude"]),
        depth_km=_num(info.get("FocalDepth")),
        mag=_num(mag.get("MagnitudeValue")),
        mag_type=normalize_mag_type(_text(mag.get("MagnitudeType"))),
        mag_type_raw=_text(mag.get("MagnitudeType")),
        status="rapid-report",
        url=_text(eq.get("Web")),
        retrieved_at=retrieved_at,
        extra={
            "earthquake_no": number,
            "location": _text(epi.get("Location")),
            "issue_time": _text(issue),
            "report_color": _text(eq.get("ReportColor")),
            **{k: v for k, v in (meta or {}).items() if k in ("identifier", "sent", "language")},
        },
    )


def _product_for(resource_id: str) -> str:
    for prefix, product in PRODUCTS.items():
        if resource_id.startswith(prefix):
            return product
    return "cwa-report"


# ---------------------------------------------------------------- catalog


def parse_catalog_json(data: bytes | str | dict, retrieved_at=None) -> list[QuakeRecord]:
    """Parse the current-year catalog E-A0073-001.json."""
    doc = json.loads(_strip_bom(data)) if isinstance(data, (bytes, str)) else data
    catalog = doc["cwaopendata"]["Dataset"]["Catalog"]
    return _catalog_records(_as_list(catalog.get("EarthquakeInfo")), retrieved_at)


def parse_catalog_xml(data: bytes | str, retrieved_at=None) -> list[QuakeRecord]:
    """Parse one yearly catalog XML (CWA-EQ-Catalog-YYYY.xml)."""
    doc = _xml_to_dict(_xml_root(data))
    catalog = (doc.get("Dataset") or {}).get("Catalog") or {}
    return _catalog_records(_as_list(catalog.get("EarthquakeInfo")), retrieved_at)


def parse_catalog_zip(
    data: bytes, years: Optional[set[int]] = None, retrieved_at=None
) -> list[QuakeRecord]:
    """Parse the historical catalog zip E-A0073-002.zip, optionally only some years."""
    out: list[QuakeRecord] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(z.namelist()):
            m = re.fullmatch(r"CWA-EQ-Catalog-(\d{4})\.xml", Path(name).name)
            if m and (years is None or int(m.group(1)) in years):
                out.extend(parse_catalog_xml(z.read(name), retrieved_at))
    return out


def _catalog_records(items: list[dict], retrieved_at) -> list[QuakeRecord]:
    out = []
    used: dict[str, int] = {}
    for e in items:
        t = parse_origin_time(str(e["OriginTime"]))
        sid = f"{t:%Y%m%dT%H%M%S}"
        used[sid] = used.get(sid, 0) + 1
        if used[sid] > 1:  # two events in the same second
            sid = f"{sid}-{used[sid]}"
        extra: dict[str, Any] = {
            "quality": _text(e.get("Quality")),
            "station_number": _int(e.get("StationNumber")),
            "phase_number": _int(e.get("PhaseNumber")),
            "min_epicenter_distance_km": _num(e.get("MinimumEpicenterDistance")),
        }
        for k, expected_unit in _EXPECTED_UNITS.items():
            value, unit = _num_unit(e.get(k))
            extra[k] = value
            if unit is not None and unit != expected_unit:
                extra[f"{k}_unit"] = unit  # flag unexpected units instead of guessing
        out.append(
            QuakeRecord(
                source="cwa",
                product=CATALOG_PRODUCT,
                source_id=sid,
                origin_time=t,
                lat=_num(e["EpicenterLatitude"]),
                lon=_num(e["EpicenterLongitude"]),
                depth_km=_num(e.get("FocalDepth")),
                mag=_num(e.get("LocalMagnitude")),
                mag_type="ml",
                mag_type_raw="LocalMagnitude",
                status=_text(e.get("ReviewStatus")),
                retrieved_at=retrieved_at,
                extra=extra,
            )
        )
    return out


# ---------------------------------------------------------------- auto-detect


def parse_file(path: str | Path, product: Optional[str] = None) -> list[QuakeRecord]:
    """Parse any saved CWA file: report/catalog zip, report/catalog XML, REST or catalog JSON."""
    path = Path(path)
    data = path.read_bytes()
    name = path.name
    if product is None:
        for prefix, p in PRODUCTS.items():
            if prefix in name:
                product = p
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
        if any(re.search(r"CWA-EQ-Catalog-\d{4}\.xml$", n) for n in names):
            return parse_catalog_zip(data)
        return parse_report_zip(data, product)
    head = _strip_bom(data[:4096]).lstrip()
    if head.startswith(b"<"):
        # Catalog files use <Dataset>; report files use lower-case <dataset>.
        if _xml_root(data).find("{*}Dataset") is not None:
            return parse_catalog_xml(data)
        return [parse_report_xml(data, product)]
    doc = json.loads(_strip_bom(data))
    if "cwaopendata" in doc:
        return parse_catalog_json(doc)
    return parse_rest_json(doc, product)


# ---------------------------------------------------------------- fetching


def fetch_reports_s3(
    which: str = "significant", raw_dir: Optional[Path] = None, session=None
) -> list[QuakeRecord]:
    """Latest 16 felt reports from CWA's public S3 bucket (no key needed)."""
    dataset = {"significant": "E-A0015-001", "small": "E-A0016-001"}[which]
    got = fetch(S3_BASE + dataset + ".zip", raw_dir=raw_dir, name=dataset + ".zip", session=session)
    return parse_report_zip(got.body, PRODUCTS[dataset[:7]], got.retrieved_at)


def fetch_reports_rest(
    which: str = "significant",
    api_key: Optional[str] = None,
    limit: Optional[int] = None,
    raw_dir: Optional[Path] = None,
    session: Optional[requests.Session] = None,
) -> list[QuakeRecord]:
    """Felt reports from the REST API. Needs a free key in CWA_API_KEY."""
    key = api_key or os.environ.get("CWA_API_KEY")
    if not key:
        raise RuntimeError("set CWA_API_KEY (free from opendata.cwa.gov.tw) or use the S3 source")
    dataset = {"significant": "E-A0015-001", "small": "E-A0016-001"}[which]
    params: dict[str, Any] = {"Authorization": key, "format": "JSON"}
    if limit:
        params["limit"] = limit
    got = fetch(
        REST_BASE + dataset,
        params=params,
        raw_dir=raw_dir,
        name=dataset + ".json",
        session=session,
        redact_params=("Authorization",),
    )
    return parse_rest_json(got.body, PRODUCTS[dataset[:7]], got.retrieved_at)


def fetch_catalog(
    years: Optional[set[int]] = None, raw_dir: Optional[Path] = None, session=None
) -> list[QuakeRecord]:
    """CWA's reviewed catalog. Current year from E-A0073-001.json; past years from E-A0073-002.zip."""
    this_year = datetime.now(TAIPEI).year
    want_current = years is None or this_year in years
    past = None if years is None else {y for y in years if y != this_year}
    out: list[QuakeRecord] = []
    if past is None or past:
        got = fetch(S3_BASE + "E-A0073-002.zip", raw_dir=raw_dir, name="E-A0073-002.zip", session=session)
        out.extend(parse_catalog_zip(got.body, past, got.retrieved_at))
    if want_current:
        got = fetch(S3_BASE + "E-A0073-001.json", raw_dir=raw_dir, name="E-A0073-001.json", session=session)
        out.extend(parse_catalog_json(got.body, got.retrieved_at))
    return sorted(out, key=lambda r: r.origin_time)


# ---------------------------------------------------------------- helpers


def _strip_bom(data):
    if isinstance(data, bytes) and data.startswith(b"\xef\xbb\xbf"):
        return data[3:]
    if isinstance(data, str) and data.startswith("﻿"):
        return data[1:]
    return data


def _xml_root(data: bytes | str) -> ET.Element:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return ET.fromstring(_strip_bom(data))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_to_dict(el: ET.Element) -> Any:
    """Namespace-free dict view. Repeated children become lists; attributes become '@name'."""
    children = list(el)
    if not children:
        text = el.text
        if el.attrib:
            d = {f"@{k}": v for k, v in el.attrib.items()}
            d["#text"] = text
            return d
        return text
    d: dict[str, Any] = {}
    for c in children:
        k = _local(c.tag)
        v = _xml_to_dict(c)
        if k in d:
            if not isinstance(d[k], list):
                d[k] = [d[k]]
            d[k].append(v)
        else:
            d[k] = v
    return d


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _text(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("#text")
        if v is None:
            return None
    s = str(v).strip()
    return s or None


def _num(v) -> Optional[float]:
    s = _text(v)
    return float(s) if s is not None else None


def _int(v) -> Optional[int]:
    s = _text(v)
    return int(float(s)) if s is not None else None


def _num_unit(v) -> tuple[Optional[float], Optional[str]]:
    unit = v.get("@unit") if isinstance(v, dict) else None
    return _num(v), unit
