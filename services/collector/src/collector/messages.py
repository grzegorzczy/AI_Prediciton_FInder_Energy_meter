"""Temat i ładunek MQTT: {site}/{line}/{device_id}/{metric}, ładunek {ts, value, unit, source}."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .evaluator import Reading


def format_ts(moment: datetime) -> str:
    """UTC, ISO 8601 z milisekundami i literą Z (decyzja D2)."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def build_message(site: str, line: str, reading: Reading, ts: str) -> tuple[str, bytes]:
    topic = f"{site}/{line}/{reading.device_id}/{reading.metric}"
    payload = json.dumps(
        {"ts": ts, "value": reading.value, "unit": reading.unit, "source": reading.source},
        separators=(",", ":"),
    )
    return topic, payload.encode("utf-8")
