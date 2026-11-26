"""Pamięć sum dobowych w pliku (K2R-D3): identyczność z rachunkiem, klucz, kontrola ostatniej doby, odporność, zapis atomowy."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import time

import pytest

from sim_support import epoch
from simulator.config import load_config_dict
from simulator.daycache import DayCache, cache_key
from simulator.samples import Simulator

ANCHOR = epoch(2026, 11, 17)
T = ANCHOR + 13 * 86400 + 4321          # 13 pełnych dób po kotwicy


def values(sim, t=T):
    return {d: c.value_wh(t) for d, (_, c) in sim.meters.items()}


def test_values_with_and_without_the_file_are_identical(sim_config, tmp_path):
    path = tmp_path / "energy-days.json"
    cold = Simulator(sim_config, str(path))
    t0 = time.perf_counter()
    first = values(cold)
    cold_s = time.perf_counter() - t0
    cold.cache.flush()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == 1 and data["key"] == cache_key(sim_config)
    assert all(len(days) == 13 for days in data["devices"].values())
    t0 = time.perf_counter()
    warm = Simulator(sim_config, str(path))
    second = values(warm)
    warm_s = time.perf_counter() - t0
    print(f"\nSTART_14D bez_pliku={cold_s:.1f}s z_plikiem={warm_s:.1f}s (z kontrolą ostatniej doby) rozmiar={path.stat().st_size} B")
    assert warm.cache.source == "plik" and first == second
    assert warm_s < cold_s


@pytest.mark.parametrize("change", [
    lambda r: r["simulator"].update(seed=7),
    lambda r: r["simulator"].update(meter_anchor="2026-11-16T00:00:00Z"),
    lambda r: r["simulator"]["devices"][0]["model"].update(p_on_kw=17),
    lambda r: r["simulator"]["calendar"].update(holidays=["2026-11-20"]),
])
def test_other_key_means_recalculation(make_raw, tmp_path, change):
    path = tmp_path / "energy-days.json"
    base = load_config_dict(make_raw())
    sim = Simulator(base, str(path))
    values(sim, ANCHOR + 2 * 86400)
    sim.cache.flush()
    other = load_config_dict(make_raw(change))
    assert cache_key(other) != cache_key(base)
    assert Simulator(other, str(path)).cache.source == "inny klucz"


def test_forged_last_day_is_detected_and_the_file_rejected(sim_config, tmp_path, caplog):
    path = tmp_path / "energy-days.json"
    sim = Simulator(sim_config, str(path))
    expected = values(sim, ANCHOR + 3 * 86400)
    sim.cache.flush()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["devices"]["sim_chlodnia"]["2"] += 3600                         # +1 Wh w ostatniej zapisanej dobie
    path.write_text(json.dumps(data), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="simulator.daycache"):
        again = Simulator(sim_config, str(path))
    assert again.cache.source == "niezgodna – odrzucona"
    assert any("niezgodna" in r.getMessage() for r in caplog.records)
    assert values(again, ANCHOR + 3 * 86400) == expected


@pytest.mark.parametrize("content", ["{nie json", "[]", '{"format": 1, "key": "%s", "devices": {"x": [1]}}'])
def test_broken_file_means_recalculation_not_an_error(sim_config, tmp_path, content):
    path = tmp_path / "energy-days.json"
    path.write_text(content.replace("%s", cache_key(sim_config)), encoding="utf-8")
    sim = Simulator(sim_config, str(path))
    assert sim.cache.source in ("plik uszkodzony", "inny klucz")
    assert values(sim, ANCHOR + 86400 + 5) == values(Simulator(sim_config), ANCHOR + 86400 + 5)


def test_unwritable_location_is_a_warning_not_an_error(sim_config, tmp_path, caplog):
    blocker = tmp_path / "plik"
    blocker.write_text("x", encoding="utf-8")
    sim = Simulator(sim_config, str(blocker / "energy-days.json"))      # katalog nadrzędny jest plikiem
    values(sim, ANCHOR + 86400 + 5)
    with caplog.at_level(logging.WARNING, logger="simulator.daycache"):
        assert sim.cache.flush() is False
    assert any("nie mogę zapisać" in r.getMessage() for r in caplog.records)


def test_interrupted_write_keeps_the_previous_file(sim_config, tmp_path, monkeypatch):
    path = tmp_path / "energy-days.json"
    sim = Simulator(sim_config, str(path))
    values(sim, ANCHOR + 86400 + 5)
    sim.cache.flush()
    before = path.read_bytes()
    sim.cache.put("sim_chlodnia", 99, 1)
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("przerwany zapis")))
    assert sim.cache.flush() is False
    assert path.read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".energy-days-")]      # plik tymczasowy usunięty


def test_sequential_reading_derives_day_sums_without_recalculation(sim_config):
    """W trybie na żywo suma doby powstaje z dwóch kolejnych początków dób (bez ponownego liczenia 86 400 sekund)."""
    sim = Simulator(sim_config, None)
    _, counter = sim.meters["sim_pakowaczka"]
    boundary = ANCHOR + 2 * 86400
    counter.value_wh(ANCHOR + 86400 - 3)
    for t in range(ANCHOR + 86400 - 2, boundary + 3):
        counter.value_wh(t)
    assert counter._day_sums[1] == counter.compute_day(1)
    assert counter._day_sums[0] == counter.compute_day(0)


def test_cache_key_ignores_pump_and_energy_start(make_raw):
    """Klucz dotyczy sum mocy liczników: zmiana pompy ani stanu początkowego licznika go nie zmienia."""
    base = load_config_dict(make_raw())
    pump = load_config_dict(make_raw(lambda r: r["simulator"]["devices"][4]["model"].update(current_a=22)))
    start = load_config_dict(make_raw(lambda r: r["simulator"]["devices"][0].update(energy_start_wh=1)))
    assert cache_key(base) == cache_key(pump) == cache_key(start)
