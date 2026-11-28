"""Wspólne helpery testów symulatora (osobny moduł, nie conftest: w repo jest kilka plików conftest.py)."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

# „Wdrożenie” testowe: wtorek 01.12.2026 00:00 UTC (01:00 czasu lokalnego). Jak w k7 (K2R-D1):
# kotwica liczników = wdrożenie − 14 dni, montaż łożyska = wdrożenie − 84 dni (x = 0,70 we wdrożeniu).
T_ZERO = datetime(2026, 12, 1, tzinfo=timezone.utc)
METER_ANCHOR = T_ZERO - timedelta(days=14)
BEARING_INSTALLED = T_ZERO - timedelta(days=84)
ISO = "%Y-%m-%dT%H:%M:%SZ"


def epoch(year, month, day, hour=0, minute=0, second=0, tz=timezone.utc) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=tz).timestamp())


def set_dates(raw: dict, meter_anchor=METER_ANCHOR, bearing=BEARING_INSTALLED) -> dict:
    """Ustawia w surowym configu obie daty (None = null: config bez dat, jak przed wdrożeniem k7)."""
    section = raw["simulator"]
    section["meter_anchor"] = meter_anchor.strftime(ISO) if isinstance(meter_anchor, datetime) else meter_anchor
    for dev in section["devices"]:
        if dev["kind"] == "pump":
            dev["bearing_installed_at"] = bearing.strftime(ISO) if isinstance(bearing, datetime) else bearing
    return raw


def with_dates(config, meter_anchor: datetime | None = None, bearing: datetime | None = None):
    """Kopia SimConfig z inną kotwicą liczników i/lub datą montażu łożyska pompy."""
    devices = tuple(dataclasses.replace(d, bearing_installed_at=bearing) if (bearing and d.kind == "pump") else d
                    for d in config.devices)
    return dataclasses.replace(config, meter_anchor=meter_anchor or config.meter_anchor, devices=devices)
