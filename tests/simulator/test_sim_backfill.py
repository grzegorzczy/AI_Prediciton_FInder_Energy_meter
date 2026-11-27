"""Narzędzie historii (E3-k5): zakresy i kroki, okno QoS 1, sufit tempa, sterowanie przepływem (porcje i czekanie na bazę),
pomijanie pełnych minut przy powtórnym przebiegu, wykrywanie i uzupełnianie luk jednej metryki (K5-U1), pamięć sum dobowych
(K5-U4). Bez brokera i bazy (atrapy); integracja w test_sim_backfill_e2e.py."""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime

import pytest

from sim_support import BEARING_INSTALLED, METER_ANCHOR
from simulator.backfill import Plan, Window, fill_gaps, incomplete_minutes, refresh_statements, run
from simulator.samples import Simulator

ANCHOR = int(METER_ANCHOR.timestamp())
BEARING = int(BEARING_INSTALLED.timestamp())
METERS = {"sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka"}
PUMP = "sim_pump_p101"


class Info:
    def __init__(self, log, ok=True):
        self.rc, self.log, self.done, self.ok = 0, log, False, ok

    def wait_for_publish(self, timeout=None):
        self.done = self.ok
        self.log.append("wait")

    def is_published(self):
        return self.done


class Client:
    def __init__(self, ok=True):
        self.sent, self.log, self.ok = [], [], ok

    def publish(self, topic, payload, qos):
        assert qos == 1
        self.sent.append((topic, payload))
        return Info(self.log, self.ok)


def row_of(topic, payload):
    _, _, device, metric = topic.split("/")
    return device, metric, int(datetime.fromisoformat(json.loads(payload)["ts"].replace("Z", "+00:00")).timestamp())


class FakeDb:
    """Baza w pamięci (wiersze device, metric, t) z „ingestem”: wiadomości klienta trafiają do bazy dopiero po `delay`
    kolejnych odpytaniach minute_rows – sprawdza, że narzędzie naprawdę czeka przed kolejną porcją."""

    def __init__(self, client=None, delay=0):
        self.rows, self.client, self.delay = set(), client, delay
        self.ingested, self.polls, self.published_at_poll = 0, 0, []

    def ingest(self):
        if self.client is not None:
            for message in self.client.sent[self.ingested:]:
                self.rows.add(row_of(*message))
            self.ingested = len(self.client.sent)

    def minute_counts(self, device, metric, start, end):
        out = {}
        for d, m, t in self.rows:
            if d == device and m == metric and start <= t < end:
                out[t - t % 60] = out.get(t - t % 60, 0) + 1
        return out

    def minute_rows(self, devices, minute):
        self.polls += 1
        self.published_at_poll.append(len(self.client.sent) if self.client else 0)
        if self.polls % (self.delay + 1) == 0:
            self.ingest()
        out = {}
        for d, _, t in self.rows:
            if d in devices and minute <= t < minute + 60:
                out[d] = out.get(d, 0) + 1
        return out


def test_plan_steps_and_starts(make_sim):
    sim = make_sim()
    plan = Plan(sim, ANCHOR - 300, ANCHOR + 120)
    moments = list(plan.moments(ANCHOR - 300, ANCHOR + 120))
    before = [(t, d) for t, d in moments if t < ANCHOR]
    assert [t for t, _ in before] == [ANCHOR - 300, ANCHOR - 240, ANCHOR - 180, ANCHOR - 120, ANCHOR - 60]
    assert all(d == {PUMP} for _, d in before)                                 # przed kotwicą liczników tylko pompa co 1 min
    after = [(t, d) for t, d in moments if t >= ANCHOR]
    assert [t for t, _ in after] == list(range(ANCHOR, ANCHOR + 120))          # liczniki co 1 s
    assert after[0][1] == METERS | {PUMP} and after[1][1] == METERS and after[60][1] == METERS | {PUMP}
    assert list(Plan(sim, BEARING - 600, BEARING + 120, "pump").moments(BEARING - 600, BEARING + 120)) == \
        [(BEARING, {PUMP}), (BEARING + 60, {PUMP})]                            # pompa od montażu łożyska


def test_plan_rejects_partial_minutes_and_other_pump_steps(make_sim, sim_config):
    with pytest.raises(ValueError, match="pełnymi minutami"):
        Plan(make_sim(), ANCHOR + 30, ANCHOR + 120)
    other = dataclasses.replace(sim_config, history=dataclasses.replace(sim_config.history, pump_step_s=120))
    with pytest.raises(ValueError, match="pump_step_s"):
        Plan(Simulator(other, None), ANCHOR, ANCHOR + 120, "pump")


def test_window_limits_inflight_and_rate_and_fails_on_missing_puback():
    client = Client()
    window = Window(client, inflight=3)
    for i in range(10):
        window.publish(f"t/{i}", b"x")
    assert len(window.pending) <= 3 and client.log.count("wait") >= 7
    clock = {"t": 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    rated = Window(Client(), inflight=100, rate=10, clock=lambda: clock["t"], sleep=sleep)
    for i in range(20):
        rated.publish("t", b"x")
    assert sum(slept) == pytest.approx(2.0, abs=0.11)                           # 20 wiadomości przy 10/s = ok. 2 s
    with pytest.raises(ValueError):
        Window(client, inflight=0)
    broken = Window(Client(ok=False), inflight=2, timeout=0.01)
    with pytest.raises(TimeoutError):                                           # brak PUBACK = błąd, nie ciche gubienie
        for i in range(3):
            broken.publish("t", b"x")


def test_run_publishes_in_chunks_and_waits_for_the_database(make_sim):
    """Sterowanie przepływem: przed kolejną porcją ostatnia minuta porcji musi być w bazie kompletna; dopóki „ingest” jej
    nie zapisał, nic więcej nie jest wysyłane (zaległość ≤ jedna porcja)."""
    plan = Plan(make_sim(), ANCHOR, ANCHOR + 600, "meters")
    client = Client()
    db = FakeDb(client, delay=2)
    stats = run(plan, Window(client, 100), db, ANCHOR, ANCHOR + 600, chunk_messages=1440, sleep=lambda s: None)
    assert stats["messages"] == 600 * 4 * 6 and stats["chunks"] == 10 and db.polls == 30
    assert sorted(set(db.published_at_poll)) == [1440 * k for k in range(1, 11)]   # w czasie czekania wysyłka stoi


def test_second_run_skips_complete_minutes_and_resends_only_gaps(make_sim):
    """Powtórny przebieg (wznowienie) pomija pełne minuty, więc nie zalewa brokera duplikatami; luka jednej metryki
    (power_factor jednego licznika, K5-U1) wraca tylko jako ta minuta tego urządzenia."""
    start, end = ANCHOR + 3600, ANCHOR + 3600 + 300
    plan = Plan(make_sim(), start, end)
    client = Client()
    db = FakeDb(client)
    first = run(plan, Window(client, 100), db, start, end, sleep=lambda s: None)
    assert first["messages"] == 300 * 24 + 5 * 5 and incomplete_minutes(plan, db, start, end) == {}
    again = run(plan, Window(client, 100), db, start, end, sleep=lambda s: None)
    assert again["messages"] == 0 and again["device_minutes_skipped"] == 5 * 5
    removed = {r for r in db.rows if r[0] == "sim_mieszalnik" and r[1] == "power_factor" and start + 120 <= r[2] < start + 125}
    db.rows -= removed
    assert incomplete_minutes(plan, db, start, end) == {"sim_mieszalnik": {start + 120}}
    result = fill_gaps(plan, Window(client, 100), db, start, end, sleep=lambda s: None)
    assert result["missing_before"] == 1 and result["missing_after"] == 0
    assert result["messages"] == 60 * 6 and removed <= db.rows                     # cała minuta jednego licznika


def test_fill_gaps_of_a_large_gap_goes_in_chunks(make_sim):
    """Duża luka (np. przerwane wgrywanie) przy --fill-gaps też idzie porcjami z czekaniem na bazę."""
    start, end = ANCHOR, ANCHOR + 1200
    plan = Plan(make_sim(), start, end, "meters")
    client = Client()
    db = FakeDb(client, delay=1)
    result = fill_gaps(plan, Window(client, 100), db, start, end, chunk_messages=7200, sleep=lambda s: None)
    assert result["missing_before"] == 80 and result["missing_after"] == 0 and result["chunks"] == 4
    assert max(db.published_at_poll) == 1200 * 24 and sorted(set(db.published_at_poll))[0] == 7200


def test_wait_times_out_when_ingest_never_writes(make_sim):
    plan = Plan(make_sim(), ANCHOR, ANCHOR + 60, "meters")
    client = Client()
    db = FakeDb(client, delay=10 ** 9)
    clock = {"t": 0.0}

    def sleep(seconds):
        clock["t"] += seconds

    with pytest.raises(TimeoutError, match="ingest nie zapisał"):
        run(plan, Window(client, 100), db, ANCHOR, ANCHOR + 60, clock=lambda: clock["t"], sleep=sleep, wait_timeout=5)


def test_incomplete_minutes_skips_days_before_the_device_history(make_sim):
    plan = Plan(make_sim(), ANCHOR - 3 * 86400, ANCHOR + 120)
    queried = []

    class CountingDb(FakeDb):
        def minute_counts(self, device, metric, start, end):
            queried.append((device, start))
            return {}

    missing = incomplete_minutes(plan, CountingDb(), plan.start, plan.end)
    assert all(start >= ANCHOR for device, start in queried if device in METERS)    # bez zapytań przed kotwicą liczników
    assert missing["sim_chlodnia"] == {ANCHOR, ANCHOR + 60} and len(missing[PUMP]) == 3 * 1440 + 2


def test_backfill_uses_the_shared_day_sum_cache(sim_config, tmp_path):
    """K5-U4: narzędzie korzysta z tego samego pliku pamięci sum co usługa – drugi start nie liczy dób od nowa."""
    path = str(tmp_path / "energy-days.json")
    first = Simulator(sim_config, path)
    plan = Plan(first, ANCHOR + 3 * 86400, ANCHOR + 3 * 86400 + 60, "meters")
    run(plan, Window(Client(), 100), None, plan.start, plan.end)
    first.cache.flush()
    second = Simulator(sim_config, path)
    assert second.cache.source == "plik" and len(second.cache.days["sim_chlodnia"]) == 3


def test_refresh_statements_follow_the_aggregate_hierarchy():
    statements = refresh_statements(ANCHOR + 90, ANCHOR + 7200 + 30)
    assert [s.split("'")[1] for s in statements] == ["energy_1m", "energy_ext_1m", "energy_1h", "energy_ext_1h", "pump_1m"]
    assert "'2026-11-17T00:00:00.000Z', '2026-11-17T03:00:00.000Z'" in statements[0]          # pełne godziny
