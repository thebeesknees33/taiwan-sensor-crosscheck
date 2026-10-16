"""Where, when and down to what magnitude a dataset promises to report.

Completeness ("did catalog B also see the quakes catalog A saw?") is only
fair inside the region and time span BOTH datasets cover. Guessing that span
from the first and last events hides misses near the ends, so each dataset
carries the coverage it actually declares:

- a USGS download: the query's start/end time, bounding box and minimum
  magnitude;
- a CWA catalog file: its own CatalogInfo (StartTime, EndTime, Region,
  MagnitudeRange). Most years declare 118-124E 20-27N, but some declare
  119-123E 21-26N.

Coverage is saved next to each JSONL file (``<name>.info.json``) by the
fetch and parse commands. When it is missing (e.g. CWA felt reports, which
are just "the latest 16"), compare falls back to the span of the events and
says so in the report.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import __version__
from .model import QuakeRecord

GLOBAL_BBOX = (-180.0, -90.0, 180.0, 90.0)

CWA_ATTRIBUTION = (
    "Contains open data from 交通部中央氣象署 (Central Weather Administration, Taiwan): "
    "felt earthquake reports E-A0015/E-A0016 and earthquake catalog E-A0073. "
    "The Open Data is made available to the public under the Open Government Data License, "
    "User can make use of it when complying to the condition and obligation of its terms. "
    "Open Government Data License, version 1.0: https://data.gov.tw/license"
)


@dataclass(frozen=True)
class Segment:
    start: datetime  # UTC, inclusive
    end: datetime  # UTC, inclusive
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max
    min_mag: Optional[float] = None  # lowest magnitude the dataset promises to include, own scale
    label: str = ""

    def contains(self, r: QuakeRecord) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bbox
        return (
            self.start <= r.origin_time <= self.end
            and lat_min <= r.lat <= lat_max
            and lon_min <= r.lon <= lon_max
        )

    def intersect(self, other: "Segment") -> Optional["Segment"]:
        start, end = max(self.start, other.start), min(self.end, other.end)
        bbox = (
            max(self.bbox[0], other.bbox[0]),
            max(self.bbox[1], other.bbox[1]),
            min(self.bbox[2], other.bbox[2]),
            min(self.bbox[3], other.bbox[3]),
        )
        if start > end or bbox[0] > bbox[2] or bbox[1] > bbox[3]:
            return None
        if start == end and self.start != self.end and other.start != other.end:
            return None  # two spans that merely touch (e.g. one year's end, the next one's start)
        floors = [m for m in (self.min_mag, other.min_mag) if m is not None]
        label = " ∩ ".join(x for x in (self.label, other.label) if x)
        return Segment(start, end, bbox, max(floors) if floors else None, label)

    def to_dict(self) -> dict:
        return {
            "start": _iso(self.start),
            "end": _iso(self.end),
            "bbox": list(self.bbox),
            "min_mag": self.min_mag,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(
            start=_parse(d["start"]),
            end=_parse(d["end"]),
            bbox=tuple(float(x) for x in d["bbox"]),
            min_mag=d.get("min_mag"),
            label=d.get("label", ""),
        )


@dataclass
class Coverage:
    segments: list[Segment]
    declared: bool = True  # False when inferred from the events themselves
    notes: list[str] = field(default_factory=list)

    def contains(self, r: QuakeRecord) -> bool:
        return any(s.contains(r) for s in self.segments)

    def intersect(self, other: "Coverage") -> "Coverage":
        segs = [x for a in self.segments for b in other.segments if (x := a.intersect(b)) is not None]
        return Coverage(segs, self.declared and other.declared, self.notes + other.notes)

    def declared_floor(self) -> Optional[float]:
        floors = [s.min_mag for s in self.segments if s.min_mag is not None]
        return max(floors) if floors else None

    @property
    def start(self) -> Optional[datetime]:
        return min((s.start for s in self.segments), default=None)

    @property
    def end(self) -> Optional[datetime]:
        return max((s.end for s in self.segments), default=None)

    def to_dict(self) -> dict:
        return {"declared": self.declared, "segments": [s.to_dict() for s in self.segments], "notes": self.notes}

    @classmethod
    def from_dict(cls, d: dict) -> "Coverage":
        return cls([Segment.from_dict(s) for s in d.get("segments", [])], d.get("declared", True), d.get("notes", []))


def inferred(records: Sequence[QuakeRecord], bbox: tuple[float, float, float, float], label: str) -> Optional[Coverage]:
    """Fallback: the span from the first to the last event inside bbox.

    Events outside bbox are ignored so they cannot stretch the span.
    """
    probe = Segment(datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc), bbox)
    inside = [r for r in records if probe.contains(r)]
    if not inside:
        return None
    start = min(r.origin_time for r in inside)
    end = max(r.origin_time for r in inside)
    return Coverage([Segment(start, end, bbox, None, f"{label} (inferred from events)")], declared=False)


def merge(coverages: Iterable[Optional[Coverage]]) -> Optional[Coverage]:
    """Union of several files' coverage. Unknown if any file's coverage is unknown."""
    segs: list[Segment] = []
    for c in coverages:
        if c is None or not c.declared:
            return None
        segs.extend(c.segments)
    return Coverage(segs) if segs else None


# ---------------------------------------------------------------- sidecar files


def info_path(jsonl_path: str | Path) -> Path:
    p = Path(jsonl_path)
    return p.with_name(p.stem + ".info.json")


def write_info(
    jsonl_path: str | Path,
    records: Sequence[QuakeRecord],
    coverage: Optional[Coverage],
) -> Path:
    path = info_path(jsonl_path)
    info = {
        "generated_by": f"taiwan-sensor-crosscheck {__version__}",
        "created": _iso(datetime.now(timezone.utc)),
        "records": len(records),
        "coverage": coverage.to_dict() if coverage else None,
    }
    if any(r.source == "cwa" for r in records):
        info["attribution"] = CWA_ATTRIBUTION
    path.write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def read_coverage(jsonl_path: str | Path) -> Optional[Coverage]:
    path = info_path(jsonl_path)
    if not path.exists():
        return None
    cov = json.loads(path.read_text(encoding="utf-8")).get("coverage")
    return Coverage.from_dict(cov) if cov else None


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
