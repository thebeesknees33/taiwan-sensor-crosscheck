import socket
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from conftest import rec

from crosscheck import cot

NOW = datetime(2026, 10, 10, 8, 15, 30, 120000, tzinfo=timezone.utc)


def parse(msg: bytes) -> ET.Element:
    text = msg.decode("utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert text.endswith("</event>")  # nothing after </event>
    return ET.fromstring(text.split("\n", 1)[1])


def test_event_structure():
    r = rec("cwa", "115068-20261006T084108", lat=22.29123456, lon=120.11, depth=34.1, mag=4.5)
    ev = parse(cot.to_message(cot.event_element(r, now=NOW, stale_hours=6)))
    assert ev.tag == "event"
    for attr in ("version", "uid", "type", "how", "time", "start", "stale"):
        assert ev.get(attr), attr
    assert ev.get("type") == "b-m-p-s-m"
    assert ev.get("how") == "m-r"
    assert ev.get("time") == "2026-10-10T08:15:30.120Z"
    assert ev.get("stale") == "2026-10-10T14:15:30.120Z"
    assert ev.get("uid") == "crosscheck-cwa-test-115068-20261006T084108"
    pt = ev.find("point")
    assert pt.get("lat") == "22.29123456"  # full precision, not cut to 4 decimals
    assert pt.get("hae") == pt.get("ce") == pt.get("le") == "9999999.0"
    d = ev.find("detail")
    assert d.find("contact").get("callsign") == "CWA M4.5 ml"
    assert d.find("color").get("argb") == str(cot.COLORS["cwa"])
    cc = d.find("crosscheck")
    assert cc.get("depthKm") == "34.1" and cc.get("magType") == "ml"
    assert cc.get("originTime").endswith("Z")
    assert "depth 34.1 km" in d.find("remarks").text


def test_unknown_values_and_escaping():
    r = rec("usgs", 'id<&>"', depth=None, mag=None, mag_type=None)
    r.url = "https://example.test/?a=1&b=2"
    ev = parse(cot.to_message(cot.event_element(r, now=NOW)))
    assert ev.find("detail/contact").get("callsign") == "USGS M?"
    assert "depthKm" not in ev.find("detail/crosscheck").attrib
    assert ev.find("detail/crosscheck").get("url") == "https://example.test/?a=1&b=2"
    assert all(c.isalnum() or c in "._:-" for c in ev.get("uid"))


def test_write_files(tmp_path):
    n = cot.write_files([rec("cwa", "a"), rec("usgs", "b")], tmp_path, now=NOW)
    assert n == 2 and len(list(tmp_path.glob("*.cot"))) == 2


def test_send_tcp_announces_gateway_first():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    got = bytearray()

    def serve():
        conn, _ = srv.accept()
        with conn:
            while chunk := conn.recv(65536):
                got.extend(chunk)

    th = threading.Thread(target=serve)
    th.start()
    n = cot.send_tcp([rec("cwa", "a"), rec("usgs", "b")], "127.0.0.1", srv.getsockname()[1], now=NOW)
    th.join(5)
    srv.close()
    assert n == 2
    msgs = [m + "</event>" for m in got.decode().split("</event>") if m.strip()]
    assert len(msgs) == 3
    first = parse(msgs[0].encode())
    assert first.get("uid") == cot.GATEWAY_UID and first.find("detail/contact") is not None
    assert [parse(m.encode()).get("type") for m in msgs[1:]] == ["b-m-p-s-m", "b-m-p-s-m"]
