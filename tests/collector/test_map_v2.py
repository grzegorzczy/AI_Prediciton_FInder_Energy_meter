"""Mapa Modbus v2 (E2-PLC2, krok 2): v1 i v2 jednocześnie, pola 44-59, ważność, zakresy, przełączanie w locie."""
from __future__ import annotations

import pytest

from collector.codec import Registers
from collector.config import ConfigError, load_config_dict
from collector.evaluator import Evaluator
from collector.status import LinkStatus
from fakes.modbus_plc import build_image

KEY = "meter:finder_7m24_1"
DEV = "finder_7m24_1"
V2_METRICS = {"reactive_pos_varh", "reactive_neg_varh", "thd_voltage", "thd_current", "phase_angle", "meter_temperature", "run_time"}
V1_METRICS = {
    "meter_error_count", "meter_data_age_ms", "meter_status", "active_power", "reactive_power", "apparent_power",
    "power_factor", "frequency", "voltage", "current", "energy_import_wh", "energy_export_wh",
}


def image(config, heartbeat=1, map_version=2, v2=None, **meter) -> Registers:
    words = build_image(heartbeat=heartbeat, map_version=map_version, meters=((10, meter),), v2=v2)
    return Registers(config.plc.read_start, words[: config.plc.read_count])


def values(evaluation):
    return {(r.device_id, r.metric): r.value for r in evaluation.readings}


def units(evaluation):
    return {r.metric: r.unit for r in evaluation.readings if r.device_id == DEV}


def warmed_up(config, clock, version=2, **meter):
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(image(config, heartbeat=1, map_version=version, **meter))
    first = evaluator.evaluate(image(config, heartbeat=2, map_version=version, **meter))
    assert first.link_status == LinkStatus.OK
    return evaluator, first


def test_v2_publishes_all_new_values_decoded_from_the_registers(config, clock):
    _, result = warmed_up(config, clock)
    got = values(result)
    assert {m for (d, m) in got if d == DEV} == V1_METRICS | V2_METRICS
    assert len(result.readings) == 20                                      # 1 link_status + 12 (v1) + 7 (v2)
    assert got[(DEV, "thd_voltage")] == 2.34
    assert got[(DEV, "thd_current")] == 140.22
    assert got[(DEV, "phase_angle")] == -50.58                             # ujemny kąt jest poprawną wartością (Q < 0)
    assert got[(DEV, "meter_temperature")] == 30.2
    assert got[(DEV, "run_time")] == 1256171.0
    assert got[(DEV, "reactive_pos_varh")] == 0.0 and got[(DEV, "reactive_neg_varh")] == 4500.0   # mantysa x 10^wykładnik
    assert units(result)["thd_current"] == "%" and units(result)["phase_angle"] == "°"
    assert units(result)["meter_temperature"] == "°C" and units(result)["run_time"] == "s"
    assert units(result)["reactive_neg_varh"] == "varh"


def test_v1_publishes_no_v2_metric_even_when_the_registers_hold_values(config, clock):
    """Wersja 1 z „śmieciami” w rejestrach 44-59: żadna metryka v2 nie może trafić do bazy."""
    _, result = warmed_up(config, clock, version=1, v2=True)
    assert {m for (d, m) in values(result) if d == DEV} == V1_METRICS
    assert len(result.readings) == 13


def test_v1_image_with_zeros_in_the_new_registers_is_the_unchanged_v1_behaviour(config, clock):
    _, result = warmed_up(config, clock, version=1)
    assert len(result.readings) == 13 and result.map_version == 1


@pytest.mark.parametrize("version", [0, 3, 4, 255, 65535])
def test_any_other_version_gives_link_status_3_and_only_the_status(config, clock, version):
    result = Evaluator(config, clock).evaluate(image(config, map_version=version))
    assert result.link_status == LinkStatus.MAP_VERSION_MISMATCH
    assert [(r.metric, r.value) for r in result.readings] == [("link_status", 3.0)]


def test_v2_values_are_not_published_unless_the_meter_is_ok(config, clock):
    evaluator, _ = warmed_up(config, clock)
    failing = evaluator.evaluate(image(config, heartbeat=3, status=1, error_code=162, error_count=2, data_age_ms=1000))
    metrics = {r.metric for r in failing.readings}
    assert not (metrics & V2_METRICS)                                       # zamrożone wartości v2 nie są zapisywane
    assert len(failing.readings) == 5                                       # model 5 wierszy na sekundę błędu bez zmian
    no_data = evaluator.evaluate(image(config, heartbeat=4, status=2, data_age_ms=0xFFFFFFFF))
    assert not ({r.metric for r in no_data.readings} & V2_METRICS)
    mismatch = evaluator.evaluate(image(config, heartbeat=5, serial="X9999999"))
    assert not ({r.metric for r in mismatch.readings} & V2_METRICS) and mismatch.states[KEY] == "SERIAL_MISMATCH"
    back = evaluator.evaluate(image(config, heartbeat=6))
    assert len(back.readings) == 20                                         # po powrocie do OK znów komplet


def test_value_outside_valid_range_is_skipped_but_valid_ones_are_published(config, clock):
    evaluator, _ = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, thd_voltage=1e38, phase_angle=-181.0, meter_temperature=-60.0,
                                      thd_current=1500.0, run_time=-1.0))
    got = values(result)
    for metric in ("thd_voltage", "phase_angle", "meter_temperature", "thd_current", "run_time"):
        assert (DEV, metric) not in got, metric
    assert len(result.skipped) == 5 and all("spoza zakresu" in item for item in result.skipped)
    assert (DEV, "reactive_neg_varh") in got and (DEV, "voltage") in got
    edge = evaluator.evaluate(image(config, heartbeat=4, thd_voltage=100.0, phase_angle=-180.0, meter_temperature=150.0,
                                    thd_current=0.0, run_time=0.0))
    assert not edge.skipped and (DEV, "thd_voltage") in values(edge)       # granice zakresu są włączone


def test_nan_in_a_v2_channel_is_skipped_like_in_v1(config, clock):
    evaluator, _ = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, thd_current=float("nan")))
    assert (DEV, "thd_current") not in values(result) and result.skipped == [f"{DEV}.thd_current"]


def test_switch_v1_to_v2_to_v1_in_flight_without_losing_the_link(config, clock):
    """Zmiana map_version między cyklami (bez zerwania połączenia): INFO w main, nowa rozgrzewka, pola v2 pojawiają się i znikają."""
    evaluator, first = warmed_up(config, clock, version=1)
    assert len(first.readings) == 13 and first.map_version == 1
    warm = evaluator.evaluate(image(config, heartbeat=3, map_version=2))
    assert warm.link_status is None and warm.map_version == 2               # nowa rozgrzewka po zmianie wersji
    ok_v2 = evaluator.evaluate(image(config, heartbeat=4, map_version=2))
    assert ok_v2.link_status == LinkStatus.OK and len(ok_v2.readings) == 20
    warm_back = evaluator.evaluate(image(config, heartbeat=5, map_version=1))
    assert warm_back.link_status is None
    ok_v1 = evaluator.evaluate(image(config, heartbeat=6, map_version=1))
    assert len(ok_v1.readings) == 13 and not ({r.metric for r in ok_v1.readings} & V2_METRICS)


def test_download_cycle_offline_warmup_then_v2(config, clock):
    """Po downloadzie PLC: zerwanie połączenia, rozgrzewka, powrót z inną wersją mapy; heartbeat po restarcie PLC jest mniejszy."""
    evaluator, _ = warmed_up(config, clock, version=1)
    assert evaluator.on_read_failed().link_status == LinkStatus.PLC_OFFLINE
    assert evaluator.evaluate(image(config, heartbeat=5, map_version=2)).link_status is None
    result = evaluator.evaluate(image(config, heartbeat=6, map_version=2))
    assert result.link_status == LinkStatus.OK and len(result.readings) == 20 and result.map_version == 2


# ---------------------------------------------------------------------------------------------------- konfiguracja

def test_config_accepts_both_versions_and_marks_the_v2_fields(config):
    assert config.plc.map_versions == (1, 2) and config.plc.read_count == 60
    profile = config.meters[0].profile
    assert {m for m, s in profile.metrics.items() if s.since == 2} == {
        "thd_voltage", "thd_current", "phase_angle", "meter_temperature", "run_time"}
    assert {m for m, s in profile.energy.items() if s.since == 2} == {"reactive_pos_varh", "reactive_neg_varh"}
    assert profile.metrics["thd_current"].valid_range == (0.0, 1000.0)
    assert profile.metrics["phase_angle"].valid_range == (-180.0, 180.0)


@pytest.mark.parametrize("bad", [[], [1, 1], [0], ["1"], [True], 1, [70000]])
def test_invalid_map_versions_are_rejected(make_config, bad):
    with pytest.raises(ConfigError, match="map_versions"):
        make_config(lambda raw: raw["plc"].update(map_versions=bad))


def test_field_since_beyond_the_listed_versions_is_a_configuration_error(make_config):
    with pytest.raises(ConfigError, match="since=2"):
        make_config(lambda raw: raw["plc"].update(map_versions=[1]))


@pytest.mark.parametrize("bad", [[1], [5, 1], ["a", "b"], "0-1", [None, 1]])
def test_invalid_valid_range_is_rejected(make_config, bad):
    with pytest.raises(ConfigError, match="valid_range"):
        make_config(lambda raw: raw["profiles"]["finder_7m24"]["metrics"]["thd_current"].update(valid_range=bad))


def test_v2_registers_must_lie_inside_the_read_request(make_config):
    with pytest.raises(ConfigError, match="poza zapytaniem"):
        make_config(lambda raw: raw["plc"].update(read={"start": 0, "count": 44}))


def test_v2_fields_do_not_overlap_the_v1_fields(make_config):
    with pytest.raises(ConfigError, match="nakładanie"):
        make_config(lambda raw: raw["profiles"]["finder_7m24"]["metrics"]["run_time"].update(offset=30))


def test_a_single_version_config_behaves_like_before(make_config, clock):
    """Konfiguracja tylko z wersją 1 (bez pól v2) działa jak dotąd."""
    def v1_only(raw):
        raw["plc"].update(map_versions=[1], read={"start": 0, "count": 44})
        profile = raw["profiles"]["finder_7m24"]
        for name in ("thd_voltage", "thd_current", "phase_angle", "meter_temperature", "run_time"):
            profile["metrics"].pop(name)
        for name in ("reactive_pos_varh", "reactive_neg_varh"):
            profile["energy"].pop(name)

    config = make_config(v1_only)
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(Registers(0, build_image(heartbeat=1, map_version=1)[:44]))
    result = evaluator.evaluate(Registers(0, build_image(heartbeat=2, map_version=1)[:44]))
    assert len(result.readings) == 13
    assert evaluator.evaluate(Registers(0, build_image(heartbeat=3, map_version=2)[:44])).link_status == LinkStatus.MAP_VERSION_MISMATCH
