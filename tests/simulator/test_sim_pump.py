"""Pompa: postęp degradacji, wartości kontrolne krzywej (K0-D2), koniec krzywej (K2-U1), praca w zmianie (K2-U4), temperatura."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sim_support import T_ZERO, epoch, with_t_zero
from simulator.calendar import CalendarModel
from simulator.pump import PumpModel, curve

WAW = ZoneInfo("Europe/Warsaw")
D = 120 * 86400
# Wartości kontrolne z planu k0/k2 (k = 3): x -> (f(x), drgania mm/s)
CONTROL = {0.25: (0.059, 1.45), 0.5: (0.182, 2.18), 0.7: (0.376, 3.32), 0.85: (0.619, 4.75), 1.0: (1.0, 7.00)}
WORK_HOUR = epoch(2026, 11, 30, 8, 0, 0, tz=WAW)     # poniedziałek 08:00-09:00 czasu lokalnego (praca, bez przerwy)


def pump_for(config, x_at_work_hour: float) -> PumpModel:
    """Pompa z t_zero dobranym tak, by w WORK_HOUR postęp wynosił x (te same chwile = ten sam szum)."""
    t_zero = WORK_HOUR - round((x_at_work_hour - 0.7) * D)
    config = with_t_zero(config, datetime.fromtimestamp(t_zero, timezone.utc))
    return PumpModel(config, config.device("sim_pump_p101"), CalendarModel(config.calendar, config.ambient))


def hour_mean(pump, metric, start=WORK_HOUR, seconds=3600):
    return sum(pump.sample(t)[metric] for t in range(start, start + seconds)) / seconds


def test_progress_is_0_70_at_t_zero(sim_config):
    pump = PumpModel(sim_config, sim_config.device("sim_pump_p101"), CalendarModel(sim_config.calendar, sim_config.ambient))
    assert pump.progress(T_ZERO.timestamp()) == pytest.approx(0.70)
    assert pump.progress(T_ZERO.timestamp() - 0.70 * D) == pytest.approx(0.0)
    assert pump.progress(T_ZERO.timestamp() - 0.70 * D - 86400) == 0.0


@pytest.mark.parametrize("x", sorted(CONTROL))
def test_control_values_of_the_curve_and_vibration(sim_config, x):
    f_expected, vib_expected = CONTROL[x]
    assert curve(x, 3.0) == pytest.approx(f_expected, abs=0.0006)
    mean = hour_mean(pump_for(sim_config, x), "vibration_rms")
    print(f"\nDRGANIA x={x} {mean:.2f} mm/s (kontrolnie {vib_expected})")
    assert mean == pytest.approx(vib_expected, rel=0.04)          # szum ±2,5 % i wolne wahanie ±3 % w średniej godziny


def test_daily_vibration_grows_over_the_curve(sim_config):
    means = [hour_mean(pump_for(sim_config, x), "vibration_rms", seconds=600) for x in (0.1, 0.3, 0.5, 0.7, 0.9, 1.0)]
    assert all(b > a for a, b in zip(means, means[1:]))


def test_after_the_end_of_the_curve_values_stay_as_at_x_1_and_warn_once(sim_config, caplog):
    """K2-U1: x = 1,2 daje te same wartości co x = 1, a WARNING pojawia się raz (na model pompy w procesie)."""
    at_end, beyond = pump_for(sim_config, 1.0), pump_for(sim_config, 1.2)
    samples_end = [at_end.sample(t) for t in range(WORK_HOUR, WORK_HOUR + 120)]
    caplog.clear()                                       # ostrzeżenie modelu at_end (x tuż powyżej 1) nie liczy się tutaj
    with caplog.at_level(logging.WARNING, logger="simulator.pump"):
        samples_beyond = [beyond.sample(t) for t in range(WORK_HOUR, WORK_HOUR + 120)]
        samples_beyond_again = [beyond.sample(t) for t in range(WORK_HOUR, WORK_HOUR + 120)]
    assert beyond.progress(WORK_HOUR) == 1.0
    assert samples_beyond == samples_beyond_again
    assert [s["vibration_rms"] for s in samples_beyond] == [s["vibration_rms"] for s in samples_end]
    assert [s["motor_current"] for s in samples_beyond] == [s["motor_current"] for s in samples_end]
    warnings = [r for r in caplog.records if "koniec krzywej" in r.getMessage()]
    assert len(warnings) == 1


def test_pump_runs_through_breaks_and_stands_outside_shifts(simulator):
    pump = simulator.pumps["sim_pump_p101"]
    brk = epoch(2026, 11, 30, 13, 40, 0, tz=WAW)
    assert pump.sample(brk)["speed"] > 2800 and pump.sample(brk)["flow"] > 30           # K2-U4: także w przerwie
    night = epoch(2026, 11, 30, 23, 30, 0, tz=WAW)
    s = pump.sample(night)
    assert (s["speed"], s["flow"], s["motor_current"]) == (0.0, 0.0, 0.0) and s["vibration_rms"] < 0.2


def test_motor_current_rises_five_percent_at_the_end_of_the_curve(sim_config):
    """K2-U4: wariant przyjęty w k2 – prąd +5 % przy x = 1 (te same chwile, więc ten sam szum)."""
    start = pump_for(sim_config, 0.0)
    end = pump_for(sim_config, 1.0)
    ratio = hour_mean(end, "motor_current", seconds=600) / hour_mean(start, "motor_current", seconds=600)
    assert ratio == pytest.approx(1.05, abs=0.003)


def test_bearing_temperature_rises_with_wear_heats_up_and_cools_down(simulator, sim_config):
    pump = simulator.pumps["sim_pump_p101"]
    # Dzień t_zero (wtorek 01.12): po nagrzaniu, bez odchylenia otoczenia od średniej (09:00 lokalnie = 20 °C)
    steady = epoch(2026, 12, 1, 9, 0, 0, tz=WAW)
    expected = 52 + 26 * curve(pump.progress(steady), 3.0)
    assert pump.bearing_temperature_model(steady) == pytest.approx(expected, abs=0.05)
    assert expected == pytest.approx(61.8, abs=0.1)
    assert hour_mean(pump, "bearing_temperature", steady, 600) == pytest.approx(61.8, abs=1.5)
    start = epoch(2026, 12, 1, 6, 0, 0, tz=WAW)
    assert pump.bearing_temperature_model(start + 300) < pump.bearing_temperature_model(start + 5400)   # nagrzewanie
    stop = epoch(2026, 12, 1, 22, 0, 0, tz=WAW)
    assert pump.bearing_temperature_model(stop + 300) > pump.bearing_temperature_model(stop + 5400)    # stygnięcie
    assert pump.bearing_temperature_model(stop + 6 * 3600) == pytest.approx(simulator.calendar.ambient_c(stop + 6 * 3600), abs=0.5)
