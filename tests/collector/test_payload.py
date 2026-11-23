"""Temat i ładunek MQTT (D2): {ts, value, unit, source}, UTC z milisekundami; `source` z konfiguracji (K3-U1)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from collector.evaluator import Evaluator, Reading
from collector.messages import build_message, format_ts
from fakes.modbus_plc import build_image
from collector.codec import Registers

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_ts_is_utc_iso8601_with_milliseconds():
    moment = datetime(2026, 11, 23, 12, 0, 0, 123456, tzinfo=timezone.utc)
    assert format_ts(moment) == "2026-11-23T12:00:00.123Z"


def test_ts_converts_other_timezones_to_utc():
    warsaw = timezone(timedelta(hours=1))
    assert format_ts(datetime(2026, 11, 23, 13, 0, 0, 5000, tzinfo=warsaw)) == "2026-11-23T12:00:00.005Z"


def test_ts_pads_milliseconds():
    assert format_ts(datetime(2026, 1, 2, 3, 4, 5, 7000, tzinfo=timezone.utc)).endswith(":05.007Z")


def test_topic_and_payload_structure():
    reading = Reading("finder_7m24_1", "voltage", 240.4, "V", "real")
    topic, payload = build_message("zaklad1", "linia1", reading, "2026-11-23T12:00:00.123Z")
    assert topic == "zaklad1/linia1/finder_7m24_1/voltage"
    body = json.loads(payload)
    assert list(body) == ["ts", "value", "unit", "source"]
    assert body == {"ts": "2026-11-23T12:00:00.123Z", "value": 240.4, "unit": "V", "source": "real"}
    assert TS_PATTERN.match(body["ts"])


def test_plc_status_topic():
    topic, payload = build_message("zaklad1", "linia1", Reading("plc-01", "link_status", 0.0, "", "real"), "t")
    assert topic == "zaklad1/linia1/plc-01/link_status"
    assert json.loads(payload)["unit"] == ""


def test_source_sim_from_configuration_reaches_payload(make_config, clock):
    config = make_config(lambda raw: raw["devices"][0].update(source="sim"))
    evaluator = Evaluator(config, clock)
    words = lambda hb: Registers(0, build_image(heartbeat=hb)[:44])  # noqa: E731
    evaluator.evaluate(words(1))
    result = evaluator.evaluate(words(2))
    meter_readings = [r for r in result.readings if r.device_id == "finder_7m24_1"]
    assert meter_readings
    for reading in meter_readings:
        _, payload = build_message(config.site, config.line, reading, "t")
        assert json.loads(payload)["source"] == "sim"
    plc_reading = next(r for r in result.readings if r.device_id == "plc-01")
    assert json.loads(build_message(config.site, config.line, plc_reading, "t")[1])["source"] == "real"


def test_values_are_finite_numbers(config, clock):
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(Registers(0, build_image(heartbeat=1)[:44]))
    result = evaluator.evaluate(Registers(0, build_image(heartbeat=2)[:44]))
    for reading in result.readings:
        _, payload = build_message(config.site, config.line, reading, "t")
        assert isinstance(json.loads(payload)["value"], (int, float))
