"""Poprawki po przeglądzie k3: zapis pamięci sum bez zalewu logu, skok zegara bez podwójnego liczenia, zegar przed kotwicą,
symulator bez konta MQTT (K3-D1), kod 2 bez dat, healthcheck."""
from __future__ import annotations

import logging
import time

import pytest

from sim_support import epoch
from simulator import health, main as sim_main
from simulator.live import LiveLoop
from simulator.publisher import Publisher
from simulator.samples import Simulator

ANCHOR = epoch(2026, 11, 17)


class Down:
    def is_connected(self):
        return False

    def publish(self, topic, payload):
        return False

    def start(self):
        pass

    def stop(self):
        pass


def test_failed_cache_write_is_retried_only_on_the_next_day(sim_config, tmp_path, caplog):
    blocker = tmp_path / "plik"
    blocker.write_text("x", encoding="utf-8")
    sim = Simulator(sim_config, str(blocker / "energy-days.json"))
    sim.meters["sim_pakowaczka"][1].value_wh(ANCHOR + 86400 + 5)
    with caplog.at_level(logging.WARNING, logger="simulator.daycache"):
        for _ in range(100):                                      # 100 ticków pętli
            sim.cache.flush()
    assert sum("nie mogę zapisać" in r.getMessage() for r in caplog.records) == 1
    sim.cache.put("sim_pakowaczka", 5, 123)                       # nowa doba: jedna kolejna próba
    with caplog.at_level(logging.WARNING, logger="simulator.daycache"):
        sim.cache.flush()
        sim.cache.flush()
    assert sum("nie mogę zapisać" in r.getMessage() for r in caplog.records) == 2


def test_big_clock_jump_does_not_count_the_gap_twice(sim_config, monkeypatch):
    sim = Simulator(sim_config, None)
    meter, counter = sim.meters["sim_mieszalnik"]
    start = ANCHOR + 86400 + 100
    counter.value_wh(start)
    calls = {"n": 0}
    original = meter.power

    def counting(t):
        calls["n"] += 1
        return original(t)

    monkeypatch.setattr(meter, "power", counting)
    jumped = ANCHOR + 4 * 86400 + 100                             # skok o 3 doby
    value = counter.value_wh(jumped)
    assert calls["n"] <= 3 * 86400 + 200, calls["n"]              # tylko brakujące doby i reszta, bez drugiego przejścia
    assert value == Simulator(sim_config, None).meters["sim_mieszalnik"][1].value_wh(jumped)


def test_clock_before_the_meter_anchor_is_logged_once_and_does_not_stop_the_loop(sim_config, caplog):
    sim = Simulator(sim_config, None)
    clock = {"t": float(ANCHOR - 3600)}
    loop = LiveLoop(sim, Publisher(Down(), 100), clock=lambda: clock["t"], sleep=lambda s: None)
    with caplog.at_level(logging.ERROR, logger="simulator.live"):
        for i in range(3):
            clock["t"] = ANCHOR - 3600 + i
            loop.step()
    assert loop.last == ANCHOR - 3598
    assert sum("nie mogę policzyć" in r.getMessage() for r in caplog.records) == 1


def write_config(tmp_path, raw):
    import yaml

    path = tmp_path / "devices.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return str(path)


def test_main_without_dates_exits_with_code_2(make_raw, tmp_path, monkeypatch, caplog):
    # daty jawnie null (config sprzed k7); plik z repo ma daty od k7, więc main() wszedłby w pętlę na żywo i test by wisiał
    monkeypatch.setenv("DEVICES_CONFIG", write_config(tmp_path, make_raw(meter_anchor=None, bearing=None)))
    monkeypatch.setenv("SIM_CACHE", "")
    with caplog.at_level(logging.ERROR, logger="simulator"):
        assert sim_main.main() == 2
    assert any("meter_anchor" in r.getMessage() for r in caplog.records)


def test_main_without_mqtt_account_keeps_running_and_logs_once(make_raw, tmp_path, monkeypatch, caplog):
    """K3-D1: brak konta nie kończy procesu (bez pętli restartów); błąd w logu, transport ponawia połączenie."""
    from datetime import datetime, timezone

    anchor = datetime.fromtimestamp(ANCHOR, timezone.utc)
    monkeypatch.setenv("DEVICES_CONFIG", write_config(tmp_path, make_raw(meter_anchor=anchor)))
    monkeypatch.setenv("SIM_CACHE", str(tmp_path / "cache.json"))
    monkeypatch.setenv("HEALTH_FILE", str(tmp_path / "health"))
    monkeypatch.delenv("MQTT_USER", raising=False)
    monkeypatch.delenv("MQTT_PASSWORD", raising=False)
    started = {}

    class FakeTransport(Down):
        def __init__(self, host, port, user, password, client_id):
            started["user"] = user

    def one_step(self, stop):
        self.clock = lambda: float(ANCHOR + 86400 + 31)
        self.step()

    monkeypatch.setattr(sim_main, "PahoTransport", FakeTransport)
    monkeypatch.setattr(LiveLoop, "run", one_step)
    monkeypatch.setattr(sim_main.time, "time", lambda: float(ANCHOR + 86400 + 30))
    with caplog.at_level(logging.INFO, logger="simulator"):
        assert sim_main.main() == 0
    assert started["user"] == ""
    assert sum("brak konta MQTT symulatora" in r.getMessage() for r in caplog.records) == 1
    assert health.check(str(tmp_path / "health"))


def test_health_marker(tmp_path):
    marker = str(tmp_path / "h")
    assert not health.check(marker)
    health.touch(marker)
    assert health.check(marker) and not health.check(marker, max_age_s=-1)
