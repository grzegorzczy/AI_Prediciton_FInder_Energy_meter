"""meter_error_code (log przy zmianie kodu, metryka przy meter_status != 0) i wyciszenie loggera pymodbus (K6-0.2, 0.3)."""
from __future__ import annotations

import asyncio
import logging

import pytest

from collector.codec import Registers
from collector.drivers.base import SourceError
from collector.drivers.modbus_plc import ModbusPlcDriver
from collector.evaluator import Evaluator
from collector.statelog import StateLogger
from collector.status import ERROR_CODE_NAMES, describe_error_code
from fakes.modbus_plc import SilentServer, build_image

KEY = "meter:finder_7m24_1"


def image(config, heartbeat=1, **meter) -> Registers:
    words = build_image(heartbeat=heartbeat, meters=((10, meter),))
    return Registers(0, words[: config.plc.read_count])


def values(evaluation):
    return {(r.device_id, r.metric): r.value for r in evaluation.readings}


def warmed_up(config, clock):
    evaluator = Evaluator(config, clock)
    evaluator.evaluate(image(config, heartbeat=1))
    assert evaluator.evaluate(image(config, heartbeat=2)).link_status is not None
    return evaluator


@pytest.mark.parametrize("code, text", [
    (161, "error_code=161, 0xA1, RESPONSE_TIMEOUT"),
    (162, "error_code=162, 0xA2, RESPONSE_CRC_FAIL"),
    (163, "error_code=163, 0xA3, RESPONSE_WRONG_SLAVE"),
    (7, "error_code=7, 0x07"),
    (0, "error_code=0, 0x00"),
])
def test_error_code_description(code, text):
    assert describe_error_code(code) == text


def test_known_codes_table():
    assert ERROR_CODE_NAMES == {161: "RESPONSE_TIMEOUT", 162: "RESPONSE_CRC_FAIL", 163: "RESPONSE_WRONG_SLAVE"}


def test_error_code_is_published_only_when_status_is_not_ok(config, clock):
    evaluator = warmed_up(config, clock)
    failing = evaluator.evaluate(image(config, heartbeat=3, status=1, error_code=162, error_count=2, data_age_ms=1000))
    got = values(failing)
    assert got[("finder_7m24_1", "meter_error_code")] == 162
    assert "RESPONSE_CRC_FAIL" in failing.details[KEY]
    assert len(failing.readings) == 5                                      # link_status + 4 wiersze licznika w sekundzie z błędem
    assert {r.metric for r in failing.readings} == {
        "link_status", "meter_status", "meter_error_count", "meter_data_age_ms", "meter_error_code"}

    healthy = evaluator.evaluate(image(config, heartbeat=4))
    assert ("finder_7m24_1", "meter_error_code") not in values(healthy)
    assert KEY not in healthy.details and len(healthy.readings) == 13      # sprawny licznik: nadal 13 wierszy


@pytest.mark.parametrize("status", [2, 7])
def test_error_code_is_published_for_no_data_and_unknown_status(config, clock, status):
    evaluator = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, status=status, error_code=0, data_age_ms=0xFFFFFFFF))
    got = values(result)
    assert got[("finder_7m24_1", "meter_error_code")] == 0
    assert ("finder_7m24_1", "meter_data_age_ms") not in got                # sentinel NO_DATA nadal pomijany


def test_no_error_code_for_serial_mismatch(config, clock):
    evaluator = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, serial="X9999999", error_code=162))
    assert ("finder_7m24_1", "meter_error_code") not in values(result)     # status 0: kod nieważny


def test_unknown_code_is_published_numerically_without_a_name(config, clock):
    evaluator = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, status=1, error_code=7))
    assert values(result)[("finder_7m24_1", "meter_error_code")] == 7
    assert result.details[KEY] == "error_code=7, 0x07"


def test_metric_is_optional_in_configuration(make_config, clock):
    def no_metric(raw):
        raw["profiles"]["finder_7m24"]["diagnostics"]["error_code"].pop("metric")

    config = make_config(no_metric)
    evaluator = warmed_up(config, clock)
    result = evaluator.evaluate(image(config, heartbeat=3, status=1, error_code=162))
    assert ("finder_7m24_1", "meter_error_code") not in values(result)
    assert "RESPONSE_CRC_FAIL" in result.details[KEY]                       # log nadal ma kod


def test_error_code_change_is_logged_once_per_change(caplog, clock):
    states = StateLogger(clock, remind_s=60)
    with caplog.at_level(logging.INFO, logger="collector.state"):
        states.update({KEY: "OK"})
        for _ in range(5):                                                  # ten sam kod przez kilka cykli: jeden wpis
            states.update({KEY: "COMM_ERROR"}, {KEY: describe_error_code(162)})
        states.update({KEY: "COMM_ERROR"}, {KEY: describe_error_code(161)})  # zmiana kodu: nowy wpis
        states.update({KEY: "OK"})
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 4, messages
    assert "COMM_ERROR (error_code=162, 0xA2, RESPONSE_CRC_FAIL)" in messages[1]
    assert "-> COMM_ERROR (error_code=161, 0xA1, RESPONSE_TIMEOUT)" in messages[2]
    assert messages[3].endswith("-> OK")


def test_pymodbus_logger_is_silenced_and_leaves_no_raw_frames(caplog, capfd, make_config):
    """Surowe ramki `>>>>>` to ostatnie ramki dopisywane przez pymodbus do komunikatów ERROR; CRITICAL usuwa jedno i drugie."""
    from collector import main as collector_main

    root = logging.getLogger()
    modbus = logging.getLogger("pymodbus")
    old_root, old_modbus = root.level, modbus.level

    async def scenario():
        server = SilentServer()
        await server.start()
        config = make_config(lambda raw: raw["plc"].update(host="127.0.0.1", port=server.port, timeout_s=0.5))
        driver = ModbusPlcDriver(config.plc)
        try:
            with pytest.raises(SourceError):
                await driver.read()
        finally:
            await driver.close()
            await server.close()

    try:
        collector_main._setup_logging()
        assert modbus.level == logging.CRITICAL
        root.setLevel(logging.DEBUG)
        caplog.set_level(logging.DEBUG)
        asyncio.run(scenario())
    finally:
        root.setLevel(old_root)
        modbus.setLevel(old_modbus)
    assert [r.name for r in caplog.records if r.name.startswith("pymodbus")] == []
    captured = capfd.readouterr()
    assert ">>>>>" not in captured.out + captured.err
