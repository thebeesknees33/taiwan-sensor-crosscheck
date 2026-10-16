import re
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
    remarks = d.find("remarks").text
    assert "depth 34.1 km" in remarks
    assert "Open Government Data License" in remarks  # CWA attribution travels with the marker


def test_usgs_marker_has_no_cwa_attribution():
    ev = parse(cot.to_message(cot.event_element(rec("usgs", "us1"), now=NOW)))
    assert "Open Government Data License" not in ev.find("detail/remarks").text


def test_unknown_values_and_escaping():
    r = rec("usgs", 'id<&>"', depth=None, mag=None, mag_type=None)
    r.url = "https://example.test/?a=1&b=2"
    ev = parse(cot.to_message(cot.event_element(r, now=NOW)))
    assert ev.find("detail/contact").get("callsign") == "USGS M?"
    assert "depthKm" not in ev.find("detail/crosscheck").attrib
    assert ev.find("detail/crosscheck").get("url") == "https://example.test/?a=1&b=2"
    assert re.fullmatch(r"[A-Za-z0-9._-]+", ev.get("uid"))  # also safe as a Windows file name


def test_write_files(tmp_path):
    n = cot.write_files([rec("cwa", "a"), rec("usgs", "b")], tmp_path, now=NOW)
    assert n == 2 and len(list(tmp_path.glob("*.cot"))) == 2


# ------------------------------------------------------------ streaming


def ots_device_uid(messages: list[bytes]) -> str | None:
    """Model of how OpenTAKServer 1.7.13 picks a TCP connection's device uid.

    From EudHandler.handle_cot / pong / parse_device_info: an event of type
    exactly "t-x-c-t" is answered as a ping and skipped; the first other event
    with a <contact> whose uid does not end in "ping" becomes the device.
    """
    for m in messages:
        ev = parse(m)
        if ev.get("type") == "t-x-c-t":
            continue
        if ev.find("detail/contact") is not None and not ev.get("uid").endswith("ping"):
            return ev.get("uid")
    return None


def split_messages(data: bytes) -> list[bytes]:
    return [m + b"</event>" for m in data.split(b"</event>") if m.strip()]


class Server:
    """Local TCP server. mode='collect' reads until EOF; 'echo' also writes
    everything back (like OpenTAKServer relaying traffic to a registered
    gateway); 'ots-split' processes each read the way OpenTAKServer 1.7.13
    does: whole events are handled, a partial event left at the end of a
    read is dropped."""

    def __init__(self, mode="collect"):
        self.mode = mode
        self.data = bytearray()
        self.handled: list[bytes] = []
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.thread = threading.Thread(target=self._serve)
        self.thread.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        with conn:
            while chunk := conn.recv(65536):
                self.data.extend(chunk)
                if self.mode == "echo":
                    conn.sendall(chunk)
                if self.mode == "ots-split":
                    pieces = chunk.split(b"</event>")
                    self.handled += [p + b"</event>" for p in pieces[:-1] if b"<event" in p]
        self.srv.close()

    def join(self):
        self.thread.join(10)


def test_send_announces_gateway_and_confirms_delivery():
    srv = Server()
    res = cot.send_tcp([rec("cwa", "a"), rec("usgs", "b")], "127.0.0.1", srv.port, interval_s=0, now=NOW)
    srv.join()
    assert (res.written, res.confirmed) == (2, True)
    msgs = split_messages(bytes(srv.data))
    assert len(msgs) == 3
    first = parse(msgs[0])
    assert first.get("type") != "t-x-c-t"  # a ping would never register the gateway
    assert first.find("detail/marti/dest").get("callsign") == cot.GATEWAY_CALLSIGN  # not broadcast
    # OpenTAKServer takes the gateway, not a quake marker, as the device.
    assert ots_device_uid(msgs) == cot.GATEWAY_UID
    assert [parse(m).get("type") for m in msgs[1:]] == ["b-m-p-s-m", "b-m-p-s-m"]


def test_without_announcement_a_marker_would_become_the_device():
    srv = Server()
    cot.send_tcp([rec("cwa", "a")], "127.0.0.1", srv.port, announce=False, interval_s=0, now=NOW)
    srv.join()
    assert ots_device_uid(split_messages(bytes(srv.data))) == "crosscheck-cwa-test-a"


def test_send_survives_a_server_that_talks_back():
    # Unread incoming data at close() makes the OS reset the connection and
    # discard queued events; the drain thread must prevent that.
    recs = [rec("cwa", f"q{i}", dt_s=i) for i in range(400)]
    srv = Server("echo")
    res = cot.send_tcp(recs, "127.0.0.1", srv.port, interval_s=0, now=NOW)
    srv.join()
    assert res.confirmed and res.written == 400
    assert len(split_messages(bytes(srv.data))) == 401
    assert res.received_bytes == len(srv.data)


def test_paced_stream_keeps_events_whole_per_read():
    recs = [rec("cwa", f"q{i}", dt_s=i) for i in range(60)]
    srv = Server("ots-split")
    res = cot.send_tcp(recs, "127.0.0.1", srv.port, interval_s=0.005, now=NOW)
    srv.join()
    assert res.confirmed
    assert len(srv.handled) == 61  # presence + every marker survived the per-read split


def test_unconfirmed_when_server_never_closes():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    held = []

    def hold():
        conn, _ = srv.accept()
        held.append(conn)  # read nothing, never close

    th = threading.Thread(target=hold)
    th.start()
    res = cot.send_tcp([rec("cwa", "a")], "127.0.0.1", srv.getsockname()[1], interval_s=0, close_wait_s=0.5, timeout=1, now=NOW)
    th.join(5)
    for c in held:
        c.close()
    srv.close()
    assert res.written == 1 and not res.confirmed
