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
    acked = []
    p = Pipeline(config, store, ack=acked.append, clock=clock, flush_s=0.0)
    p.feed(real(0))
    p.tick()
    assert p.db_down
    with caplog.at_level(logging.WARNING, logger="ingest"):
        for i in range(20000):                                   # ok. 11 min danych symulatora (29/s)
            p.feed(sim(i))
        for i in range(1, 50):
            p.feed(real(i))
    assert p.pending == 50 and p.total.dropped_sim == 20000
    assert [t for t in acked if t[1] == 1] == []                 # dane real niepotwierdzone, dopóki baza nie zapisze
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
    with caplog.at_level(logging.WARNING, logger="ingest"):
        p.tick()                                                 # zapis paczki: koniec epizodu z liczbą odrzuconych
    assert sum("koniec odrzucania" in r.getMessage() and "odrzucono 400" in r.getMessage() for r in caplog.records) == 1


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



def test_limit_must_be_positive(config):
    import pytest

    with pytest.raises(ValueError):
        pipeline_for(config, Store(), Clock(), sim_pending_max=0)


# --- kolejka wejściowa MQTT (przegląd k4): przy wolnej bazie zaległość jest tutaj, a nie w potoku ---------------------------

class Msg:
    def __init__(self, topic, qos, mid=0):
        self.topic, self.qos, self.mid, self.payload = topic, qos, mid, b"{}"


def make_input(sim_devices={"sim_pasteryzator"}, limit=100):
    from ingest.mqtt_in import MqttInput

    return MqttInput("127.0.0.1", 1, "u", "p", "t-queue",
                     droppable=lambda topic, qos: qos == 0 and topic.split("/")[2] in sim_devices, droppable_max=limit)


def test_input_queue_caps_sim_qos0_and_never_blocks_real(caplog):
    src = make_input()
    with caplog.at_level(logging.WARNING, logger="ingest.mqtt"):
        for i in range(1000):                                     # nikt nie czyta kolejki (wolna baza)
            src._on_message(None, None, Msg("zaklad1/linia2/sim_pasteryzator/active_power", 0))
        for i in range(100):                                      # real QoS 1 (max_inflight brokera) i real QoS 0
            src._on_message(None, None, Msg("zaklad1/linia1/finder_7m24_1/voltage", 1, i + 1))
            src._on_message(None, None, Msg("zaklad1/linia1/finder_7m24_1/voltage", 0))
    assert src._queue.qsize() == 100 + 200 and src.sim_dropped_total == 900
    items = [src.get(0) for _ in range(300)]
    assert sum(1 for it in items if it.droppable) == 100 and src._droppable_in_queue == 0
    with caplog.at_level(logging.WARNING, logger="ingest.mqtt"):
        src._on_message(None, None, Msg("zaklad1/linia2/sim_pasteryzator/active_power", 0))    # znowu miejsce
    assert src._queue.qsize() == 1
    starts = [r for r in caplog.records if "odrzucam kolejne" in r.getMessage()]
    ends = [r for r in caplog.records if "koniec odrzucania" in r.getMessage()]
    assert len(starts) == 1 and len(ends) == 1 and "odrzucono 900" in ends[0].getMessage()


def test_input_queue_keeps_sim_with_qos1():
    src = make_input(limit=10)
    for i in range(50):
        src._on_message(None, None, Msg("zaklad1/linia2/sim_pasteryzator/active_power", 1, i + 1))
    assert src._queue.qsize() == 50 and src.sim_dropped_total == 0
