"""K3-U1: MODEL_VERSION pilnowany wartościami wzorcowymi.

Wzorce (sumy W·s jednej doby każdego licznika i kilka próbek pompy) są zapisane razem z wersją modelu. Gdy wynik modelu
zmieni się przy tej samej wersji, test jest czerwony: trzeba podbić MODEL_VERSION (unieważnia pamięć sum dobowych w
plikach) i zaktualizować wzorce poniżej.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from sim_support import epoch
from simulator import MODEL_VERSION

WAW = ZoneInfo("Europe/Warsaw")
GOLDEN_VERSION = "2026-11-26.1"
# doba 13 od kotwicy 17.11.2026 = 30.11.2026 00:00–24:00 UTC (poniedziałek roboczy) [W·s]
GOLDEN_DAY_13_WS = {"sim_pasteryzator": 692382630, "sim_chlodnia": 515645608, "sim_mieszalnik": 234622483,
                    "sim_pakowaczka": 179509450}
GOLDEN_PUMP = {
    epoch(2026, 11, 30, 8, 0, 0, tz=WAW): {"vibration_rms": 3.23, "bearing_temperature": 60.4, "motor_current": 18.53,
                                           "flow": 35.2, "speed": 2968.0},
    epoch(2026, 11, 30, 23, 30, 0, tz=WAW): {"vibration_rms": 0.06, "bearing_temperature": 22.8, "motor_current": 0.0,
                                             "flow": 0.0, "speed": 0.0},
    epoch(2026, 12, 1, 9, 0, 0, tz=WAW): {"vibration_rms": 3.54, "bearing_temperature": 61.7, "motor_current": 18.42,
                                          "flow": 34.9, "speed": 2959.0},
}
HINT = "wynik modelu zmienił się przy tej samej MODEL_VERSION: podbij MODEL_VERSION (simulator/__init__.py) i zaktualizuj wzorce"


def test_golden_values_match_the_model_version(simulator):
    if MODEL_VERSION != GOLDEN_VERSION:
        raise AssertionError(f"MODEL_VERSION {MODEL_VERSION} != wzorce {GOLDEN_VERSION}: zaktualizuj wzorce w tym pliku")
    days = {dev: counter.compute_day(13) for dev, (_, counter) in simulator.meters.items()}
    assert days == GOLDEN_DAY_13_WS, HINT
    pump = simulator.pumps["sim_pump_p101"]
    assert {t: pump.sample(t) for t in GOLDEN_PUMP} == GOLDEN_PUMP, HINT


def test_model_version_is_part_of_the_cache_key(sim_config, monkeypatch):
    import simulator.daycache as daycache

    before = daycache.cache_key(sim_config)
    monkeypatch.setattr(daycache, "MODEL_VERSION", "inna")
    assert daycache.cache_key(sim_config) != before
