"""Wspólne helpery testów symulatora (osobny moduł, nie conftest: w repo jest kilka plików conftest.py)."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

# t_zero testów: wtorek 01.12.2026 00:00 UTC (01:00 czasu lokalnego); kotwica liczników = 17.11.2026 00:00 UTC.
T_ZERO = datetime(2026, 12, 1, tzinfo=timezone.utc)


def epoch(year, month, day, hour=0, minute=0, second=0, tz=timezone.utc) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=tz).timestamp())


def with_t_zero(config, t_zero: datetime):
    return dataclasses.replace(config, t_zero=t_zero)
