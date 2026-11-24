"""Pętla collectora (K6-a, K6-U1, K6-U2): odczyt w tle, ciągłość link_status w awarii, porzucanie zawieszonego odczytu."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import pytest

from collector.codec import Registers
from collector.drivers.base import SourceError
from collector.drivers.modbus_plc import ModbusPlcDriver
from collector.evaluator import Evaluator
from collector.main import run
from fakes.modbus_plc import SilentServer, build_image

INTERVAL = 0.1
TIMEOUT = 0.5            # porzucenie po 3 x TIMEOUT = 1,5 s


class FakePublisher:
    def __init__(self) -> None:
        self.batches: list[tuple[float, list[tuple[str, bytes]]]] = []

    def publish_batch(self, messages) -> None:
        self.batches.append((time.monotonic(), list(messages)))

    def drain(self) -> None:
        pass

    def rows(self):
        out = []
        for moment, messages in self.batches:
            for topic, payload in messages:
                _, _, device, metric = topic.split("/")
                out.append((moment, device, metric, json.loads(payload)["value"]))
        return out

    def link_rows(self):
        return [(t, v) for t, d, m, v in self.rows() if m == "link_status"]


class ScriptedDriver:
    """Sterownik sterowany przez test: tryby ok, hang (wisi do anulowania), stubborn (ignoruje anulowanie), error, boom."""

    def __init__(self, stale_voltage: float = 111.0) -> None:
        self.mode = "ok"
        self.delay = 0.0
        self.resets = 0
        self.reads_started = 0
        self._hb = 1
        self._stale_voltage = stale_voltage

    def registers(self, voltage: float | None = None) -> Registers:
        self._hb += 1
        meter = {} if voltage is None else {"voltage": voltage}
        return Registers(0, build_image(heartbeat=self._hb, meters=((10, meter),))[:44])

    async def read(self) -> Registers:
        self.reads_started += 1
        mode = self.mode
        if mode == "hang":
            await asyncio.Event().wait()
        if mode == "stubborn":
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:                  # nie wolno później opublikować wyniku porzuconego zadania
                await asyncio.sleep(0.4)
                return self.registers(self._stale_voltage)
        if self.delay:
            await asyncio.sleep(self.delay)
        if mode == "error":
            raise SourceError("test: błąd odczytu")
        if mode == "boom":
            raise RuntimeError("test: nieoczekiwany wyjątek")
        if mode == "short":
            return Registers(0, [])
        return self.registers()

    async def reset(self) -> None:
        self.resets += 1

    async def close(self) -> None:
        pass


def measured_period(publisher: FakePublisher, before: float) -> float:
    """Mediana odstępów między kolejnymi cyklami sprawnej pracy (nie mniej niż nominalny okres)."""
    times = [t for t, _ in publisher.link_rows() if t < before]
    gaps = sorted(b - a for a, b in zip(times, times[1:]))
    assert len(gaps) >= 3, "za mało cykli sprawnej pracy do pomiaru okresu"
    return max(gaps[len(gaps) // 2], INTERVAL)


def measured_cycle(times: list[float]) -> float:
    """Typowy odstęp (mediana) między kolejnymi wierszami; luki zwiększają liczbę brakujących okresów, nie medianę."""
    gaps = sorted(b - a for a, b in zip(times, times[1:]))
    return gaps[len(gaps) // 2]


@pytest.fixture
def loop_config(make_config):
    def mutate(raw):
        raw["plc"].update(poll_interval_s=INTERVAL, timeout_s=TIMEOUT, heartbeat_timeout_s=5)

    return make_config(mutate)


def start(config, driver, tmp_path):
    publisher = FakePublisher()
    stop = asyncio.Event()
    task = asyncio.create_task(
        run(config, driver, publisher, Evaluator(config), stop, health_file=str(tmp_path / "health")))
    return publisher, stop, task


async def finish(stop, task):
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


def test_black_hole_keeps_link_status_flowing_and_recovers_without_restart(loop_config, tmp_path):
    async def scenario():
        driver = ScriptedDriver()
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.8)                                   # sprawny PLC: komplet wierszy
        driver.mode = "hang"
        t_fault = time.monotonic()
        await asyncio.sleep(4.0)                                   # awaria: connect()/odczyt nigdy się nie kończy
        driver.mode = "ok"
        t_recover = time.monotonic()
        await asyncio.sleep(3.0)
        await finish(stop, task)
        return driver, publisher, t_fault, t_recover

    driver, publisher, t_fault, t_recover = asyncio.run(scenario())

    offline = [(t, v) for t, v in publisher.link_rows() if v == 1.0]
    assert offline, "brak link_status = 1 w awarii"
    t_detect = offline[0][0]
    assert t_detect - t_fault <= TIMEOUT + 1.0, f"wykrycie po {t_detect - t_fault:.2f} s"

    # od chwili wykrycia do końca awarii: >= 95% okresów z wierszem link_status; okres rzeczywisty mierzony w fazie sprawnej
    # (ziarnistość timerów asyncio zależy od systemu), a nie nominalny
    in_outage = [t for t, v in offline if t_detect <= t <= t_recover]
    period = measured_cycle(in_outage)       # typowy odstęp w samej awarii: luki zwiększają liczbę brakujących okresów, nie medianę
    cycles = (t_recover - t_detect) / period + 1
    assert len(in_outage) >= 0.95 * cycles, f"{len(in_outage)} wierszy z {cycles:.0f} okresów (okres {period * 1000:.0f} ms)"
    print(f"\n[pomiar] czarna dziura: wykrycie po {t_detect - t_fault:.2f} s, {len(in_outage)} z {cycles:.0f} okresów z wierszem")

    # w awarii tylko link_status
    others = [(m) for t, d, m, v in publisher.rows() if t_detect <= t <= t_recover and m != "link_status"]
    assert others == []

    # zawieszone zadania są porzucane (co 3 x timeout), a po powrocie PLC collector wraca do OK bez restartu
    assert driver.resets >= 2
    after = [(t, d, m, v) for t, d, m, v in publisher.rows() if t > t_recover]
    assert any(m == "link_status" and v == 0.0 for _, _, m, v in after), "brak powrotu do link_status = 0"
    assert any(m == "voltage" for _, _, m, _ in after), "po powrocie brak pomiarów"


def test_slow_read_below_timeout_does_not_report_offline_nor_warmup(loop_config, tmp_path):
    """K6-U1: odczyt trwający 1,5 x okres, ale krótszy niż timeout_s, nie daje link_status = 1 ani rozgrzewki."""

    async def scenario():
        driver = ScriptedDriver()
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.8)
        driver.delay = 1.5 * INTERVAL
        mark = time.monotonic()
        await asyncio.sleep(2.5)
        driver.delay = 0.0
        await asyncio.sleep(0.5)
        await finish(stop, task)
        return publisher, mark

    publisher, mark = asyncio.run(scenario())
    values = [v for t, v in publisher.link_rows() if t >= mark]
    assert values and set(values) == {0.0}, "wolny, ale poprawny odczyt nie może dawać link_status = 1"
    voltage = [t for t, d, m, v in publisher.rows() if m == "voltage" and t >= mark]
    assert len(voltage) >= 8                                           # pomiary płyną cały czas (bez rozgrzewki)


def test_abandoned_task_never_publishes_its_late_result(loop_config, tmp_path):
    """K6-U2: porzucone zadanie, które mimo anulowania zwróci wynik, nie może go opublikować."""

    async def scenario():
        driver = ScriptedDriver(stale_voltage=111.0)
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.5)
        driver.mode = "stubborn"
        await asyncio.sleep(2.2)                                       # porzucenie po 1,5 s; wynik porzuconego po kolejnych 0,4 s
        driver.mode = "ok"
        await asyncio.sleep(2.5)
        await finish(stop, task)
        return publisher

    publisher = asyncio.run(scenario())
    voltages = [v for _, _, m, v in publisher.rows() if m == "voltage"]
    assert voltages and 111.0 not in voltages


def test_stop_with_a_hung_read_returns_promptly_and_leaves_no_task(loop_config, tmp_path):
    async def scenario():
        driver = ScriptedDriver()
        driver.mode = "hang"
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.4)
        started = time.monotonic()
        await finish(stop, task)
        await asyncio.sleep(0.05)
        leftovers = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        return time.monotonic() - started, leftovers

    elapsed, leftovers = asyncio.run(scenario())
    assert elapsed < 0.5
    assert leftovers == []


def test_unexpected_exceptions_do_not_stop_the_loop(loop_config, tmp_path):
    """Błąd inny niż SourceError (wyjątek sterownika, za krótka odpowiedź) = nieudany odczyt, pętla żyje."""

    async def scenario():
        driver = ScriptedDriver()
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.5)
        driver.mode = "boom"
        await asyncio.sleep(0.8)
        driver.mode = "short"
        await asyncio.sleep(0.8)
        driver.mode = "ok"
        await asyncio.sleep(1.0)
        assert not task.done(), "pętla zakończyła się po nieoczekiwanym wyjątku"
        await finish(stop, task)
        return publisher

    publisher = asyncio.run(scenario())
    values = [v for _, v in publisher.link_rows()]
    assert 1.0 in values and values[-1] == 0.0


def test_error_read_reports_offline_immediately_and_each_cycle(loop_config, tmp_path):
    async def scenario():
        driver = ScriptedDriver()
        publisher, stop, task = start(loop_config, driver, tmp_path)
        await asyncio.sleep(0.5)
        driver.mode = "error"
        t_fault = time.monotonic()
        await asyncio.sleep(1.5)
        await finish(stop, task)
        return publisher, t_fault

    publisher, t_fault = asyncio.run(scenario())
    offline = [t for t, v in publisher.link_rows() if v == 1.0]
    period = measured_period(publisher, before=t_fault)
    assert offline and offline[0] - t_fault <= 2 * period + 0.05      # błąd = natychmiast, bez czekania na timeout
    assert len(offline) >= 0.9 * (1.5 / period) - 1


def test_real_driver_against_a_server_that_accepts_but_never_answers(loop_config, make_config, tmp_path):
    """Prawdziwy ModbusPlcDriver i serwer, który przyjmuje połączenie i milczy (jak Stop programu): ciągłość >= 95%."""

    async def scenario():
        server = SilentServer()
        await server.start()

        def mutate(raw):
            raw["plc"].update(host="127.0.0.1", port=server.port, poll_interval_s=0.2, timeout_s=0.6)
            raw["plc"]["reconnect"] = {"initial_s": 0.1, "max_s": 0.4}

        config = make_config(mutate)
        driver = ModbusPlcDriver(config.plc)
        publisher = FakePublisher()
        stop = asyncio.Event()
        task = asyncio.create_task(
            run(config, driver, publisher, Evaluator(config), stop, health_file=str(tmp_path / "health")))
        started = time.monotonic()
        await asyncio.sleep(6.0)
        await finish(stop, task)
        await driver.close()
        await server.close()
        return publisher, started

    publisher, started = asyncio.run(scenario())
    offline = [t for t, v in publisher.link_rows() if v == 1.0]
    assert offline
    t_detect = offline[0]
    detect = t_detect - started
    cycles = (started + 6.0 - t_detect) / max(0.2, measured_cycle(offline))
    print(f"\n[pomiar] milczący serwer: wykrycie po {detect:.2f} s, {len(offline)} wierszy w {cycles:.0f} okresach")
    assert detect <= 0.6 + 1.0
    assert len(offline) >= 0.95 * cycles
    assert {m for _, _, m, _ in publisher.rows()} == {"link_status"}


def test_driver_reset_clears_backoff_and_drops_the_client(loop_config):
    class Failing:
        connected = False

        async def connect(self):
            return False

        def close(self):
            pass

    clock = {"now": 0.0}
    driver = ModbusPlcDriver(loop_config.plc, client_factory=lambda p: Failing(), clock=lambda: clock["now"])

    async def scenario():
        with pytest.raises(SourceError):
            await driver.read()
        with pytest.raises(SourceError) as error:
            await driver.read()                                        # w oknie cofania: bez próby
        assert "cofanie" in str(error.value)
        await driver.reset()
        assert driver.failures == 0
        with pytest.raises(SourceError) as error:
            await driver.read()                                        # po reset: natychmiastowa nowa próba
        assert "cofanie" not in str(error.value)

    asyncio.run(scenario())
