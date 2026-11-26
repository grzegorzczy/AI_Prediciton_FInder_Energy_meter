"""K2R-D3, K3-U4: start liczników energii po 90 i 365 dniach od kotwicy – bez pamięci sum i z plikiem; rozmiar pliku.
Uruchamiany tylko przez tests/run-perf.sh (AIP_PERF=1): przeliczenie 365 dób 4 liczników trwa ok. 20 min."""
from __future__ import annotations

import os
import time
from datetime import timedelta

import pytest

from simulator.samples import Simulator

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(os.environ.get("AIP_PERF") != "1", reason="pomiar wydajności: tests/run-perf.sh"),
]


@pytest.mark.parametrize("days", [90, 365])
def test_start_after_many_days_with_and_without_the_file(sim_config, tmp_path, days):
    t = int((sim_config.require_meter_anchor() + timedelta(days=days)).timestamp()) + 1234
    path = tmp_path / "energy-days.json"
    t0 = time.perf_counter()
    cold = Simulator(sim_config, str(path))
    cold.prime(t)
    cold_s = time.perf_counter() - t0
    t0 = time.perf_counter()
    warm = Simulator(sim_config, str(path))
    warm.prime(t)
    warm_s = time.perf_counter() - t0
    same = all(cold.meters[d][1].value_wh(t) == warm.meters[d][1].value_wh(t) for d in cold.meters)
    print(f"\n[perf] START_{days}D bez_pliku={cold_s:.0f}s z_plikiem={warm_s:.1f}s rozmiar_pliku={path.stat().st_size} B "
          f"zgodne={same} źródło={warm.cache.source}")
    assert same and warm.cache.source == "plik" and warm_s < 30
