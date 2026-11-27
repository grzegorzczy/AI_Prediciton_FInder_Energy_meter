"""E3-k4 (K4-D1, K4-U1): limit danych symulatora w pamięci ingestu. Odrzucane są wyłącznie wiersze urządzeń `source = sim`
dostarczone z QoS 0, gdy baza jest niedostępna albo w pamięci czeka już `sim_pending_max` wierszy sim. Dane real nigdy."""
from __future__ import annotations

import logging

from ingest.pipeline import Incoming, Pipeline
from ingest.store import StoreUnavailable

from ingest_support import make_payload, unique_ts


class Store:
    """Atrapa bazy: `down` = StoreUnavailable przy zapisie; `stuck` = zapis „wisi” (też StoreUnavailable, jak timeout)."""

    def __init__(self, down=False):
        self.down = down
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


def sim(i, qos=0):
    return Incoming("zaklad1/linia2/sim_pasteryzator/active_power",
                    make_payload(value=1000.0 + i, unit="W", source="sim", ts=unique_ts(i)), (0 if qos == 0 else i + 1, qos), qos=qos)


def real(i, qos=1):
    return Incoming("zaklad1/linia1/finder_7m24_1/voltage", make_payload(value=230.0, unit="V", ts=unique_ts(i)),
                    (i + 1 if qos else 0, qos), qos=qos)


def pipeline_for(config, store, clock, **kw):
    return Pipeline(config, store, ack=lambda t: None, clock=clock, flush_s=0.0, **kw)


def test_database_down_drops_sim_qos0_keeps_real(config, caplog):
    clock, store = Clock(), Store(down=True)
    p = pipeline_for(config, store, clock)
    p.feed(real(0))
    p.tick()
    assert p.db_down
    with caplog.at_level(logging.WARNING, logger="ingest"):
        for i in range(20000):                                   # ok. 11 min danych symulatora (29/s)
            p.feed(sim(i))
        for i in range(1, 50):
            p.feed(real(i))
    assert p.pending == 50 and p.total.dropped_sim == 20000
    store.down = False
    clock.t += 30
    with caplog.at_level(logging.WARNING, logger="ingest"):
        p.tick()
    assert len(store.rows) == 50 and not p.db_down
    starts = [r for r in caplog.records if "odrzucam dane symulatora" in r.getMessage()]
    ends = [r for r in caplog.records if "koniec odrzucania" in r.getMessage()]
    assert len(starts) == 1 and "baza niedostępna" in starts[0].getMessage()
    assert len(ends) == 1 and "odrzucono 20000" in ends[0].getMessage()
    assert "odrzucone_sim=20000" in p.summary()


def test_limit_applies_also_when_the_database_is_up(config, caplog):
    """Wolna, ale dostępna baza: paczki nie schodzą (tick nie jest wołany), więc działa limit liczby wierszy sim."""
    p = pipeline_for(config, Store(), Clock(), sim_pending_max=100, batch_max=10_000)
    with caplog.at_level(logging.WARNING, logger="ingest"):
        for i in range(500):
            p.feed(sim(i))
        for i in range(300):
            p.feed(real(i))                                       # real bez limitu (ogranicza je broker, max_inflight)
    assert p.pending == 100 + 300 and p.total.dropped_sim == 400 and not p.db_down
    assert any("limit INGEST_SIM_PENDING_MAX" in r.getMessage() for r in caplog.records)


def test_real_data_with_qos0_is_never_dropped(config):
    p = pipeline_for(config, Store(down=True), Clock(), sim_pending_max=1)
    p.feed(real(0))
    p.tick()
    for i in range(1, 200):
        p.feed(real(i, qos=0))
    assert p.pending == 200 and p.total.dropped_sim == 0


def test_sim_with_qos1_is_never_dropped(config):
    """K4-U1: wgrywanie historii (k5) może publikować QoS 1 – takie wiersze sim nie podlegają odrzucaniu."""
    p = pipeline_for(config, Store(down=True), Clock(), sim_pending_max=10)
    p.feed(sim(0, qos=1))
    p.tick()
    for i in range(1, 100):
        p.feed(sim(i, qos=1))
    assert p.pending == 100 and p.total.dropped_sim == 0


def test_sim_is_stored_normally_below_the_limit(config):
    store = Store()
    p = pipeline_for(config, store, Clock())
    for i in range(10):
        p.feed(sim(i))
    p.tick()
    assert len(store.rows) == 10 and p.total.dropped_sim == 0
