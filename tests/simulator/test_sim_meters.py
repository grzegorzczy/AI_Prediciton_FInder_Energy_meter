"""Wirtualne liczniki: moc w stanach kalendarza, elektryka (trójfazowe, U-1) i energia dobowa (K2-D2)."""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pytest

from sim_support import epoch

WAW = ZoneInfo("Europe/Warsaw")
# Przedziały energii doby roboczej z planu k2 (test spójności parametrów, K2-D2) [kWh]
DAILY_RANGES = {"sim_pasteryzator": (170, 210), "sim_chlodnia": (120, 160), "sim_mieszalnik": (50, 80), "sim_pakowaczka": (35, 55)}


def local(*args):
    return epoch(*args, tz=WAW)


def meter(simulator, dev_id):
    return simulator.meters[dev_id][0]


def model_kw(simulator, dev_id, t):
    return meter(simulator, dev_id).model_power(t)[0] / 1000.0


def test_power_in_off_break_and_work_states(simulator):
    night, brk, work = local(2026, 11, 30, 3, 0, 0), local(2026, 11, 30, 13, 40, 0), local(2026, 11, 30, 11, 0, 0)
    assert model_kw(simulator, "sim_pasteryzator", night) == 0.15
    assert model_kw(simulator, "sim_pasteryzator", brk) == 2.5
    assert {model_kw(simulator, "sim_pasteryzator", work + s) for s in range(60)} == {18.0, 2.5}   # K2-U6: p_idle w fazie wyłączonej
    assert model_kw(simulator, "sim_pakowaczka", night) == 0.12 and model_kw(simulator, "sim_pakowaczka", brk) == 0.9
    assert 3.2 * 0.85 <= model_kw(simulator, "sim_pakowaczka", work) <= 3.2 * 1.15
    assert model_kw(simulator, "sim_mieszalnik", night) == 0.05 and model_kw(simulator, "sim_mieszalnik", brk) == 0.3
    sunday = local(2026, 12, 6, 12, 0, 0)
    assert {model_kw(simulator, "sim_chlodnia", sunday + s) for s in range(0, 23 * 60, 30)} == {9.5, 0.4}   # chłodnia 24/7


def test_thermostat_duty_cycle_within_a_shift(simulator):
    start = local(2026, 11, 30, 6, 30, 0)
    on = sum(model_kw(simulator, "sim_pasteryzator", start + s) == 18.0 for s in range(3 * 3600))
    assert on / (3 * 3600) == pytest.approx(0.65, abs=0.02)


def test_batch_has_ramp_mixing_and_pause_from_shift_start(simulator):
    start = local(2026, 11, 30, 6, 0, 0)
    values = [model_kw(simulator, "sim_mieszalnik", start + s) for s in range(8 * 60)]
    assert values[0] == pytest.approx(0.3) and values[10] == pytest.approx(0.3 + 5.5 * 0.5)
    assert values[30] == pytest.approx(5.8) and values[6 * 60 - 1] == pytest.approx(5.8) and values[6 * 60] == pytest.approx(0.3)


def test_compressor_runs_longer_in_the_warm_afternoon(simulator):
    def on_share(hour):
        start = local(2026, 11, 30, hour, 0, 0)
        return sum(model_kw(simulator, "sim_chlodnia", start + s) == 9.5 for s in range(0, 3 * 3600, 5)) / (3 * 3600 / 5)
    assert on_share(14) > on_share(2) + 0.05


def test_electrical_quantities_are_consistent(simulator):
    start = local(2026, 11, 30, 0, 0, 0)
    for t in range(start, start + 86400, 37):
        rows = {(d, m): v for d, m, v, _ in simulator.samples_at(t) if d != "sim_pump_p101"}
        for dev in DAILY_RANGES:
            p, q, u, i, pf = (rows[(dev, m)] for m in ("active_power", "reactive_power", "voltage", "current", "power_factor"))
            assert all(math.isfinite(v) for v in (p, q, u, i, pf))
            assert p >= 0 and q >= 0 and 0 < pf <= 1 and 220 <= u <= 240
            s = p / pf
            assert math.isclose(q, math.sqrt(max(s * s - p * p, 0)), abs_tol=1.0)
            assert math.isclose(i, s / (3 * u), rel_tol=1e-3, abs_tol=0.002)   # trójfazowy (U-1); U i I zaokrąglone w danych


def daily_energy_kwh(simulator, dev_id, start):
    power = meter(simulator, dev_id).power
    return sum(power(t)[0] for t in range(start, start + 86400)) / 3600.0 / 1000.0


@pytest.mark.parametrize("dev_id", sorted(DAILY_RANGES))
def test_daily_energy_of_a_working_day_is_in_the_planned_range(simulator, dev_id):
    """K2-D2: poniedziałek 30.11.2026 (doba robocza: 15 h pracy, 1 h przerw, 8 h postoju). Wynik w wydruku (-s) do raportu."""
    kwh = daily_energy_kwh(simulator, dev_id, local(2026, 11, 30, 0, 0, 0))
    low, high = DAILY_RANGES[dev_id]
    print(f"\nENERGIA_DOBOWA {dev_id} {kwh:.1f} kWh (przedział {low}-{high})")
    assert low <= kwh <= high
