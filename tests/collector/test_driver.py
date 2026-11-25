"""Sterownik Modbus TCP: odczyt z atrapy PLC, awarie, cofanie wykładnicze, timeout, krótka odpowiedź."""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from collector.drivers.base import SourceError
from collector.drivers.modbus_plc import ModbusPlcDriver
from collector.evaluator import Evaluator
from fakes.modbus_plc import FakePlc, SilentServer


def run(coro):
    return asyncio.run(coro)


def plc_config(config, port, **changes):
    plc = dataclasses.replace(config.plc, host="127.0.0.1", port=port, timeout_s=1.0,
                              reconnect_initial_s=0.1, reconnect_max_s=0.4, **changes)
    return dataclasses.replace(config, plc=plc)


def test_reads_60_registers_from_the_fake_plc(config):
    async def scenario():
        plc = FakePlc()
        await plc.start()
        cfg = plc_config(config, plc.port)
        driver = ModbusPlcDriver(cfg.plc)
        try:
            regs = await driver.read()
            assert len(regs) == 60 and regs.start == 0
            assert regs.u16(2) == 1 and regs.ascii(40, 4) == "F0183363"
            assert set(plc.function_codes) == {4}
        finally:
            await driver.close()
            await plc.close()

    run(scenario())


def test_recovers_after_the_plc_goes_away_without_restart(config):
    async def scenario():
        plc = FakePlc()
        await plc.start()
        cfg = plc_config(config, plc.port)
        driver = ModbusPlcDriver(cfg.plc)
        try:
            await driver.read()
            await plc.stop()
            with pytest.raises(SourceError):
                await driver.read()
            await plc.start()
            deadline = time.monotonic() + 5
            while True:
                try:
                    regs = await driver.read()
                    break
                except SourceError:
                    assert time.monotonic() < deadline, "sterownik nie wrócił po powrocie PLC"
                    await asyncio.sleep(0.05)
            assert regs.u16(2) == 1
            assert driver.failures == 0
        finally:
            await driver.close()
            await plc.close()

    run(scenario())


def test_silent_server_times_out_instead_of_hanging(config):
    async def scenario():
        server = SilentServer()
        await server.start()
        cfg = plc_config(config, server.port)
        driver = ModbusPlcDriver(cfg.plc)
        try:
            started = time.perf_counter()
            with pytest.raises(SourceError):
                await driver.read()
            elapsed = time.perf_counter() - started
            print(f"\n[pomiar] timeout przy milczącym serwerze: {elapsed:.2f} s (timeout_s = {cfg.plc.timeout_s})")
            assert cfg.plc.timeout_s - 0.1 <= elapsed <= cfg.plc.timeout_s + 1.0   # bez ponowień biblioteki
        finally:
            await driver.close()
            await server.close()

    run(scenario())


class FailingClient:
    """Klient, który nigdy się nie łączy; zlicza próby łączenia."""

    attempts: list[float] = []

    def __init__(self, clock):
        self._clock = clock
        self.connected = False

    async def connect(self):
        FailingClient.attempts.append(self._clock())
        return False

    def close(self):
        pass


def test_reconnect_backoff_is_exponential_and_capped(config, clock):
    """Próby w chwilach 0, 1, 3, 7, 15, 25 s (cofanie 1, 2, 4, 8, 10 s); w międzyczasie bez prób."""
    FailingClient.attempts = []
    plc = dataclasses.replace(config.plc, reconnect_initial_s=1, reconnect_max_s=10)
    driver = ModbusPlcDriver(plc, client_factory=lambda p: FailingClient(clock), clock=clock)

    async def scenario():
        start = clock()
        for _ in range(60):                         # 30 s krokami co 0,5 s
            with pytest.raises(SourceError):
                await driver.read()
            clock.advance(0.5)
        return [round(t - start, 1) for t in FailingClient.attempts]

    assert run(scenario()) == [0.0, 1.0, 3.0, 7.0, 15.0, 25.0]


class ShortClient:
    connected = True

    async def connect(self):
        return True

    async def read_input_registers(self, address, count, unit_id):
        return [0] * (count - 1)

    def close(self):
        pass


def test_short_response_is_an_error(config):
    driver = ModbusPlcDriver(config.plc, client_factory=lambda p: ShortClient())
    with pytest.raises(SourceError) as error:
        run(driver.read())
    assert "krótka odpowiedź" in str(error.value)


def test_library_retries_and_auto_reconnect_are_disabled(config):
    """Ponawianiem i łączeniem zarządza sterownik; biblioteka (domyślnie 3 ponowienia) zablokowałaby cykl."""
    from collector.drivers.modbus_plc import ReadOnlyModbusClient

    async def scenario():
        client = ReadOnlyModbusClient("127.0.0.1", 1, 1.0)
        inner = client._ReadOnlyModbusClient__client
        assert inner.comm_params.reconnect_delay == 0
        assert inner.ctx.retries == 0
        assert inner.comm_params.timeout_connect == 1.0

    run(scenario())


def test_cycle_time_on_the_fake_plc(config):
    async def scenario():
        plc = FakePlc()
        await plc.start()
        cfg = plc_config(config, plc.port)
        driver = ModbusPlcDriver(cfg.plc)
        evaluator = Evaluator(cfg)
        try:
            await driver.read()                     # pierwsze połączenie poza pomiarem
            samples = []
            for _ in range(30):
                started = time.perf_counter()
                evaluator.evaluate(await driver.read())
                samples.append((time.perf_counter() - started) * 1000)
            samples.sort()
            print(f"\n[pomiar] odczyt FC04 + ocena na atrapie (localhost): mediana {samples[15]:.1f} ms, "
                  f"maks. {samples[-1]:.1f} ms z 30 cykli")
            assert samples[-1] < 500
        finally:
            await driver.close()
            await plc.close()

    run(scenario())
