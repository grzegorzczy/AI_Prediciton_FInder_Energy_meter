"""Tor od atrapy PLC przez collector (w procesie testu) i prawdziwy Mosquitto do odbiorcy z kontem `ingest`.

Wymaga brokera (projekt aip-test); poza nim testy są pomijane. Collector używa prawdziwego ModbusPlcDriver,
PahoTransport i pętli `run`, więc sprawdzany jest ten sam kod co w kontenerze (bez sprzętu).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import re
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import pytest

from collector import main as collector_main
from collector.drivers.modbus_plc import ModbusPlcDriver
from collector.evaluator import Evaluator
from collector.publisher import PahoTransport, Publisher
from fakes.modbus_plc import FakePlc

pytestmark = pytest.mark.skipif("MQTT_HOST" not in os.environ, reason="wymaga brokera Mosquitto (projekt aip-test)")

TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
PREFIX = "zaklad1/linia1/"
EXPECTED_TOPICS = {
    "plc-01/link_status",
    *(f"finder_7m24_1/{m}" for m in (
        "active_power", "reactive_power", "apparent_power", "power_factor", "frequency", "voltage", "current",
        "energy_import_wh", "energy_export_wh", "meter_status", "meter_error_count", "meter_data_age_ms")),
}


class Listener:
    """Odbiorca z kontem ingest: zbiera wiadomości z czasem odbioru."""

    def __init__(self):
        self.messages: list[tuple[float, str, dict]] = []
        self._lock = threading.Lock()
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="e2e-" + uuid.uuid4().hex[:8],
                                   protocol=mqtt.MQTTv5)
        self._client.username_pw_set(os.environ["MQTT_INGEST_USER"], os.environ["MQTT_INGEST_PASSWORD"])
        self._client.on_connect = lambda c, u, f, rc, p: c.subscribe("+/+/+/+", qos=1)
        self._client.on_message = self._on_message
        self._client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
        self._client.loop_start()

    def _on_message(self, client, userdata, msg):
        with self._lock:
            self.messages.append((time.monotonic(), msg.topic, json.loads(msg.payload)))

    def snapshot(self):
        with self._lock:
            return list(self.messages)

    def since(self, mark: float):
        return [m for m in self.snapshot() if m[0] >= mark]

    def close(self):
        self._client.loop_stop()
        self._client.disconnect()


class Harness:
    """Atrapa PLC + collector w jednej pętli zdarzeń; konfiguracja z prawdziwego devices.yaml (szybsze okresy)."""

    def __init__(self, config, heartbeat_timeout_s=1.0):
        self.plc = FakePlc()
        plc_cfg = dataclasses.replace(
            config.plc, host="127.0.0.1", port=self.plc.port, poll_interval_s=0.2, timeout_s=1.0,
            reconnect_initial_s=0.1, reconnect_max_s=0.4, heartbeat_timeout_s=heartbeat_timeout_s)
        self.config = dataclasses.replace(config, plc=plc_cfg)
        self.listener = Listener()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.health_file = f"/tmp/e2e-health-{uuid.uuid4().hex[:6]}"
        self.publisher = None

    async def __aenter__(self):
        await self.plc.start()
        transport = PahoTransport(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")),
                                  os.environ["MQTT_COLLECTOR_USER"], os.environ["MQTT_COLLECTOR_PASSWORD"],
                                  client_id="e2e-collector-" + uuid.uuid4().hex[:6])
        self.publisher = Publisher(transport, 20000)
        self.publisher.start()
        self.driver = ModbusPlcDriver(self.config.plc)
        self.task = asyncio.create_task(collector_main.run(
            self.config, self.driver, self.publisher, Evaluator(self.config), self.stop, health_file=self.health_file))
        return self

    async def __aexit__(self, *exc):
        self.stop.set()
        if self.task:
            await self.task
        await self.driver.close()
        self.publisher.stop()
        self.listener.close()
        await self.plc.close()
        try:
            os.remove(self.health_file)
        except OSError:
            pass

    async def until(self, predicate, timeout=8.0, step=0.05):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            await asyncio.sleep(step)
        raise AssertionError("warunek nie został spełniony w czasie")

    def latest(self, topic, since=0.0):
        found = [m for m in self.listener.since(since) if m[1] == PREFIX + topic]
        return found[-1][2] if found else None

    def value_is(self, topic, value, since=0.0):
        return lambda: (self.latest(topic, since) or {}).get("value") == value

    def assert_only_reads(self):
        assert self.plc.function_codes, "collector nic nie odczytał"
        assert set(self.plc.function_codes) == {4}, f"do PLC dotarły kody funkcji: {set(self.plc.function_codes)}"


def run(coro):
    return asyncio.run(coro)


def test_full_cycle_publishes_13_messages_with_documented_values(config):
    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            await h.until(lambda: h.latest("finder_7m24_1/voltage"))
            await asyncio.sleep(0.5)
            snapshot = h.listener.snapshot()
            by_ts: dict[str, dict] = {}
            for _, topic, body in snapshot:
                by_ts.setdefault(body["ts"], {})[topic[len(PREFIX):]] = body
            full = [group for group in by_ts.values() if set(group) == EXPECTED_TOPICS]
            assert full, f"brak pełnego cyklu 13 wiadomości; zebrane grupy: {[sorted(g) for g in by_ts.values()][:2]}"
            cycle = full[0]
            assert len(cycle) == 13
            assert cycle["finder_7m24_1/voltage"]["value"] == 240.4
            assert cycle["finder_7m24_1/active_power"]["value"] == 7.0
            assert cycle["finder_7m24_1/frequency"]["value"] == 50.02
            assert cycle["finder_7m24_1/energy_import_wh"]["value"] == 3500.0
            assert cycle["finder_7m24_1/meter_status"]["value"] == 0
            assert cycle["plc-01/link_status"]["value"] == 0
            for body in cycle.values():
                assert set(body) == {"ts", "value", "unit", "source"}
                assert TS_PATTERN.match(body["ts"]) and body["source"] == "real"
            assert cycle["finder_7m24_1/voltage"]["unit"] == "V"
            h.assert_only_reads()

    run(scenario())


def test_plc_offline_gives_link_status_1_only_and_recovers_without_restart(config):
    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            await h.until(lambda: h.latest("finder_7m24_1/voltage"))
            await h.plc.stop()
            mark = time.monotonic()
            await h.until(h.value_is("plc-01/link_status", 1, since=mark))
            detected = time.monotonic()
            await asyncio.sleep(1.0)                                        # PLC nadal wyłączony
            during = h.listener.since(detected)
            assert during, "w czasie awarii powinien płynąć link_status"
            assert {m[1] for m in during} == {PREFIX + "plc-01/link_status"}, "podczas awarii tylko link_status"
            assert {m[2]["value"] for m in during} == {1}
            await h.plc.start()
            mark2 = time.monotonic()
            await h.until(h.value_is("plc-01/link_status", 0, since=mark2), timeout=10)
            await h.until(lambda: h.latest("finder_7m24_1/voltage", since=mark2), timeout=10)
            h.assert_only_reads()

    run(scenario())


def test_frozen_heartbeat_gives_link_status_2(config):
    async def scenario():
        async with Harness(config, heartbeat_timeout_s=1.0) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            h.plc.freeze_heartbeat()
            mark = time.monotonic()
            await h.until(h.value_is("plc-01/link_status", 2, since=mark))
            detected = time.monotonic()
            await asyncio.sleep(0.6)
            assert h.latest("finder_7m24_1/voltage", since=detected) is None      # po wykryciu brak pomiarów
            h.plc.freeze_heartbeat(False)
            await h.until(h.value_is("plc-01/link_status", 0, since=time.monotonic()), timeout=10)
            h.assert_only_reads()

    run(scenario())


def test_wrong_map_version_gives_link_status_3(config):
    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            h.plc.set_map_version(2)
            mark = time.monotonic()
            await h.until(h.value_is("plc-01/link_status", 3, since=mark))
            detected = time.monotonic()
            await asyncio.sleep(0.6)
            assert h.latest("finder_7m24_1/voltage", since=detected) is None
            h.assert_only_reads()

    run(scenario())


def test_rs485_break_publishes_status_1_and_diagnostics_then_measurements_return(config):
    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            await h.until(lambda: h.latest("finder_7m24_1/voltage"))
            h.plc.set_meter(status=1, error_code=162, error_count=1, data_age_ms=5200)
            mark = time.monotonic()
            await h.until(h.value_is("finder_7m24_1/meter_status", 1, since=mark))
            await h.until(h.value_is("finder_7m24_1/meter_error_count", 1, since=mark))
            await h.until(h.value_is("finder_7m24_1/meter_data_age_ms", 5200, since=mark))
            await h.until(h.value_is("finder_7m24_1/meter_error_code", 162, since=mark))
            detected = time.monotonic()
            await asyncio.sleep(0.5)
            assert h.latest("finder_7m24_1/voltage", since=detected) is None          # bez pomiarów w czasie przerwy
            assert h.latest("plc-01/link_status", since=mark)["value"] == 0           # sam PLC sprawny

            # sekunda z błędem licznika ma dokładnie 5 wierszy (K6-i: model 13 / 5 / 1)
            groups: dict[str, set] = {}
            for moment, topic, body in h.listener.since(detected):
                groups.setdefault(body["ts"], set()).add(topic[len(PREFIX):])
            full = [groups[key] for key in sorted(groups)][:-1]                       # ostatnia grupa może być jeszcze w drodze
            assert full and all(g == {"plc-01/link_status", "finder_7m24_1/meter_status", "finder_7m24_1/meter_error_count",
                                      "finder_7m24_1/meter_data_age_ms", "finder_7m24_1/meter_error_code"} for g in full)

            h.plc.set_meter(status=0, error_code=0, error_count=1, data_age_ms=0)
            mark2 = time.monotonic()
            await h.until(h.value_is("finder_7m24_1/meter_status", 0, since=mark2))
            await h.until(lambda: h.latest("finder_7m24_1/voltage", since=mark2))
            await asyncio.sleep(0.5)
            assert h.latest("finder_7m24_1/meter_error_code", since=time.monotonic() - 0.4) is None   # przy OK kod nie jest publikowany
            h.assert_only_reads()

    run(scenario())


def test_wrong_serial_gives_meter_status_10(config):
    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            h.plc.set_meter(serial="F9999999")
            mark = time.monotonic()
            await h.until(h.value_is("finder_7m24_1/meter_status", 10, since=mark))
            detected = time.monotonic()
            await asyncio.sleep(0.4)
            assert h.latest("finder_7m24_1/voltage", since=detected) is None
            h.assert_only_reads()

    run(scenario())


def test_offline_detection_time_and_log_volume(config, caplog):
    """K3-U4: czas wykrycia offline <= timeout_s + 1 s; w czasie ciągłej awarii kilka wpisów logu, nie zalew."""

    async def scenario():
        async with Harness(config) as h:
            await h.until(h.value_is("plc-01/link_status", 0))
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="collector"):
                started = time.monotonic()
                await h.plc.stop()
                mark = time.monotonic()
                await h.until(h.value_is("plc-01/link_status", 1, since=mark))
                detected = time.monotonic() - started
                await asyncio.sleep(3.0)                                    # ok. 15 cykli awarii
            records = [r for r in caplog.records if r.name.startswith("collector") and r.levelno >= logging.WARNING]
            print(f"\n[pomiar] wykrycie 'PLC offline' po wyłączeniu serwera: {detected:.2f} s "
                  f"(timeout_s = {h.config.plc.timeout_s}); wpisów WARNING w 3 s awarii: {len(records)}")
            assert detected <= h.config.plc.timeout_s + 1.0
            assert len(records) <= 4, [r.getMessage() for r in records]

    run(scenario())


def test_health_marker_is_refreshed(config):
    from collector import health

    async def scenario():
        async with Harness(config) as h:
            await h.until(lambda: os.path.exists(h.health_file))
            assert health.is_fresh(h.health_file)
            await h.plc.stop()                                              # PLC offline nie psuje żywotności
            await asyncio.sleep(1.0)
            assert health.is_fresh(h.health_file, max_age_s=1.0)

    run(scenario())
