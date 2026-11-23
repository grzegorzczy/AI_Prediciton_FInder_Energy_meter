"""Walidacja tematu i ładunku: każdy powód odrzucenia, granice okna czasu, poprawne wiadomości."""
from __future__ import annotations

import json
from datetime import timedelta, timezone

import pytest

from ingest.validate import Rejection, Row, validate

from ingest_support import NOW, make_payload

GOOD_TOPIC = "zaklad1/linia1/finder_7m24_1/voltage"


def run(topic=GOOD_TOPIC, payload=None, config=None, **kw):
    return validate(topic, payload if payload is not None else make_payload(), config, NOW, **kw)


def reason(result) -> str:
    assert isinstance(result, Rejection), f"oczekiwano odrzucenia, jest {result}"
    return result.reason


def test_good_message_becomes_a_row(config):
    result = run(config=config)
    assert result == Row(
        time=NOW.replace(hour=11, minute=59, second=59, microsecond=123000), device_id="finder_7m24_1",
        metric="voltage", value=240.4, unit="V", source="real")


def test_milliseconds_and_timezone_offset_are_preserved(config):
    result = run(payload=make_payload(ts="2026-11-23T12:59:59.456+01:00"), config=config)
    assert result.time.tzinfo == timezone.utc
    assert result.time == NOW.replace(hour=11, minute=59, second=59, microsecond=456000)


def test_integer_and_zero_values_are_accepted(config):
    assert run(payload=make_payload(value=0), config=config).value == 0.0
    assert run(payload=make_payload(value=3500), config=config).value == 3500.0
    assert run(payload=make_payload(value=-8.7), config=config).value == -8.7


def test_empty_unit_is_valid(config):
    assert run(payload=make_payload(unit=""), config=config).unit == ""


def test_plc_status_message_is_valid(config):
    row = run(topic="zaklad1/linia1/plc-01/link_status", payload=make_payload(value=0, unit=""), config=config)
    assert row.device_id == "plc-01" and row.metric == "link_status"


@pytest.mark.parametrize("topic", [
    "zaklad1/linia1/finder_7m24_1",                       # 3 poziomy
    "zaklad1/linia1/finder_7m24_1/voltage/extra",         # 5 poziomów
    "zaklad1/linia1//voltage",                            # pusty segment
    "zaklad1/lin ia1/finder_7m24_1/voltage",              # spacja
    "zaklad1/łinia1/finder_7m24_1/voltage",               # znak spoza ASCII
    "",
])
def test_bad_topic(config, topic):
    assert reason(run(topic=topic, config=config)) == "topic"


def test_unknown_device(config):
    result = run(topic="zaklad1/linia1/nieznany/voltage", config=config)
    assert reason(result) == "unknown_device" and result.device_id == "nieznany"


@pytest.mark.parametrize("topic", ["inny/linia1/finder_7m24_1/voltage", "zaklad1/inna/finder_7m24_1/voltage"])
def test_site_or_line_mismatch(config, topic):
    assert reason(run(topic=topic, config=config)) == "site_line"


@pytest.mark.parametrize("metric", ["Voltage", "volt-age", "a" * 65])
def test_bad_metric(config, metric):
    assert reason(run(topic=f"zaklad1/linia1/finder_7m24_1/{metric}", config=config)) == "metric"


@pytest.mark.parametrize("payload", [
    b"", b"nie json", b"[1,2,3]", b'"tekst"', b"\xff\xfe",
    json.dumps({"ts": "2026-11-23T11:59:59Z", "value": 1, "unit": "V"}).encode(),          # brak source
    json.dumps({"value": 1, "unit": "V", "source": "real"}).encode(),                        # brak ts
    b"x" * 1025,
])
def test_bad_payload(config, payload):
    assert reason(run(payload=payload, config=config)) == "payload"


def test_extra_keys_are_ignored(config):
    assert isinstance(run(payload=make_payload(dodatkowe="x"), config=config), Row)


@pytest.mark.parametrize("ts", [
    "2026-11-23T11:59:59.123",             # bez strefy czasowej
    "2026-11-23",                          # sama data
    "wczoraj", "", 1732363199, None, 1.5,
])
def test_bad_ts_format(config, ts):
    assert reason(run(payload=make_payload(ts=ts), config=config)) == "ts"


def test_ts_future_window(config):
    inside = (NOW + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    outside = (NOW + timedelta(minutes=6)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert isinstance(run(payload=make_payload(ts=inside), config=config), Row)
    assert reason(run(payload=make_payload(ts=outside), config=config)) == "ts"


def test_ts_past_window(config):
    inside = (NOW - timedelta(days=399)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    outside = (NOW - timedelta(days=401)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert isinstance(run(payload=make_payload(ts=inside), config=config), Row)
    assert reason(run(payload=make_payload(ts=outside), config=config)) == "ts"
    assert reason(run(payload=make_payload(ts="1970-01-01T00:00:00Z"), config=config)) == "ts"


def test_window_is_configurable(config):
    old = (NOW - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    assert reason(run(payload=make_payload(ts=old), config=config, max_past_days=7)) == "ts"
    assert isinstance(run(payload=make_payload(ts=old), config=config, max_past_days=60), Row)


@pytest.mark.parametrize("value", ["240.4", None, True, False, [1], {"a": 1}])
def test_value_must_be_a_number(config, value):
    assert reason(run(payload=make_payload(value=value), config=config)) == "value"


@pytest.mark.parametrize("raw", [b"NaN", b"Infinity", b"-Infinity", b"1e400", b"-1e400"])
def test_value_must_be_finite(config, raw):
    payload = b'{"ts":"2026-11-23T11:59:59.000Z","value":' + raw + b',"unit":"V","source":"real"}'
    assert reason(run(payload=payload, config=config)) == "value"


def test_huge_integer_is_rejected_not_crashing(config):
    payload = b'{"ts":"2026-11-23T11:59:59.000Z","value":' + b"9" * 400 + b',"unit":"V","source":"real"}'
    assert reason(run(payload=payload, config=config)) == "value"


@pytest.mark.parametrize("unit", [5, None, "x" * 17, ["V"]])
def test_bad_unit(config, unit):
    assert reason(run(payload=make_payload(unit=unit), config=config)) == "unit"


@pytest.mark.parametrize("source", ["inne", "REAL", None, 1])
def test_source_outside_real_sim(config, source):
    assert reason(run(payload=make_payload(source=source), config=config)) == "source"


def test_source_must_match_the_device(config):
    result = run(payload=make_payload(source="sim"), config=config)    # urządzenie w configu ma source: real
    assert reason(result) == "source" and "różne" in result.detail


def test_simulated_device_accepts_sim_and_rejects_real(make_config):
    config = make_config(lambda raw: raw["devices"][0].update(source="sim"))
    assert isinstance(run(payload=make_payload(source="sim"), config=config), Row)
    assert reason(run(payload=make_payload(source="real"), config=config)) == "source"


def test_order_of_checks_topic_before_payload(config):
    assert reason(run(topic="a/b", payload=b"", config=config)) == "topic"
    assert reason(run(topic="zaklad1/linia1/nieznany/voltage", payload=b"", config=config)) == "unknown_device"
