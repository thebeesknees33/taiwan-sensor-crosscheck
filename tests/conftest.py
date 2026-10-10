from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crosscheck.model import QuakeRecord

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


def rec(source="cwa", sid="x", dt_s=0.0, lat=24.0, lon=121.5, depth=10.0, mag=4.0, mag_type="ml"):
    """Synthetic record for algorithm tests. Parser tests use the real files in fixtures/."""
    return QuakeRecord(
        source=source,
        product=f"{source}-test",
        source_id=sid,
        origin_time=T0 + timedelta(seconds=dt_s),
        lat=lat,
        lon=lon,
        depth_km=depth,
        mag=mag,
        mag_type=mag_type,
    )
