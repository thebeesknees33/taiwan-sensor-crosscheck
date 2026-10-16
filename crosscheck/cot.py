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

Streaming to a TAK server is opt-in (``send_tcp``). What it does, and why,
based on reading the OpenTAKServer 1.7.13 source (not yet tested against a
running server):
- It first sends a gateway announcement. OpenTAKServer treats the first
  event on a connection that carries <contact> as the connecting device,
  and when the connection closes it broadcasts a delete-style message for
  that device's uid. Announcing the gateway first keeps a quake marker
  from being taken for the device. The announcement uses type "t-x-c-t-r",
  because OpenTAKServer answers exactly "t-x-c-t" as a ping and never
  registers it, and it is addressed to the gateway itself (<marti><dest>)
  so the server does not broadcast it to other clients.
- Nagle's algorithm is off and sends are paced: OpenTAKServer up to 1.7.13
  drops any event that is split across two network reads, and pacing keeps
  each read to whole events. This lowers the risk; it cannot rule it out
  if the server falls far behind.
- A background thread reads everything the server sends (it echoes traffic
  back), and the connection is closed gracefully. Closing with unread data
  would reset the connection and discard events still in flight.
"""

from __future__ import annotations

import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .model import QuakeRecord

UNKNOWN = "9999999.0"
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'
DEFAULT_TYPE = "b-m-p-s-m"
GATEWAY_UID = "taiwan-sensor-crosscheck-gateway"
GATEWAY_CALLSIGN = "taiwan-sensor-crosscheck"
PRESENCE_TYPE = "t-x-c-t-r"  # anything but exactly "t-x-c-t", which OpenTAKServer swallows as a ping
CWA_REMARK = "Data: CWA Taiwan, Open Government Data License v1.0 (https://data.gov.tw/license)"

# Signed 32-bit ARGB, the form ATAK writes in <color argb>.
COLORS = {"usgs": -32768, "cwa": -16776961}  # 0xFFFF8000 orange, 0xFF0000FF blue
DEFAULT_COLOR = -1  # white


def _ts(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def uid_for(r: QuakeRecord) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", f"crosscheck-{r.product}-{r.source_id}")


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
        f"{mag} | depth {depth} | {r.lat}, {r.lon}"
        + (f" | {r.url}" if r.url else "")
        + (f" | {CWA_REMARK}" if r.source == "cwa" else "")
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


def presence_element(now: Optional[datetime] = None) -> ET.Element:
    """Gateway announcement sent before any marker (see the module docstring)."""
    now = now or datetime.now(timezone.utc)
    ev = ET.Element(
        "event",
        {
            "version": "2.0",
            "uid": GATEWAY_UID,
            "type": PRESENCE_TYPE,
            "how": "m-r",
            "time": _ts(now),
            "start": _ts(now),
            "stale": _ts(now + timedelta(minutes=5)),
        },
    )
    ET.SubElement(ev, "point", {"lat": "0.0", "lon": "0.0", "hae": UNKNOWN, "ce": UNKNOWN, "le": UNKNOWN})
    detail = ET.SubElement(ev, "detail")
    ET.SubElement(detail, "contact", {"callsign": GATEWAY_CALLSIGN})
    marti = ET.SubElement(detail, "marti")
    ET.SubElement(marti, "dest", {"callsign": GATEWAY_CALLSIGN})
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


@dataclass
class SendResult:
    written: int  # marker events written to the socket
    confirmed: bool  # the server read everything we sent and closed the connection
    received_bytes: int  # what the server sent back (echoes, other clients' traffic)


def send_tcp(
    records: Iterable[QuakeRecord],
    host: str,
    port: int = 8088,
    timeout: float = 10.0,
    interval_s: float = 0.02,
    announce: bool = True,
    close_wait_s: float = 15.0,
    **kw,
) -> SendResult:
    """Stream markers to a TAK server over plaintext TCP. Use only on a trusted local network.

    ``confirmed`` is True when, after we finished sending and closed our side,
    the server closed its side too. A server only sees our close after
    reading everything before it, so that confirms the server received every
    byte. It cannot confirm the server stored every marker.
    """
    received = 0
    eof = threading.Event()
    stop = threading.Event()
    written = 0
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def drain() -> None:
            nonlocal received
            while not stop.is_set():
                try:
                    chunk = s.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    return
                if not chunk:
                    eof.set()
                    return
                received += len(chunk)

        reader = threading.Thread(target=drain, name="cot-drain", daemon=True)
        reader.start()
        try:
            if announce:
                s.sendall(to_message(presence_element()))
            for r in records:
                if announce or written:
                    time.sleep(interval_s)
                s.sendall(to_message(event_element(r, **kw)))
                written += 1
            s.shutdown(socket.SHUT_WR)
            eof.wait(close_wait_s)
        finally:
            stop.set()
            reader.join(timeout + 1)
    return SendResult(written, eof.is_set(), received)
