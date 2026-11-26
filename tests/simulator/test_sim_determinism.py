"""Determinizm: wartości zależą tylko od chwili, ziarna i configu (zasada K0) – także w nowym procesie i przy innej kolejności."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from sim_support import epoch
from simulator.config import load_config_dict
from simulator.samples import METER_METRICS, PUMP_METRICS, Simulator

MOMENTS = [epoch(2026, 11, 30, 9, 0, 0), epoch(2026, 11, 30, 9, 0, 1), epoch(2026, 11, 28, 3, 0, 0),
           epoch(2026, 12, 6, 12, 0, 0), epoch(2026, 11, 20, 14, 30, 7)]


def snapshot(sim, moments):
    return {t: sim.samples_at(t) for t in moments}


def test_twenty_nine_metrics_with_units(simulator):
    rows = simulator.samples_at(MOMENTS[0])
    assert len(rows) == 29
    pump = [(m, u) for d, m, _, u in rows if d == "sim_pump_p101"]
    assert pump == list(PUMP_METRICS) and ("speed", "rpm") in pump                      # K2-U5
    meter = [(m, u) for d, m, _, u in rows if d == "sim_chlodnia"]
    assert meter == list(METER_METRICS)


def test_same_values_regardless_of_call_order_and_instance(sim_config):
    forward = snapshot(Simulator(sim_config), MOMENTS)
    backward = snapshot(Simulator(sim_config), list(reversed(MOMENTS)))
    assert forward == backward


def test_same_values_in_a_new_python_process(sim_config):
    """Szum z blake2b, nie z hash(): nowy proces (inny PYTHONHASHSEED) daje te same liczby."""
    expected = json.loads(json.dumps(snapshot(Simulator(sim_config), MOMENTS)))
    code = (
        "import json, sys, yaml\n"
        "from simulator.config import load_config_dict\n"
        "from simulator.samples import Simulator\n"
        "raw = yaml.safe_load(open(sys.argv[1], encoding='utf-8'))\n"
        "raw['simulator']['t_zero'] = '2026-12-01T00:00:00Z'\n"
        "sim = Simulator(load_config_dict(raw))\n"
        f"print(json.dumps({{t: sim.samples_at(t) for t in {MOMENTS!r}}}))\n"
    )
    from dbtools import REPO
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    out = subprocess.run([sys.executable, "-c", code, str(REPO / "config" / "devices.yaml")], capture_output=True,
                         text=True, env=env, timeout=120, check=True).stdout
    assert json.loads(out) == expected


def test_other_seed_gives_other_noise(make_raw):
    base = Simulator(load_config_dict(make_raw()))
    other = Simulator(load_config_dict(make_raw(lambda r: r["simulator"].update(seed=1))))
    voltage = lambda sim: [v for d, m, v, _ in sim.samples_at(MOMENTS[0]) if m == "voltage"]
    assert voltage(base) != voltage(other)


def test_values_do_not_depend_on_the_system_clock(sim_config, monkeypatch):
    import time

    before = snapshot(Simulator(sim_config), MOMENTS[:2])
    monkeypatch.setattr(time, "time", lambda: 0.0)
    assert snapshot(Simulator(sim_config), MOMENTS[:2]) == before
