"""Licznik energii licznika wirtualnego: kotwica, monotoniczność, kwant 100 Wh, zgodność z całką mocy, ciągłość."""
from __future__ import annotations

import math

import pytest

from sim_support import epoch
from simulator.samples import Simulator

ANCHOR = epoch(2026, 11, 17)          # meter_anchor testów (wdrożenie 01.12.2026 − 14 dni)


def counter(simulator, dev_id="sim_pakowaczka"):
    return simulator.meters[dev_id][1]


def test_anchor_and_start_value(simulator):
    c = counter(simulator)
    assert c.anchor == ANCHOR
    assert c.value_wh(ANCHOR) == 390000.0
    with pytest.raises(ValueError):
        c.value_wh(ANCHOR - 1)


def test_monotonic_and_quantised_to_100_wh(sim_config):
    c = counter(Simulator(sim_config), "sim_mieszalnik")
    start = epoch(2026, 11, 30, 5)
    values = [c.value_wh(t) for t in range(start, start + 4 * 3600, 7)]
    assert all(b >= a for a, b in zip(values, values[1:]))
    assert all(v % 100 == 0 for v in values)
    assert values[-1] > values[0]


def test_daily_increase_matches_the_integral_of_published_power(sim_config):
    sim = Simulator(sim_config)
    meter, c = sim.meters["sim_pasteryzator"]
    day = epoch(2026, 11, 30)
    integral = sum(meter.power(t)[0] for t in range(day, day + 86400)) / 3600.0
    assert abs((c.value_wh(day + 86400) - c.value_wh(day)) - integral) < 100.0
    assert c.integral_wh(day + 86400) - c.integral_wh(day) == pytest.approx(integral, abs=1e-6)


def test_sequential_and_random_access_give_the_same_value(sim_config):
    """Pamięć ostatniej wartości (odczyty po kolei) i sumy dobowe (start po N dobach) to tylko przyspieszenie."""
    day_boundary = ANCHOR + 13 * 86400
    sequential = Simulator(sim_config).meters["sim_chlodnia"][1]
    for t in range(day_boundary - 600, day_boundary + 600):
        sequential.value_wh(t)
    random = Simulator(sim_config).meters["sim_chlodnia"][1]
    for t in (day_boundary - 1, day_boundary, day_boundary + 599):
        assert random.integral_wh(t) == pytest.approx(sequential.integral_wh(t), abs=1e-6)
        assert math.isclose(random.value_wh(t), sequential.value_wh(t))



def test_integral_is_exact_integer_watt_seconds_on_both_paths(sim_config):
    """Przegląd k2, ustalenie 3: suma W·s w liczbach całkowitych – ścieżka „po kolei” i „sumy dobowe” są identyczne."""
    boundary = ANCHOR + 13 * 86400
    sequential = Simulator(sim_config).meters["sim_mieszalnik"][1]
    for t in range(boundary - 3000, boundary + 3000, 1):
        sequential.integral_ws(t)
    random = Simulator(sim_config).meters["sim_mieszalnik"][1]
    for t in (boundary - 1, boundary, boundary + 2999):
        assert isinstance(random.integral_ws(t), int)
        assert random.integral_ws(t) == sequential.integral_ws(t)
        assert random.value_wh(t) == sequential.value_wh(t)
