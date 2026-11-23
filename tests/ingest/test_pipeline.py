"""Potok: paczkowanie, potwierdzenie dopiero po zapisie, ponawianie, izolacja wierszy, rejestr odrzuceń."""
from __future__ import annotations

import logging

import pytest

from ingest.pipeline import Incoming, Pipeline
from ingest.store import NeedsResync, StoreUnavailable

from ingest_support import NOW, make_payload

TOPIC = "zaklad1/linia1/finder_7m24_1/voltage"


class Acks:
    def __init__(self):
        self.tokens = []

    def __call__(self, token):
        self.tokens.append(token)


def build(config, store, clock, **kw):
    acks = Acks()
    pipeline = Pipeline(config, store, acks, clock=clock, wall=lambda: NOW, **kw)
    return pipeline, acks


def good(i: int, metric="voltage") -> Incoming:
    ts = f"2026-11-23T11:59:{i // 1000 % 60:02d}.{i % 1000:03d}Z"
    return Incoming(f"zaklad1/linia1/finder_7m24_1/{metric}", make_payload(value=float(i), ts=ts), token=i)


def test_batch_closes_after_batch_max_messages(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock, batch_max=100, flush_s=1.0)
    for i in range(99):
        pipeline.feed(good(i))
    pipeline.tick()
    assert fake_store.calls == [] and acks.tokens == []                # jeszcze za mało i za wcześnie
    pipeline.feed(good(99))
    pipeline.tick()
    assert fake_store.calls == [100]
    assert sorted(acks.tokens) == list(range(100))


def test_batch_closes_after_flush_interval(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock, batch_max=100, flush_s=1.0)
    pipeline.feed(good(1))
    pipeline.tick()
    assert fake_store.calls == []
    clock.advance(0.99)
    pipeline.tick()
    assert fake_store.calls == []
    clock.advance(0.02)
    pipeline.tick()
    assert fake_store.calls == [1] and acks.tokens == [1]


def test_ack_only_after_successful_write(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.failures = [StoreUnavailable("baza leży")]
    pipeline.feed(good(1))
    clock.advance(2)
    pipeline.tick()                                                    # zapis się nie udał
    assert acks.tokens == [] and pipeline.pending == 1 and pipeline.db_down
    assert fake_store.rows == {}


def test_retry_with_exponential_backoff_then_success(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.fail_while = StoreUnavailable("baza leży")
    pipeline.feed(good(1))
    attempts = []
    for _ in range(40):                                                # 40 s krokami co 1 s
        clock.advance(1)
        before = len(fake_store.calls)
        pipeline.tick()
        if len(fake_store.calls) > before:
            attempts.append(round(clock.now - 1000))
    # pierwsza próba po flush_s (1 s), potem cofanie 1, 2, 4, 8, 10, 10 s
    assert attempts[:6] == [1, 2, 4, 8, 16, 26]
    assert acks.tokens == []
    fake_store.fail_while = None
    clock.advance(11)
    pipeline.tick()
    assert acks.tokens == [1] and pipeline.pending == 0 and not pipeline.db_down


def test_duplicates_are_counted_and_still_acked(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    pipeline.feed(good(1))
    pipeline.feed(Incoming(good(1).topic, good(1).payload, token="redelivery"))     # to samo dostarczone ponownie
    clock.advance(2)
    pipeline.tick()
    assert fake_store.calls == [2] and len(fake_store.rows) == 1
    assert pipeline.total.written == 1 and pipeline.total.duplicates == 1
    assert sorted(map(str, acks.tokens)) == ["1", "redelivery"]


def test_invalid_message_is_acked_immediately_and_never_written(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    pipeline.feed(Incoming(TOPIC, make_payload(value="x"), token="bad"))
    assert acks.tokens == ["bad"] and pipeline.pending == 0 and fake_store.calls == []
    assert pipeline.total.rejected["value"] == 1


def test_invalid_message_does_not_block_valid_ones(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    pipeline.feed(Incoming(TOPIC, b"nie json", token="bad"))
    pipeline.feed(good(1))
    clock.advance(2)
    pipeline.tick()
    assert len(fake_store.rows) == 1 and sorted(map(str, acks.tokens)) == ["1", "bad"]


def test_row_isolation_when_batch_has_a_constraint_violation(config, fake_store, clock, caplog):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.bad_metrics = {"zla_metryka"}
    for i in range(3):
        pipeline.feed(good(i))
    pipeline.feed(good(10, metric="zla_metryka"))
    pipeline.feed(good(11))
    clock.advance(2)
    with caplog.at_level(logging.INFO, logger="ingest"):
        pipeline.tick()
    assert len(fake_store.rows) == 4                                   # dobre zapisane, zła odrzucona
    assert pipeline.total.rejected["db_constraint"] == 1
    assert sorted(acks.tokens) == [0, 1, 2, 10, 11] and pipeline.pending == 0


def test_foreign_key_violation_triggers_resync_and_one_retry(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.failures = [NeedsResync()]
    pipeline.feed(good(1))
    clock.advance(2)
    pipeline.tick()
    assert fake_store.sync_calls == 1 and len(fake_store.rows) == 1 and acks.tokens == [1]


def test_persistent_foreign_key_violation_falls_back_to_isolation(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.failures = [NeedsResync(), NeedsResync(), NeedsResync(), NeedsResync()]
    pipeline.feed(good(1))
    clock.advance(2)
    pipeline.tick()
    assert acks.tokens == [1] and pipeline.total.rejected["db_constraint"] == 1 and fake_store.rows == {}


def test_database_outage_during_isolation_keeps_remaining_rows(config, fake_store, clock):
    pipeline, acks = build(config, fake_store, clock)
    fake_store.bad_metrics = {"zla_metryka"}
    pipeline.feed(good(1, metric="zla_metryka"))
    pipeline.feed(good(2))
    pipeline.feed(good(3))
    # paczka -> ConstraintError; izolacja: wiersz 1 odrzucony, przy wierszu 2 baza znika
    original = fake_store.insert_rows
    state = {"n": 0}

    def flaky(rows):
        state["n"] += 1
        if state["n"] == 3:                                           # 1: paczka, 2: wiersz 1, 3: wiersz 2
            raise StoreUnavailable("baza zniknęła")
        return original(rows)

    fake_store.insert_rows = flaky
    clock.advance(2)
    pipeline.tick()
    assert acks.tokens == [1] and pipeline.pending == 2 and pipeline.db_down       # 2 i 3 czekają, bez potwierdzenia
    fake_store.insert_rows = original
    clock.advance(11)
    pipeline.tick()
    assert sorted(acks.tokens) == [1, 2, 3] and len(fake_store.rows) == 2


def test_flush_on_shutdown_with_database_down_acks_nothing(config, fake_store, clock):
    """Zatrzymanie ingestu przy niedostępnej bazie: nic nie potwierdzone, broker dostarczy ponownie."""
    pipeline, acks = build(config, fake_store, clock)
    fake_store.fail_while = StoreUnavailable("baza leży")
    for i in range(5):
        pipeline.feed(good(i))
    assert pipeline.flush() is False
    assert acks.tokens == [] and pipeline.pending == 5


def test_rejections_do_not_flood_the_log(config, fake_store, clock, caplog):
    pipeline, acks = build(config, fake_store, clock)
    with caplog.at_level(logging.INFO, logger="ingest"):
        for i in range(1000):
            pipeline.feed(Incoming(TOPIC, make_payload(value="x"), token=i))
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert pipeline.total.rejected["value"] == 1000 and len(acks.tokens) == 1000
    assert len(warnings) == 1                                          # pierwsze wystąpienie, reszta tylko liczona


def test_each_reason_is_logged_once_per_device(config, fake_store, clock, caplog):
    pipeline, _ = build(config, fake_store, clock)
    with caplog.at_level(logging.INFO, logger="ingest"):
        for _ in range(50):
            pipeline.feed(Incoming(TOPIC, make_payload(value="x"), token=1))
            pipeline.feed(Incoming(TOPIC, make_payload(unit=5), token=1))
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 2


def test_new_metric_is_logged_once(config, fake_store, clock, caplog):
    pipeline, _ = build(config, fake_store, clock)
    with caplog.at_level(logging.INFO, logger="ingest"):
        for i in range(5):
            pipeline.feed(good(i, metric="nowa_metryka"))
    assert sum("nowa metryka" in r.getMessage() for r in caplog.records) == 1


def test_database_down_is_logged_on_change_not_every_attempt(config, fake_store, clock, caplog):
    pipeline, _ = build(config, fake_store, clock)
    fake_store.fail_while = StoreUnavailable("baza leży")
    pipeline.feed(good(1))
    with caplog.at_level(logging.INFO, logger="ingest"):
        for _ in range(50):
            clock.advance(1)
            pipeline.tick()
        fake_store.fail_while = None
        clock.advance(11)
        pipeline.tick()
    messages = [r.getMessage() for r in caplog.records]
    assert sum("baza niedostępna" in m for m in messages) == 1
    assert sum("baza dostępna po" in m for m in messages) == 1
    assert len(messages) <= 4


def test_summary_reports_counters_and_resets(config, fake_store, clock):
    pipeline, _ = build(config, fake_store, clock)
    pipeline.feed(good(1))
    pipeline.feed(Incoming(TOPIC, b"zly", token=2))
    clock.advance(2)
    pipeline.tick()
    text = pipeline.summary()
    assert "odebrane=2" in text and "zapisane=1" in text and "rejected=1" in text and "payload=1" in text
    assert "odebrane=0" in pipeline.summary()                          # liczniki przedziału wyzerowane
    assert pipeline.total.received == 2                                # sumy od startu zostają


def test_ack_failure_does_not_stop_the_pipeline(config, fake_store, clock):
    def broken_ack(token):
        raise RuntimeError("paho rozłączone")

    pipeline = Pipeline(config, fake_store, broken_ack, clock=clock, wall=lambda: NOW)
    pipeline.feed(good(1))
    clock.advance(2)
    pipeline.tick()
    assert len(fake_store.rows) == 1 and pipeline.pending == 0
