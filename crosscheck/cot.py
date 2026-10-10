"""Export records as Cursor-on-Target (CoT) XML for viewing in ATAK/WinTAK.

CoT is a display channel only; the project's own JSONL records keep full
precision. Choices (sources in docs/METHOD.md):
- type "b-m-p-s-m": ATAK's own spot-map marker. It carries no
  friend/hostile/unknown affiliation, and OpenTAKServer stores it as a marker.
- how "m-r": relayed from another system by a gateway (not "m-g", which
  OpenTAKServer records as a GPS fix).
- hae/ce/le "9999999.0" (unknown): earthquake depth is not height above the
  WGS84 ellipsoid, and neither source states its errors as the 1-sigma
  circle CoT expects. Depth and errors go in <remarks> and <crosscheck>.
- Times are UTC with a trailing "Z"; OpenTAKServer rejects other offsets.
- One uid per source report, so USGS and CWA markers for the same quake sit
  side by side and a re-sent report replaces its old marker.
- Sending is opt-in. OpenTAKServer's plaintext TCP CoT port is 8088
  (8087 is its UDP port, off by default).
"""

from __future__ import annotations

import re
import socket
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .model import QuakeRecord

UNKNOWN = "9999999.0"
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'
DEFAULT_TYPE = "b-m-p-s-m"
GATEWAY_UID = "taiwan-sensor-crosscheck-gateway"

# Signed 32-bit ARGB, the form ATAK writes in <color argb>.
COLORS = {"usgs": -32768, "cwa": -16776961}  # 0xFFFF8000 orange, 0xFF0000FF blue
DEFAULT_COLOR = -1  # white


def _ts(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def uid_for(r: QuakeRecord) -> str:
    return re.sub(r"[^A-Za-z0-9._:-]", "_", f"crosscheck-{r.product}-{r.source_id}")


def event_element(
    r: QuakeRecord,
    now: Optional[datetime] = None,
    stale_hours: float = 24.0,
    cot_type: str = DEFAULT_TYPE,
) -> ET.Element:
    now = now or datetime.now(timezone.utc)
    ev = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": uid_for(r),
            "type": cot_type,
            "how": "m-r",
            "time": _ts(now),
            "start": _ts(now),
            "stale": _ts(now + timedelta(hours=stale_hours)),
        },
    )
    ET.SubElement(
        ev, "point", {"lat": repr(r.lat), "lon": repr(r.lon), "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN}
    )
    detail = ET.SubElement(ev, "detail")
    mag = f"M{r.mag:.1f} {r.mag_type or ''}".strip() if r.mag is not None else "M?"
    ET.SubElement(detail, "contact", {"callsign": f"{r.source.upper()} {mag}"})
    color = COLORS.get(r.source, DEFAULT_COLOR)
    ET.SubElement(detail, "color", {"argb": str(color)})
    if cot_type == DEFAULT_TYPE:
        ET.SubElement(detail, "usericon", {"iconsetpath": f"COT_MAPPING_SPOTMAP/b-m-p-s-m/{color}"})
    depth = f"{r.depth_km:g} km" if r.depth_km is not None else "unknown"
    remarks = ET.SubElement(detail, "remarks", {"source": f"crosscheck/{r.product}"})
    remarks.text = (
        f"{r.source.upper()} {r.product} {r.source_id} | origin {_ts(r.origin_time)} | "
        f"{mag} | depth {depth} | {r.lat}, {r.lon}" + (f" | {r.url}" if r.url else "")
    )
    attrs = {
        "source": r.source,
        "product": r.product,
        "sourceId": r.source_id,
        "originTime": _ts(r.origin_time),
    }
    if r.mag is not None:
        attrs["mag"] = repr(r.mag)
    if r.mag_type:
        attrs["magType"] = r.mag_type
    if r.depth_km is not None:
        attrs["depthKm"] = repr(r.depth_km)
    if r.url:
        attrs["url"] = r.url
    ET.SubElement(detail, "crosscheck", attrs)
    return ev


def presence_element(now: Optional[datetime] = None, uid: str = GATEWAY_UID) -> ET.Element:
    """Announce the gateway first, so OpenTAKServer ties the connection to it.

    OpenTAKServer takes the uid of the first event with a <contact> as the
    connection's device, and broadcasts a disconnect for that uid when the
    socket closes. Sending this first keeps that away from quake markers.
    (Inferred from OpenTAKServer source; not yet tested against a server.)
    """
    now = now or datetime.now(timezone.utc)
    ev = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": uid,
            "type": "t-x-c-t",
            "how": "m-r",
            "time": _ts(now),
            "start": _ts(now),
            "stale": _ts(now + timedelta(minutes=5)),
        },
    )
    ET.SubElement(ev, "point", {"lat": "0.0", "lon": "0.0", "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN})
    detail = ET.SubElement(ev, "detail")
    ET.SubElement(detail, "contact", {"callsign": uid})
    return ev


def to_message(ev: ET.Element) -> bytes:
    """TAK stream framing: XML declaration, newline, the event, nothing after </event>."""
    return (XML_DECL + ET.tostring(ev, encoding="unicode")).encode("utf-8")


def write_files(records: Iterable[QuakeRecord], out_dir: Path, **kw) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for r in records:
        (out_dir / f"{uid_for(r)}.cot").write_bytes(to_message(event_element(r, **kw)))
        n += 1
    return n


def send_tcp(
    records: Iterable[QuakeRecord],
    host: str,
    port: int = 8088,
    timeout: float = 10.0,
    announce: bool = True,
    **kw,
) -> int:
    """Stream markers to a TAK server over plaintext TCP. Use only on a trusted local network."""
    n = 0
    with socket.create_connection((host, port), timeout=timeout) as s:
        if announce:
            s.sendall(to_message(presence_element()))
        for r in records:
            s.sendall(to_message(event_element(r, **kw)))
            n += 1
    return n
