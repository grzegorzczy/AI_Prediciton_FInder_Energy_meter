"""Walidacja tematu i ładunku MQTT. Wadliwe wiadomości idą do logu i liczników, nigdy do bazy.

Kolejność sprawdzania i kody powodów: topic, unknown_device, site_line, metric, payload, ts, value, unit, source.
Ładunek: {ts, value, unit, source}; dodatkowe klucze są ignorowane, flaga retain nie ma znaczenia.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import IngestConfig, SEGMENT

MAX_PAYLOAD_BYTES = 1024
MAX_METRIC_LEN = 64
MAX_UNIT_LEN = 16
METRIC = re.compile(r"^[a-z0-9_]+$")
REQUIRED_KEYS = ("ts", "value", "unit", "source")

REASONS = ("topic", "unknown_device", "site_line", "metric", "payload", "ts", "value", "unit", "source")


@dataclass(frozen=True)
class Row:
    time: datetime
    device_id: str
    metric: str
    value: float
    unit: str
    source: str


@dataclass(frozen=True)
class Rejection:
    reason: str
    detail: str
    device_id: str | None = None


def validate(
    topic: str,
    payload: bytes,
    config: IngestConfig,
    now: datetime,
    max_future_s: float = 300.0,
    max_past_days: float = 400.0,
) -> Row | Rejection:
    parts = topic.split("/")
    if len(parts) != 4 or not all(SEGMENT.match(p) for p in parts):
        return Rejection("topic", "temat musi mieć 4 poziomy z dozwolonych znaków")
    site, line, device_id, metric = parts

    device = config.devices.get(device_id)
    if device is None:
        return Rejection("unknown_device", f"nieznane urządzenie '{device_id}'", device_id)
    if site != config.site or line != config.line:
        return Rejection("site_line", f"zakład/linia '{site}/{line}' inne niż w konfiguracji", device_id)
    if len(metric) > MAX_METRIC_LEN or not METRIC.match(metric):
        return Rejection("metric", f"niedozwolona nazwa metryki '{metric[:MAX_METRIC_LEN]}'", device_id)

    if not payload:
        return Rejection("payload", "pusty ładunek", device_id)
    if len(payload) > MAX_PAYLOAD_BYTES:
        return Rejection("payload", f"ładunek większy niż {MAX_PAYLOAD_BYTES} B", device_id)
    try:
        body = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return Rejection("payload", "ładunek nie jest poprawnym JSON-em", device_id)
    if not isinstance(body, dict):
        return Rejection("payload", "ładunek nie jest obiektem JSON", device_id)
    missing = [k for k in REQUIRED_KEYS if k not in body]
    if missing:
        return Rejection("payload", f"brak kluczy: {', '.join(missing)}", device_id)

    ts = body["ts"]
    if not isinstance(ts, str):
        return Rejection("ts", "ts nie jest tekstem ISO 8601", device_id)
    try:
        moment = datetime.fromisoformat(ts)
    except ValueError:
        return Rejection("ts", "ts nie jest poprawnym czasem ISO 8601", device_id)
    if moment.tzinfo is None or moment.utcoffset() is None:
        return Rejection("ts", "ts bez strefy czasowej", device_id)
    moment = moment.astimezone(timezone.utc)
    if moment > now + timedelta(seconds=max_future_s):
        return Rejection("ts", "ts z przyszłości (poza dopuszczalnym dryfem zegara)", device_id)
    if moment < now - timedelta(days=max_past_days):
        return Rejection("ts", "ts starszy niż dopuszczalne okno", device_id)

    value = body["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return Rejection("value", "value nie jest liczbą", device_id)
    try:
        number = float(value)
    except OverflowError:
        return Rejection("value", "value poza zakresem liczby", device_id)
    if not math.isfinite(number):
        return Rejection("value", "value nie jest liczbą skończoną", device_id)

    unit = body["unit"]
    if not isinstance(unit, str) or len(unit) > MAX_UNIT_LEN:
        return Rejection("unit", "unit nie jest tekstem do 16 znaków", device_id)

    source = body["source"]
    if source not in ("real", "sim"):
        return Rejection("source", "source spoza real/sim", device_id)
    if source != device.source:
        return Rejection("source", f"source '{source}' różne od źródła urządzenia ('{device.source}')", device_id)

    return Row(time=moment, device_id=device_id, metric=metric, value=number, unit=unit, source=source)
