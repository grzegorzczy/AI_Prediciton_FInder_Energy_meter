"""Sekcja `simulator` w config/devices.yaml (E3-k2): wczytanie, walidacja parametrów, t_zero (K1-U2), zgodność z ingestem."""
from __future__ import annotations

import math

import pytest

from dbtools import REPO
from simulator.config import T_ZERO_MISSING, ConfigError, load_config, load_config_dict
from simulator.samples import Simulator

SIM_IDS = ["sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka", "sim_pump_p101"]


def test_real_file_loads_with_five_devices_and_no_t_zero():
    config = load_config(REPO / "config" / "devices.yaml")
    assert [d.device_id for d in config.devices] == SIM_IDS
    assert [d.model_type for d in config.devices] == ["thermostat", "compressor", "batch", "continuous", "pump"]
    assert config.t_zero is None and config.seed == 20261126 and (config.site, config.line) == ("zaklad1", "linia2")
    assert str(config.calendar.timezone) == "Europe/Warsaw"
    assert (config.history.meter_days, config.history.pump_step_s) == (14, 60)
    assert (config.degradation.days_total, config.degradation.history_progress, config.degradation.shape_k) == (120, 0.70, 3.0)
    meters = [d for d in config.devices if d.kind == "energy_meter"]
    assert all(d.phases == 3 and d.energy_resolution_wh == 100 for d in meters)
    assert [d.energy_start_wh for d in meters] == [1250000, 2480000, 610000, 390000]
    pump = config.device("sim_pump_p101")
    assert pump.params["current_a"] == 21 and pump.params["speed_rpm"] == 2950 and pump.params["flow_m3_h"] == 40
    assert (pump.params["warmup_tau_min"], pump.params["cooldown_tau_min"]) == (25, 40)


def test_missing_t_zero_stops_the_simulator_with_a_clear_message():
    """K1-U2: przy t_zero: null nic nie podstawia „teraz”; tryb na żywo i historia nie wystartują."""
    config = load_config(REPO / "config" / "devices.yaml")
    with pytest.raises(ConfigError) as error:
        config.require_t_zero()
    assert str(error.value) == T_ZERO_MISSING and "k7" in str(error.value)
    with pytest.raises(ConfigError):
        Simulator(config)


@pytest.mark.parametrize("value, fragment", [
    ("2026-12-01T00:00:00", "bez strefy"),
    ("2026-12-01", "bez strefy"),
    ("wczoraj", "ISO 8601"),
    ("2026-12-01T00:00:30Z", "pełna minuta"),
    (12345, "ISO 8601"),
])
def test_bad_t_zero_is_rejected(make_raw, value, fragment):
    with pytest.raises(ConfigError, match=fragment):
        load_config_dict(make_raw(t_zero=value))


def test_t_zero_with_offset_is_accepted(make_raw):
    config = load_config_dict(make_raw(t_zero="2026-12-01T01:00:00+01:00"))
    assert config.require_t_zero().timestamp() == load_config_dict(make_raw()).require_t_zero().timestamp()


def dev(raw, index):
    return raw["simulator"]["devices"][index]


@pytest.mark.parametrize("mutate, fragment", [
    (lambda r: dev(r, 0)["model"].update(type="piec"), "nieznany typ"),
    (lambda r: dev(r, 0)["model"].pop("cycle_s"), "cycle_s"),
    (lambda r: dev(r, 0)["model"].update(p_on_kw=-18), "dodatnia"),
    (lambda r: dev(r, 0)["model"].update(p_on_kw=math.nan), "skończoną"),
    (lambda r: dev(r, 0)["model"].update(p_on_kw="dużo"), "nie jest liczbą"),
    (lambda r: dev(r, 0)["model"].update(on_fraction=1.2), "ułamek"),
    (lambda r: dev(r, 0)["model"].update(pf_run=1.5), "współczynnik mocy"),
    (lambda r: dev(r, 0)["model"].update(extra=1), "nieznane parametry"),
    (lambda r: dev(r, 0)["model"].update(schedule="zawsze"), "schedule"),
    (lambda r: dev(r, 0)["model"].update(type="pump"), "nie pasuje"),
    (lambda r: dev(r, 4)["model"].update(type="thermostat"), "nie pasuje"),
    (lambda r: dev(r, 2)["model"].update(mix_min=8), "mix_min"),
    (lambda r: dev(r, 2)["model"].update(schedule="always"), "wymaga schedule: shifts"),
    (lambda r: dev(r, 4)["model"].update(vibration_end_mm_s=1.0), "vibration_end_mm_s"),
    (lambda r: dev(r, 0).pop("energy_start_wh"), "energy_start_wh"),
    (lambda r: dev(r, 0).update(phases=2), "phases"),
    (lambda r: r["simulator"]["calendar"]["shifts"][0].update(start="25:00"), "HH:MM"),
    (lambda r: r["simulator"]["calendar"]["shifts"][0].update(days=[8]), "dni ISO"),
    (lambda r: r["simulator"]["calendar"]["shifts"][0].update(end="05:00"), "przez północ"),
    (lambda r: r["simulator"]["calendar"]["shifts"].append({"days": [1], "start": "23:00", "end": "23:30"}), "więcej niż jednej"),
    (lambda r: r["simulator"]["calendar"].update(timezone="Europe/Atlantyda"), "strefa"),
    (lambda r: r["simulator"]["calendar"].update(holidays=["31.12.2026"]), "YYYY-MM-DD"),
    (lambda r: r["simulator"].update(poll_interval_s=2.0), "1.0"),
    (lambda r: r["simulator"].pop("seed"), "seed"),
    (lambda r: r["simulator"]["degradation"].update(history_progress=1.0), "history_progress"),
    (lambda r: r["simulator"]["history"].update(meter_days=0), "meter_days"),
    (lambda r: r["simulator"]["devices"].append(dict(r["simulator"]["devices"][0])), "powtórzone id"),
    # przegląd k2, ustalenie 4
    (lambda r: r["simulator"]["calendar"].update(holidays=[__import__("datetime").datetime(2026, 12, 24)]), "samą datę"),
    (lambda r: r["simulator"]["calendar"].update(holiday=["2026-12-24"]), "nieznane klucze"),
    (lambda r: r["simulator"].update(seeed=1), "nieznane klucze"),
    (lambda r: dev(r, 0).update(ip="10.0.0.1"), "nieznane klucze"),
    (lambda r: r["simulator"]["calendar"]["breaks"].append({"start": "10:05", "minutes": 5}), "nakładają"),
    (lambda r: dev(r, 0)["model"].update(p_on_kw="18"), "nie jest liczbą"),
    (lambda r: dev(r, 0)["model"].update(cycle_s=60.7), "całkowita"),
    (lambda r: dev(r, 2)["model"].update(batch_min=7.5), "całkowita"),
    (lambda r: r["simulator"]["electrical"].update(voltage_slow_v=50), "±4 %"),
    (lambda r: r["simulator"].update(line="linia1"), "muszą być inne"),
])
def test_invalid_parameters_are_rejected(make_raw, mutate, fragment):
    with pytest.raises(ConfigError) as error:
        load_config_dict(make_raw(mutate))
    assert fragment in str(error.value)


def test_ingest_sees_the_same_devices_and_meta_as_after_k1():
    """Ingest czyta z wpisów sim tylko pola z k1; parametry modeli (k2) nie zmieniają urządzeń ani meta w `devices`."""
    from ingest.config import load_config as load_ingest

    config = load_ingest(REPO / "config" / "devices.yaml")
    sims = {k: v for k, v in config.devices.items() if v.source == "sim"}
    assert list(sims) == SIM_IDS
    assert sims["sim_pasteryzator"].meta == {"poll_interval_s": 1.0, "energy_resolution_wh": 100.0, "phases": 3, "rated_kw": 18.0}
    assert sims["sim_pump_p101"].meta == {"poll_interval_s": 1.0, "rated_kw": 11.0}
    assert all(set(d.meta) <= {"poll_interval_s", "energy_resolution_wh", "phases", "rated_kw"} for d in sims.values())
