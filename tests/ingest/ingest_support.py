"""Wspólne helpery testów ingestu (osobny moduł, nie conftest: w repo jest kilka plików conftest.py)."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

from dbtools import admin_connect
from ingest.main import serve
from ingest.mqtt_in import MqttInput
from ingest.pipeline import Pipeline
from ingest.store import ConstraintError, Store, StoreUnavailable

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)
HAS_BROKER = "MQTT_HOST" in os.environ


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeStore:
    """Atrapa bazy: zapamiętuje wiersze, usuwa duplikaty po (urządzenie, metryka, czas), wstrzykuje błędy."""

    def __init__(self) -> None:
        self.rows: dict[tuple, object] = {}
        self.calls: list[int] = []
        self.failures: list[Exception] = []          # kolejka wyjątków zgłaszanych przy kolejnych zapisach
        self.fail_while: Exception | None = None     # wyjątek przy każdym zapisie, dopóki ustawiony
        self.sync_calls = 0
        self.bad_metrics: set[str] = set()           # wiersze z tą metryką wywołują ConstraintError

    def sync_devices(self, config):
        self.sync_calls += 1
        return len(config.devices), 0

    def insert_rows(self, rows):
        self.calls.append(len(rows))
        if self.failures:
            raise self.failures.pop(0)
        if self.fail_while is not None:
            raise self.fail_while
        if any(r.metric in self.bad_metrics for r in rows):
            raise ConstraintError("test: naruszenie ograniczenia")
        inserted = 0
        for r in rows:
            key = (r.device_id, r.metric, r.time)
            if key not in self.rows:
                self.rows[key] = r
                inserted += 1
        return inserted


DEFAULT_TS = "2026-11-23T11:59:59.123Z"


def make_payload(value=240.4, unit="V", source="real", ts=DEFAULT_TS, **extra) -> bytes:
    return json.dumps({"ts": ts, "value": value, "unit": unit, "source": source, **extra}).encode()


# --- integracja: broker i baza z projektu aip-test --------------------------------------------------------

def broker_params() -> dict:
    return {"host": os.environ["MQTT_HOST"], "port": int(os.environ.get("MQTT_PORT", "1883"))}


class Publisher:
    """Klient z kontem collector (tylko publikacja)."""

    def __init__(self) -> None:
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t-pub-" + uuid.uuid4().hex[:8],
                                  protocol=mqtt.MQTTv5)
        self.client.username_pw_set(os.environ["MQTT_COLLECTOR_USER"], os.environ["MQTT_COLLECTOR_PASSWORD"])
        self.client.max_inflight_messages_set(200)
        self.client.connect(**broker_params())
        self.client.loop_start()
        self.last = None

    def publish(self, topic: str, payload: bytes | str, wait: bool = True) -> None:
        self.last = self.client.publish(topic, payload, qos=1)
        if wait:
            self.last.wait_for_publish(timeout=10)

    def flush(self) -> None:
        if self.last is not None:
            self.last.wait_for_publish(timeout=60)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def unique_ts(offset_ms: int = 0, base: datetime | None = None) -> str:
    moment = (base or datetime.now(timezone.utc)) + timedelta(milliseconds=offset_ms)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def topic_for(device="finder_7m24_1", metric="voltage") -> str:
    return f"zaklad1/linia1/{device}/{metric}"


class FlakyStore(Store):
    """Prawdziwa baza, którą test może „wyłączyć” (zapis i synchronizacja zgłaszają StoreUnavailable)."""

    down = False

    def insert_rows(self, rows):
        if self.down:
            raise StoreUnavailable("test: baza wyłączona")
        return super().insert_rows(rows)

    def sync_devices(self, config):
        if self.down:
            raise StoreUnavailable("test: baza wyłączona")
        return super().sync_devices(config)


def until(predicate, timeout=15.0, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(step)
    raise AssertionError("warunek nie został spełniony w czasie")


def forget_session(client_id: str) -> None:
    """Usuwa trwałą sesję testowego ingestu z brokera (ponowne połączenie z clean_session=True)."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True,
                         protocol=mqtt.MQTTv311)
    client.username_pw_set(os.environ["MQTT_INGEST_USER"], os.environ["MQTT_INGEST_PASSWORD"])
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    time.sleep(0.3)
    client.disconnect()
    client.loop_stop()


class IngestHarness:
    """Uruchamia `serve` (prawdziwy MqttInput i potok) w wątku; można zatrzymać i wystartować ponownie."""

    def __init__(self, config, store, client_id, flush_s=0.2, batch_max=100, summary_s=3600.0):
        self.config, self.store, self.client_id = config, store, client_id
        self.source = MqttInput(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")),
                                os.environ["MQTT_INGEST_USER"], os.environ["MQTT_INGEST_PASSWORD"], client_id)
        self.pipeline = Pipeline(config, store, ack=self.source.ack, flush_s=flush_s, batch_max=batch_max)
        self.stop_event = threading.Event()
        self.health_file = f"/tmp/ingest-health-{uuid.uuid4().hex[:6]}"
        self.error: BaseException | None = None
        self._summary_s = summary_s
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            serve(self.config, self.store, self.source, self.pipeline, self.stop_event,
                  health_file=self.health_file, summary_s=self._summary_s)
        except BaseException as exc:                 # noqa: BLE001  (test ma zobaczyć każdy wyjątek wątku)
            self.error = exc

    def start(self):
        self.thread.start()
        return self

    def stop(self, forget=False):
        self.stop_event.set()
        self.thread.join(timeout=15)
        assert not self.thread.is_alive(), "ingest nie zatrzymał się w 15 s"
        try:
            os.remove(self.health_file)
        except OSError:
            pass
        if forget:
            forget_session(self.client_id)
        assert self.error is None, f"wątek ingestu zakończył się wyjątkiem: {self.error!r}"

    def wait_connected(self, timeout=15.0):
        until(lambda: self.source.connected, timeout)


def count_rows(pg: dict, dbname: str, where: str = "TRUE") -> int:
    with admin_connect(pg, dbname) as conn:
        return conn.execute(f"SELECT count(*) FROM measurements WHERE {where}").fetchone()[0]


def make_store(pg: dict, dbname: str, password: str, flaky: bool = False) -> Store:
    cls = FlakyStore if flaky else Store
    return cls(host=pg["host"], port=pg["port"], dbname=dbname, user="app_writer", password=password)
