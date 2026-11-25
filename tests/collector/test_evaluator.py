"""Reguły ważności danych (kontrakt docs/modbus-map.md), kody statusów (D10, U2) i źródło `source` (K3-U1)."""
from __future__ import annotations

import math

import pytest

from collector.codec import Registers
from collector.evaluator import Evaluator
from collector.status import LinkStatus, MeterStatus
from fakes.modbus_plc import build_image, words_f32

EXPECTED_METRICS = {
    "meter_error_count", "meter_data_age_ms", "meter_status", "active_power", "reactive_power", "apparent_power",
    "power_factor", "frequency", "voltage", "current", "energy_import_wh", "energy_export_wh",
}


def image(config, heartbeat=1, map_version=1, **meter) -> Registers:
    words = build_image(heartbeat=heartbeat, map_version=map_version, meters=((10, meter),))
    return Registers(config.plc.read_start, words[: config.plc.read_count])


def values(evaluation):
    return {(r.device_id, r.metric): r.value for r in evaluation.readings}


def warm_up(evaluator, config, hb=1):
    """Pierwszy odczyt po połączeniu (rozgrzewka) i drugi ze zmienionym heartbeatem: dopiero on jest ważny."""
    first = evaluator.evaluate(image(config, heartbeat=hb))
    assert first.link_status is None
    return evaluator.evaluate(image(config, heartbeat=hb + 1))


def test_first_read_is_warmup_second_is_valid(config, clock):
    evaluator = Evaluator(config, clock)
    assert evaluator.evaluate(image(config)).link_status is None            # nic nie publikujemy
    assert evaluator.evaluate(image(config)).readings == []                 # heartbeat jeszcze bez zmiany
    result = evaluator.evaluate(image(config, heartbeat=2))
    assert result.link_status == LinkStatus.OK
    assert len(result.readings) == 13                                       # 13 wiadomości na cykl
    got = values(result)
    assert got[("plc-01", "link_status")] == 0
    assert {metric for (device, metric) in got if device == "finder_7m24_1"} == EXPECTED_METRICS
    assert got[("finder_7m24_1", "voltage")] == 240.4
    assert got[("finder_7m24_1", "active_power")] == 7.0
    assert got[("finder_7m24_1", "energy_import_wh")] == 3500.0
    assert got[("finder_7m24_1", "meter_status")] == MeterStatus.OK


def test_read_failure_gives_offline_only(config, clock):
    evaluator = Evaluator(config, clock)
    result = evaluator.on_read_failed()
    assert result.link_status == LinkStatus.PLC_OFFLINE
    assert [(r.metric, r.value) for r in result.readings] == [("link_status", 1.0)]
    assert result.states == {"plc": "PLC_OFFLINE"}


def test_after_failure_next_read_needs_a_new_heartbeat_change(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    evaluator.on_read_failed()
    # PLC wrócił, ale pierwszy odczyt po połączeniu nie może uchodzić za świeży
    assert evaluator.evaluate(image(config, heartbeat=50)).link_status is None
    assert evaluator.evaluate(image(config, heartbeat=51)).link_status == LinkStatus.OK


def test_map_version_mismatch(config, clock):
    result = Evaluator(config, clock).evaluate(image(config, map_version=3))
    assert result.link_status == LinkStatus.MAP_VERSION_MISMATCH
    assert [(r.metric, r.value) for r in result.readings] == [("link_status", 3.0)]


def test_map_version_is_checked_before_heartbeat(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    clock.advance(60)                                                       # heartbeat dawno nie zmieniony
    assert evaluator.evaluate(image(config, heartbeat=2, map_version=3)).link_status == LinkStatus.MAP_VERSION_MISMATCH


def test_heartbeat_exactly_five_seconds_is_not_stale_but_more_is(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)                                              # zmiana heartbeatu w chwili t0
    clock.advance(5.0)
    assert evaluator.evaluate(image(config, heartbeat=2)).link_status == LinkStatus.OK
    clock.advance(0.01)
    stale = evaluator.evaluate(image(config, heartbeat=2))
    assert stale.link_status == LinkStatus.PLC_STOPPED
    assert [(r.metric, r.value) for r in stale.readings] == [("link_status", 2.0)]


def test_heartbeat_change_resets_the_timer(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    clock.advance(4.9)
    assert evaluator.evaluate(image(config, heartbeat=3)).link_status == LinkStatus.OK
    clock.advance(4.9)
    assert evaluator.evaluate(image(config, heartbeat=3)).link_status == LinkStatus.OK


def test_heartbeat_wraparound_counts_as_a_change(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config, hb=0xFFFFFFFE)
    clock.advance(4.0)
    assert evaluator.evaluate(image(config, heartbeat=0xFFFFFFFF)).link_status == LinkStatus.OK
    clock.advance(4.0)
    assert evaluator.evaluate(image(config, heartbeat=0)).link_status == LinkStatus.OK


def test_stale_heartbeat_during_warmup_is_stopped(config, clock):
    """PLC zatrzymany, ale serwer odpowiada: po 5 s bez zmiany link_status = 2 (nie "OK" z zamrożonymi danymi)."""
    evaluator = Evaluator(config, clock)
    assert evaluator.evaluate(image(config)).link_status is None
    clock.advance(5.0)
    assert evaluator.evaluate(image(config)).link_status is None
    clock.advance(0.5)
    assert evaluator.evaluate(image(config)).link_status == LinkStatus.PLC_STOPPED


def test_comm_error_publishes_status_and_diagnostics_only(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    result = evaluator.evaluate(image(config, heartbeat=3, status=1, error_code=161, error_count=1, data_age_ms=5200))
    got = values(result)
    assert got[("finder_7m24_1", "meter_status")] == MeterStatus.COMM_ERROR
    assert got[("finder_7m24_1", "meter_error_count")] == 1
    assert got[("finder_7m24_1", "meter_data_age_ms")] == 5200
    assert ("finder_7m24_1", "voltage") not in got and ("finder_7m24_1", "active_power") not in got
    assert result.states["meter:finder_7m24_1"] == "COMM_ERROR"
    assert result.link_status == LinkStatus.OK                              # PLC sam jest sprawny


def test_no_data_with_empty_serial_is_not_a_serial_mismatch(config, clock):
    """K3-b: status oceniamy przed serialem; przy NO_DATA serial jest pusty i data_age = FFFFFFFF (pomijany)."""
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    result = evaluator.evaluate(image(config, heartbeat=3, status=2, serial="", data_age_ms=0xFFFFFFFF))
    got = values(result)
    assert got[("finder_7m24_1", "meter_status")] == MeterStatus.NO_DATA
    assert ("finder_7m24_1", "meter_data_age_ms") not in got
    assert ("finder_7m24_1", "voltage") not in got


def test_unknown_status_is_published_raw_without_measurements(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    result = evaluator.evaluate(image(config, heartbeat=3, status=7))
    got = values(result)
    assert got[("finder_7m24_1", "meter_status")] == 7
    assert ("finder_7m24_1", "voltage") not in got
    assert result.states["meter:finder_7m24_1"] == "UNKNOWN_STATUS_7"


def test_serial_mismatch_publishes_code_10_and_no_measurements(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    result = evaluator.evaluate(image(config, heartbeat=3, serial="X9999999"))
    got = values(result)
    assert got[("finder_7m24_1", "meter_status")] == MeterStatus.SERIAL_MISMATCH == 10
    assert ("finder_7m24_1", "voltage") not in got
    assert result.states["meter:finder_7m24_1"] == "SERIAL_MISMATCH"


def test_serial_mismatch_blocks_only_that_meter(make_config, clock):
    """U2: pomyłka w jednym liczniku nie blokuje drugiego (konfiguracja z dwoma licznikami: bazy 10 i 60)."""

    def two_meters(raw):
        raw["plc"]["read"]["count"] = 110
        raw["devices"].append({"id": "finder_2", "name": "Licznik 2", "kind": "energy_meter", "source": "real",
                               "profile": "finder_7m24", "block_base": 60, "serial": "F9999999"})

    config = make_config(two_meters)

    def both(hb, serial2):
        words = build_image(heartbeat=hb, meters=((10, {}), (60, {"serial": serial2, "voltage": 231.0})))
        return Registers(0, words[:110])

    evaluator = Evaluator(config, clock)
    assert evaluator.evaluate(both(1, "F0000000")).link_status is None
    result = evaluator.evaluate(both(2, "F0000000"))                         # drugi licznik ma zły serial
    got = values(result)
    assert got[("finder_7m24_1", "meter_status")] == 0 and got[("finder_7m24_1", "voltage")] == 240.4
    assert got[("finder_2", "meter_status")] == 10 and ("finder_2", "voltage") not in got

    fixed = evaluator.evaluate(both(3, "F9999999"))
    assert values(fixed)[("finder_2", "voltage")] == 231.0


def test_non_finite_values_are_skipped_and_reported(config, clock):
    evaluator = Evaluator(config, clock)
    warm_up(evaluator, config)
    regs = image(config, heartbeat=3)
    regs.values[26:28] = words_f32(math.nan)                                # napięcie (offset 16 + baza 10)
    result = evaluator.evaluate(regs)
    got = values(result)
    assert ("finder_7m24_1", "voltage") not in got
    assert result.skipped == ["finder_7m24_1.voltage"]
    assert got[("finder_7m24_1", "frequency")] == 50.02


def test_source_comes_from_configuration_not_from_code(make_config, clock):
    """K3-U1: `source` urządzenia i PLC z devices.yaml; ten sam collector obsłuży np. PLC testowe jako sim."""

    def simulated(raw):
        raw["devices"][0]["source"] = "sim"
        raw["plc"]["source"] = "sim"

    config = make_config(simulated)
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(image(config))
    result = evaluator.evaluate(image(config, heartbeat=2))
    assert {r.source for r in result.readings} == {"sim"}


def test_default_source_is_real(config, clock):
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(image(config))
    assert {r.source for r in evaluator.evaluate(image(config, heartbeat=2)).readings} == {"real"}


def test_units_and_names_come_from_configuration(config, clock):
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(image(config))
    result = evaluator.evaluate(image(config, heartbeat=2))
    units = {r.metric: r.unit for r in result.readings}
    assert units["voltage"] == "V" and units["active_power"] == "W" and units["energy_import_wh"] == "Wh"
    assert units["meter_data_age_ms"] == "ms" and units["link_status"] == ""
