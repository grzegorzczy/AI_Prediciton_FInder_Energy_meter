"""Narzędzie historii (E3-k5): zakresy i kroki, okno QoS 1, sufit tempa, sterowanie przepływem, wykrywanie luk (K5-U1),
pamięć sum dobowych (K5-U4). Bez brokera i bazy (atrapy); integracja w test_sim_backfill_e2e.py."""
from __future__ import annotations

import json

import pytest

from sim_support import BEARING_INSTALLED, METER_ANCHOR
from simulator.backfill import Plan, Window, fill_gaps, incomplete_minutes, refresh_statements, run
from simulator.samples import Simulator

ANCHOR = int(METER_ANCHOR.timestamp())
BEARING = int(BEARING_INSTALLED.timestamp())
METERS = {"sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka"}
PUMP = "sim_pump_p101"


class Info:
    def __init__(self, log):
        self.rc, self.log, self.done = 0, log, False

    def wait_for_publish(self, timeout=None):
        self.done = True
        self.log.append("wait")

    def is_published(self):
        return self.done


class Client:
    def __init__(self):
        self.sent, self.log = [], []

    def publish(self, topic, payload, qos):
        assert qos == 1
        self.sent.append((topic, payload))
        info = Info(self.log)
        return info


class FakeDb:
    """Baza w pamięci: wiersze (device, metric, t)."""

    def __init__(self):
        self.rows = set()

    def add_messages(self, messages):
        for topic, payload in messages:
            _, _, device, metric = topic.split("/")
            from datetime import datetime
            t = int(datetime.fromisoformat(json.loads(payload)["ts"].replace("Z", "+00:00")).timestamp())
            self.rows.add((device, metric, t))

    def minute_counts(self, device, metric, start, end):
        out = {}
        for d, m, t in self.rows:
            if d == device and m == metric and start <= t < end:
                out[t - t % 60] = out.get(t - t % 60, 0) + 1
        return out

    def has_row(self, device, metric, t):
        return (device, metric, t) in self.rows


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


def test_window_limits_inflight_and_rate():
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


def test_run_waits_for_the_database_after_each_chunk(make_sim):
    """Sterowanie przepływem end-to-end: po każdej porcji czekanie na zapis ostatniej minuty w bazie."""
    sim = make_sim()
    plan = Plan(sim, ANCHOR, ANCHOR + 600, "meters")
    client, db = Client(), FakeDb()
    waits = []

    class Db(FakeDb):
        def has_row(self, device, metric, t):
            db.add_messages(client.sent)                                        # „ingest” zapisuje to, co wysłano
            waits.append(t)
            return FakeDb.has_row(db, device, metric, t)

    stats = run(plan, Window(client, 100), Db(), ANCHOR, ANCHOR + 600, chunk_s=300)
    assert stats["chunks"] == 2 and stats["messages"] == 600 * 4 * 6
    assert waits == [ANCHOR + 299, ANCHOR + 599]


def test_incomplete_minutes_detects_a_single_missing_metric(make_sim):
    """K5-U1: brak wierszy tylko jednej metryki (power_factor) w jednej minucie jest wykryty i uzupełniony."""
    sim = make_sim()
    start, end = ANCHOR + 3600, ANCHOR + 3600 + 300
    plan = Plan(sim, start, end)
    db = FakeDb()
    for t, devices in plan.moments(start, end):
        db.add_messages(plan.messages(t, devices))
    assert incomplete_minutes(plan, db, start, end) == {}
    removed = {r for r in db.rows if r[0] == "sim_mieszalnik" and r[1] == "power_factor" and start + 120 <= r[2] < start + 125}
    db.rows -= removed
    missing = incomplete_minutes(plan, db, start, end)
    assert missing == {"sim_mieszalnik": {start + 120}}
    client = Client()
    window = Window(client, 100)

    original = Window.drain

    def drain_and_store(self):
        original(self)
        db.add_messages(client.sent)

    Window.drain = drain_and_store
    try:
        result = fill_gaps(plan, window, db, start, end)
    finally:
        Window.drain = original
    assert result["missing_before"] == 1 and result["missing_after"] == 0
    assert result["messages"] == 60 * 6                                         # cała minuta jednego licznika
    assert removed <= db.rows


def test_backfill_uses_the_shared_day_sum_cache(sim_config, tmp_path):
    """K5-U4: narzędzie korzysta z tego samego pliku pamięci sum co usługa – drugi start nie liczy dób od nowa."""
    path = str(tmp_path / "energy-days.json")
    first = Simulator(sim_config, path)
    plan = Plan(first, ANCHOR + 3 * 86400, ANCHOR + 3 * 86400 + 5, "meters")
    run(plan, Window(Client(), 100), None, plan.start, plan.end)
    first.cache.flush()
    second = Simulator(sim_config, path)
    assert second.cache.source == "plik" and len(second.cache.days["sim_chlodnia"]) == 3


def test_refresh_statements_follow_the_aggregate_hierarchy():
    statements = refresh_statements(ANCHOR + 90, ANCHOR + 7200 + 30)
    assert [s.split("'")[1] for s in statements] == ["energy_1m", "energy_ext_1m", "energy_1h", "energy_ext_1h", "pump_1m"]
    assert "'2026-11-17T00:00:00.000Z', '2026-11-17T03:00:00.000Z'" in statements[0]          # pełne godziny
