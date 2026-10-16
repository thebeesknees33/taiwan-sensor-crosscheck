from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from crosscheck import http

SECRET = "CWA-FAKE-TESTKEY-0000"


class Resp:
    def __init__(self, status=200, headers=None, url="https://api.test/x?Authorization=" + SECRET + "&format=JSON"):
        self.status_code = status
        self.headers = headers or {}
        self.content = b"{}"
        self.url = url
        self.reason = "Unauthorized" if status == 401 else ""


class Sess:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


@pytest.fixture
def sleeps(monkeypatch):
    got = []
    monkeypatch.setattr(http.time, "sleep", lambda s: got.append(s))
    return got


def call(sess, **kw):
    return http.fetch("https://api.test/x", params={"Authorization": SECRET}, session=sess,
                      redact_params=("Authorization",), **kw)


def test_transient_network_errors_are_retried(sleeps):
    sess = Sess(requests.ConnectionError("reset"), requests.Timeout("slow"), Resp(200))
    assert call(sess).status == 200
    assert sess.calls == 3 and sleeps == [2.0, 4.0]


def test_errors_never_show_the_key(sleeps):
    err = requests.ConnectionError(f"Max retries exceeded with url: /x?Authorization={SECRET}&format=JSON")
    with pytest.raises(http.FetchError) as e:
        call(Sess(*[err] * 5))
    assert SECRET not in str(e.value) and "REDACTED" in str(e.value)
    assert e.value.__suppress_context__  # the original (unredacted) error is not printed

    with pytest.raises(http.FetchError) as e:
        call(Sess(Resp(401)))
    assert "401" in str(e.value) and SECRET not in str(e.value)


def test_retry_after_seconds_and_http_date(sleeps):
    call(Sess(Resp(429, {"Retry-After": "7"}), Resp(200)))
    assert sleeps == [7.0]
    when = datetime.now(timezone.utc) + timedelta(seconds=30)
    call(Sess(Resp(503, {"Retry-After": format_datetime(when, usegmt=True)}), Resp(200)))
    assert 25 <= sleeps[1] <= 31
    call(Sess(Resp(503, {"Retry-After": "0"}), Resp(200)))
    assert sleeps[2] == 0.0


def test_long_retry_after_gives_up_instead_of_retrying_early(sleeps):
    with pytest.raises(http.FetchError, match="wait 3600 s"):
        call(Sess(Resp(429, {"Retry-After": "3600"})))
    assert sleeps == []


def test_final_server_error_raises(sleeps):
    with pytest.raises(http.FetchError, match="HTTP 503"):
        call(Sess(*[Resp(503)] * 5))
    assert sleeps == [2.0, 4.0, 8.0, 16.0]
