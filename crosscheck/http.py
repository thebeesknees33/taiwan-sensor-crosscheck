"""Polite HTTP fetching that keeps a copy of every raw response.

Every comparison should be reproducible from the exact bytes a source served,
so each fetch can save the body plus a small metadata sidecar (URL, time,
status and the caching headers).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from . import USER_AGENT

RETRY_STATUSES = {429, 500, 502, 503, 504}
KEEP_HEADERS = ("Date", "Last-Modified", "Expires", "Cache-Control", "ETag", "Content-Type")


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
    """GET a URL, retrying on rate limits and transient errors.

    ``redact_params`` lists query parameters (e.g. an API key) to strip from
    the URL recorded in the metadata sidecar.
    """
    sess = session or requests.Session()
    h = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    h.update(headers or {})
    delay = 2.0
    for attempt in range(max_retries + 1):
        resp = sess.get(url, params=params, headers=h, timeout=timeout)
        if resp.status_code not in RETRY_STATUSES or attempt == max_retries:
            break
        wait = _retry_after(resp) or delay
        time.sleep(wait)
        delay *= 2
    resp.raise_for_status()
    got = Fetched(
        url=_redact(resp.url, redact_params),
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
    v = resp.headers.get("Retry-After")
    if v and v.strip().isdigit():
        return min(float(v), 300.0)
    return None


def _redact(url: str, names: tuple[str, ...]) -> str:
    for n in names:
        url = re.sub(rf"([?&]{re.escape(n)}=)[^&]*", r"\1REDACTED", url)
    return url
