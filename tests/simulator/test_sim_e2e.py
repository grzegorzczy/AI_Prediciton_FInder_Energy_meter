"""Symulator -> Mosquitto -> ingest -> baza (projekt aip-test): dane sim w linia2 (QoS 0) obok danych prawdziwych z linia1,
oraz K3-D4: przy przerwie ingestu kolejka brokera zostaje dla danych prawdziwych (QoS 1), dane sim (QoS 0) mają lukę."""
from __future__ import annotations

import os
import time
import uuid

import pytest

from dbtools import REPO, admin_connect
from ingest.config import load_config as load_ingest_config
from ingest_support import HAS_BROKER, IngestHarness, Publisher, count_rows, make_payload, make_store, until
from simulator.live import LiveLoop, iso_ms
from simulator.publisher import PahoTransport
from simulator.publisher import Publisher as SimPublisher

pytestmark = pytest.mark.skipif(not HAS_BROKER, reason="wymaga brokera Mosquitto i bazy (projekt aip-test)")

# Chwile względem „teraz” (ingest odrzuca ts z przyszłości); po kotwicy liczników testów (17.11.2026).
START = (int(time.time()) // 3600 - 1) * 3600


@pytest.fixture
def config():
    return load_ingest_config(REPO / "config" / "devices.yaml")


@pytest.fixture
def pub():
    publisher = Publisher()
    yield publisher
    publisher.close()


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


def sim_transport():
    transport = PahoTransport(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")),
                              os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"], "t-sim-" + uuid.uuid4().hex[:6])
    return transport


def rows(pg, dbname, where):
    with admin_connect(pg, dbname) as conn:
        return conn.execute(f"SELECT time, device_id, metric, value, unit, source FROM measurements WHERE {where} "
                            "ORDER BY time, device_id, metric").fetchall()


def test_simulator_rows_land_in_the_database_equal_to_the_model(pg, migrated_db, role_passwords, config, simulator, pub):
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    harness = IngestHarness(config, store, "t-ingest-" + uuid.uuid4().hex[:6]).start()
    harness.wait_connected()
    transport = sim_transport()
    publisher = SimPublisher(transport, 36000)
    publisher.start()
    try:
        until(transport.is_connected)
        clock = Clock(START)
        loop = LiveLoop(simulator, publisher, clock=clock, sleep=lambda s: None)
        for i in range(3):
            clock.t = START + i
            loop.step()
        pub.publish("zaklad1/linia1/finder_7m24_1/voltage", make_payload(value=231.5, unit="V", ts=iso_ms(START)))
        until(lambda: count_rows(pg, migrated_db) == 3 * 29 + 1, timeout=30)
        sim_rows = rows(pg, migrated_db, "source = 'sim'")
        expected = sorted((d, m, v, u) for t in range(START, START + 3) for d, m, v, u in simulator.samples_at(t))
        assert sorted((r[1], r[2], r[3], r[4]) for r in sim_rows) == expected
        assert {r[0].timestamp() for r in sim_rows} == {START, START + 1, START + 2}
        real = rows(pg, migrated_db, "source = 'real'")
        assert [(r[1], r[2], r[3]) for r in real] == [("finder_7m24_1", "voltage", 231.5)]
    finally:
        publisher.stop()
        harness.stop(forget=True)
        store.close()


@pytest.mark.slow
def test_ingest_outage_keeps_the_broker_queue_for_real_data(pg, migrated_db, role_passwords, config, simulator, pub):
    """K3-D4: ingest zatrzymany 2 min (sesja trwała zostaje) przy działającym symulatorze (QoS 0) i collectorze testowym
    (QoS 1): po powrocie wszystkie wiadomości linia1 są w bazie, a linia2 ma lukę z czasu przerwy."""
    client_id = "t-ingest-" + uuid.uuid4().hex[:6]
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    first = IngestHarness(config, store, client_id).start()
    first.wait_connected()
    transport = sim_transport()
    publisher = SimPublisher(transport, 36000)
    publisher.start()
    until(transport.is_connected)
    clock = Clock(START)
    loop = LiveLoop(simulator, publisher, clock=clock, sleep=lambda s: None)
    second = None
    try:
        loop.step()                                                     # sekunda przed przerwą: dociera
        until(lambda: count_rows(pg, migrated_db, "source = 'sim'") == 29, timeout=30)
        first.stop(forget=False)                                        # ingest „wyłączony”, sesja w brokerze zostaje
        deadline = time.monotonic() + 120
        i = 0
        while time.monotonic() < deadline:
            i += 1
            clock.t = START + i
            loop.step()                                                 # 29 wiadomości QoS 0 na sekundę (linia2)
            pub.publish("zaklad1/linia1/finder_7m24_1/voltage",         # 1 wiadomość QoS 1 na sekundę (linia1)
                        make_payload(value=230.0 + (i % 10) / 10, unit="V", ts=iso_ms(START + i)), wait=False)
            time.sleep(1.0)
        pub.flush()
        outage_seconds = i
        second = IngestHarness(config, store, client_id).start()        # powrót z tą samą sesją
        second.wait_connected()
        until(lambda: count_rows(pg, migrated_db, "source = 'real'") == outage_seconds, timeout=60)
        clock.t = START + outage_seconds + 1
        loop.step()                                                     # po powrocie dane sim znowu docierają
        until(lambda: count_rows(pg, migrated_db, "source = 'sim'") == 2 * 29, timeout=30)
        time.sleep(2.0)
        sim_seconds = {r[0].timestamp() for r in rows(pg, migrated_db, "source = 'sim'")}
        print(f"\nPRZERWA INGESTU {outage_seconds} s: linia1 {count_rows(pg, migrated_db, 'source = ' + chr(39) + 'real' + chr(39))}"
              f"/{outage_seconds} w bazie, linia2 sekundy w bazie: {sorted(int(s - START) for s in sim_seconds)}")
        assert sim_seconds == {START, START + outage_seconds + 1}       # QoS 0 z czasu przerwy nie był kolejkowany
        assert count_rows(pg, migrated_db, "source = 'real'") == outage_seconds
    finally:
        publisher.stop()
        if second is not None:
            second.stop(forget=True)
        else:
            from ingest_support import forget_session
            forget_session(client_id)
        store.close()
