"""E3-k3 (przegląd): przy niedostępnej bazie wiadomości QoS 0 (dane symulatora) są odrzucane, a nie trzymane w pamięci;
QoS 1 (dane prawdziwe) zachowuje się jak dotąd (czeka bez potwierdzenia)."""
from __future__ import annotations

import logging

from ingest.pipeline import Incoming, Pipeline
from ingest.store import StoreUnavailable

from ingest_support import make_payload, unique_ts


class DownStore:
    def __init__(self):
        self.down = True
        self.rows = []

    def insert_rows(self, rows):
        if self.down:
            raise StoreUnavailable("test: baza wyłączona")
        self.rows.extend(rows)
        return len(rows)

    def sync_devices(self, config):
        return (0, 0)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def sim_item(i):
    return Incoming("zaklad1/linia2/sim_pasteryzator/active_power",
                    make_payload(value=1000.0 + i, unit="W", source="sim", ts=unique_ts(i)), (0, 0), qos=0)


def real_item(i):
    return Incoming("zaklad1/linia1/finder_7m24_1/voltage", make_payload(value=230.0, unit="V", ts=unique_ts(i)), (i + 1, 1), qos=1)


def test_qos0_is_dropped_while_the_database_is_down_and_qos1_waits(config, caplog):
    acked = []
    clock = Clock()
    store = DownStore()
    pipeline = Pipeline(config, store, ack=acked.append, clock=clock, flush_s=0.0)
    pipeline.feed(real_item(0))
    pipeline.tick()                                               # pierwsza próba zapisu: baza niedostępna
    assert pipeline.db_down and pipeline.pending == 1
    with caplog.at_level(logging.WARNING, logger="ingest"):
        for i in range(20000):                                    # ok. 11 min danych symulatora (29/s)
            pipeline.feed(sim_item(i))
        for i in range(1, 50):
            pipeline.feed(real_item(i))
    assert pipeline.pending == 50, "w pamięci tylko dane prawdziwe (QoS 1), bez danych sim"
    assert pipeline.total.dropped_qos0 == 20000
    assert sum("odrzucam wiadomości QoS 0" in r.getMessage() for r in caplog.records) == 1
    assert [t for t in acked if t[1] == 1] == []                  # dane prawdziwe niepotwierdzone (wrócą z brokera)
    store.down = False
    clock.t += 30
    pipeline.tick()
    assert not pipeline.db_down and len(store.rows) == 50 and pipeline.pending == 0
    assert "odrzucone_qos0_przy_braku_bazy=20000" in pipeline.summary()


def test_qos0_is_stored_normally_when_the_database_is_up(config):
    store = DownStore()
    store.down = False
    pipeline = Pipeline(config, store, ack=lambda t: None, clock=Clock(), flush_s=0.0)
    for i in range(10):
        pipeline.feed(sim_item(i))
    pipeline.tick()
    assert len(store.rows) == 10 and pipeline.total.dropped_qos0 == 0
