"""Polite HTTP fetching that keeps a copy of every raw response.

Every comparison should be reproducible from the exact bytes a source served,
so each fetch can save the body plus a small metadata sidecar (URL, time,
status and the caching headers).

Secrets passed as query parameters (``redact_params``, e.g. the CWA API key)
are removed from the saved metadata and from every error message; the
original exception is not chained, because its text contains the full URL.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import requests

from . import USER_AGENT

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_RETRY_WAIT_S = 300.0  # if a server asks us to wait longer, stop instead of retrying early
KEEP_HEADERS = ("Date", "Last-Modified", "Expires", "Cache-Control", "ETag", "Content-Type")


class FetchError(RuntimeError):
    """A download failed. The message never contains redacted secrets."""


@dataclass
class Fetched:
    url: str
    status: int
    body: bytes
    headers: dict
    retrieved_at: datetime
    raw_path: Optional[Path] = None


def fetch(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    raw_dir: Optional[Path] = None,
    name: Optional[str] = None,
    timeout: float = 60,
    max_retries: int = 4,
    session: Optional[requests.Session] = None,
    redact_params: tuple[str, ...] = (),
) -> Fetched:
    """GET a URL, retrying rate limits, server errors, timeouts and dropped connections."""
    sess = session or requests.Session()
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    secrets = [str(v) for k, v in (params or {}).items() if k in redact_params and v]

    def clean(text: str) -> str:
        text = _redact(text, redact_params)
        for s in secrets:
            text = text.replace(s, "REDACTED")
        return text

    shown = clean(url)
    delay = 2.0
    resp = None
    for attempt in range(max_retries + 1):
        last = attempt == max_retries
        try:
            resp = sess.get(url, params=params, headers=h, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            if last:
                raise FetchError(clean(f"{type(e).__name__} fetching {shown}: {e}")) from None
            time.sleep(delay)
            delay *= 2
            continue
        except requests.RequestException as e:
            raise FetchError(clean(f"{type(e).__name__} fetching {shown}: {e}")) from None
        if resp.status_code not in RETRY_STATUSES or last:
            break
        wait = _retry_after(resp)
        if wait is None:
            wait = delay
        if wait > MAX_RETRY_WAIT_S:
            raise FetchError(f"HTTP {resp.status_code} from {shown}: server asks to wait {wait:.0f} s; giving up")
        time.sleep(wait)
        delay *= 2
    if resp.status_code >= 400:
        reason = getattr(resp, "reason", None) or ""
        raise FetchError(clean(f"HTTP {resp.status_code} {reason} from {getattr(resp, 'url', None) or url}"))
    got = Fetched(
        url=clean(resp.url),
        status=resp.status_code,
        body=resp.content,
        headers={k: resp.headers[k] for k in KEEP_HEADERS if k in resp.headers},
        retrieved_at=datetime.now(timezone.utc),
    )
    if raw_dir is not None:
        got.raw_path = save_raw(got, Path(raw_dir), name or "response")
    return got


def save_raw(got: Fetched, raw_dir: Path, name: str) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = got.retrieved_at.strftime("%Y%m%dT%H%M%S.%fZ")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    path = raw_dir / f"{stamp}-{safe}"
    path.write_bytes(got.body)
    meta = {
        "url": got.url,
        "status": got.status,
        "retrieved_at": got.retrieved_at.isoformat(),
        "headers": got.headers,
        "bytes": len(got.body),
    }
    path.with_name(path.name + ".meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return path


def _retry_after(resp: requests.Response) -> Optional[float]:
    """Seconds to wait from a Retry-After header: delay-seconds or an HTTP-date."""
    v = (resp.headers.get("Retry-After") or "").strip()
    if not v:
        return None
    if v.isdigit():
        return float(v)
    try:
        when = parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _redact(text: str, names: tuple[str, ...]) -> str:
    for n in names:
        text = re.sub(rf"([?&]{re.escape(n)}=)[^&\s'\"]*", r"\1REDACTED", text)
    return text
