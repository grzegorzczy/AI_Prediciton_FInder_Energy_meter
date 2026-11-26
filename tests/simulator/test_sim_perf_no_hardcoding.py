"""Koszt liczenia (K2-U3) i reguła 3 dla symulatora (brak danych urządzeń w kodzie)."""
from __future__ import annotations

import time

from sim_support import epoch
from dbtools import REPO
from simulator.samples import Simulator

SOURCE_DIR = REPO / "services" / "simulator"


def test_cost_of_one_meter_day_and_of_a_cold_energy_start(sim_config):
    """K2-U3: koszt jednej doby (86 400 próbek mocy) i startu licznika 14 dni po kotwicy; prognoza 30/90/365 dni w wydruku."""
    sim = Simulator(sim_config)
    meter, counter = sim.meters["sim_pasteryzator"]
    start = epoch(2026, 11, 30)
    t0 = time.perf_counter()
    for t in range(start, start + 86400):
        meter.power(t)
    one_day = time.perf_counter() - t0
    t0 = time.perf_counter()
    counter.value_wh(counter.anchor + 14 * 86400)
    cold14 = time.perf_counter() - t0
    sim.samples_at(start)                                  # rozgrzewka: start liczników energii (koszt liczony wyżej)
    t0 = time.perf_counter()
    for t in range(start + 1, start + 601):
        sim.samples_at(t)
    per_tick = (time.perf_counter() - t0) / 600
    four = 4 * one_day
    print(f"\nKOSZT doba_1_licznik={one_day:.2f}s start_14d_1_licznik={cold14:.2f}s tick_29_metryk={per_tick * 1000:.2f}ms "
          f"prognoza_4_liczniki: 14d={14 * four:.0f}s 30d={30 * four:.0f}s 90d={90 * four:.0f}s 365d={365 * four:.0f}s "
          f"historia_14d_co_1s={14 * 86400 * per_tick / 3600:.1f}h")
    assert one_day < 10.0 and per_tick < 0.1


def test_no_device_data_in_simulator_code():
    offenders = []
    sources = list(SOURCE_DIR.rglob("*.py"))
    assert len(sources) >= 8
    for path in sources:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for token in ("sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka", "sim_pump", "P-101",
                          "zaklad1", "linia1", "linia2", "Europe/Warsaw", "2950", "20261126"):
                if token in line:
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {token}")
    assert offenders == []
