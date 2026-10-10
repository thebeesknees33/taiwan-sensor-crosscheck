"""The normalized earthquake record every source is converted into.

Each collector maps its own format onto QuakeRecord so the matcher and the
metrics never need to know where a record came from. Values are kept at the
precision the source published; nothing is rounded here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional


@dataclass
class QuakeRecord:
    source: str  # agency: "usgs" or "cwa"
    product: str  # which feed: "usgs-comcat", "cwa-catalog", "cwa-report-significant", ...
    source_id: str  # stable id within (source, product)
    origin_time: datetime  # timezone-aware, UTC
    lat: float  # WGS84 degrees
    lon: float
    depth_km: Optional[float]  # positive down; may be negative (above datum) or unknown
    mag: Optional[float]
    mag_type: Optional[str]  # normalized lower case, e.g. "ml", "mww"
    mag_type_raw: Optional[str] = None  # exactly as published
    status: Optional[str] = None  # e.g. USGS "reviewed"/"automatic", CWA catalog ReviewStatus
    url: Optional[str] = None
    retrieved_at: Optional[datetime] = None  # when this collector first saw the record
    extra: dict = field(default_factory=dict)  # source-specific fields, kept for audit

    @property
    def key(self) -> str:
        return f"{self.source}:{self.product}:{self.source_id}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origin_time"] = _iso(self.origin_time)
        d["retrieved_at"] = _iso(self.retrieved_at) if self.retrieved_at else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "QuakeRecord":
        d = dict(d)
        d["origin_time"] = _parse_iso(d["origin_time"])
        if d.get("retrieved_at"):
            d["retrieved_at"] = _parse_iso(d["retrieved_at"])
        return cls(**d)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {s!r}")
    return t.astimezone(timezone.utc)


def normalize_mag_type(raw: Optional[str]) -> Optional[str]:
    """Lower-case a magnitude type; CWA's Chinese label 芮氏規模 is local magnitude ML."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    if s == "芮氏規模":
        return "ml"
    return s.lower()


def write_jsonl(records: Iterable[QuakeRecord], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: str | Path) -> Iterator[QuakeRecord]:
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield QuakeRecord.from_dict(json.loads(line))
