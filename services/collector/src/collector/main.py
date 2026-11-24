"""Pętla collectora: odczyt -> ocena -> publikacja -> znacznik żywotności. Uruchomienie: python -m collector.main.

Brak PLC lub brokera MQTT to stan, a nie błąd: proces nie kończy się z tego powodu (uwaga U4). Zły plik
konfiguracji przy starcie kończy proces kodem 2 (restart zrobi Docker).
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone

from . import health
from .config import Config, ConfigError, load_config
from .drivers.base import SourceDriver, SourceError
from .drivers.modbus_plc import ModbusPlcDriver
from .evaluator import Evaluation, Evaluator
from .messages import build_message, format_ts
from .publisher import PahoTransport, Publisher
from .statelog import StateLogger

LOG = logging.getLogger("collector")

# Zadanie odczytu trwające dłużej niż ABANDON_FACTOR x timeout_s jest porzucane, a klient tworzony od nowa (K6-U2).
ABANDON_FACTOR = 3.0


async def _read_once(driver: SourceDriver, wall: Callable[[], datetime]):
    """Jeden odczyt wraz ze znacznikiem czasu chwili odbioru odpowiedzi (jeden `ts` na cały odczyt, D2)."""
    registers = await driver.read()
    return registers, format_ts(wall())


def _consume(task: asyncio.Task) -> None:
    """Porzucone zadanie: wynik i wyjątek są odrzucane, żeby nic nie zostało opublikowane ani zalogowane."""
    try:
        task.result()
    except BaseException:                    # noqa: BLE001
        pass


async def run(
    config: Config,
    driver: SourceDriver,
    publisher: Publisher,
    evaluator: Evaluator,
    stop: asyncio.Event,
    health_file: str = health.DEFAULT_PATH,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    state_logger: StateLogger | None = None,
) -> None:
    """Pętla: co okres jeden cykl, w którym odczyt (zadanie w tle) jest oceniany, a stan publikowany.

    Odczyt z PLC, łącznie z łączeniem, nie blokuje cyklu (K6-a). Gdy odczyt jeszcze trwa:
      - PLC uznany za sprawny i odczyt trwa krócej niż timeout_s: cykl bez publikacji (wolna odpowiedź, bez
        fałszywego "offline");
      - odczyt trwa dłużej niż timeout_s albo PLC jest już uznany za niedostępny: link_status = 1 w każdym kolejnym
        cyklu, aż odczyt się zakończy (K6-U1);
      - po przekroczeniu ABANDON_FACTOR x timeout_s: zadanie jest porzucane i startuje nowy odczyt na nowym kliencie (K6-U2).
    Nigdy nie działają dwa odczyty naraz.
    """
    interval = config.plc.poll_interval_s
    timeout = config.plc.timeout_s
    states = state_logger or StateLogger(clock)
    failing = False
    abandoned_logged = False
    pending: asyncio.Task | None = None
    started = 0.0
    cycle_start = clock()

    try:
        while not stop.is_set():
            if pending is None:
                pending = asyncio.create_task(_read_once(driver, wall))
                started = clock()

            done, _ = await asyncio.wait({pending}, timeout=max(0.0, cycle_start + interval - clock()))
            ts = format_ts(wall())
            if done:
                task, pending = pending, None
                try:
                    registers, ts = task.result()
                    evaluation = evaluator.evaluate(registers)
                    failing = abandoned_logged = False
                except Exception as exc:                 # SourceError i błędy nieoczekiwane: nie zatrzymują pętli
                    if not failing:
                        LOG.warning("odczyt PLC nie powiódł się: %s", exc if isinstance(exc, SourceError) else repr(exc))
                        failing = True
                    evaluation = evaluator.on_read_failed()
            else:
                age = clock() - started
                # Wstrzymanie publikacji do upływu timeout_s chroni przed fałszywym "offline" przy wolnej odpowiedzi
                # sprawnego PLC (K6-U1). Gdy PLC jest już uznany za niedostępny, każdy cykl publikuje link_status = 1
                # niezależnie od wieku nowego odczytu: inaczej po każdym porzuceniu lub ponownej próbie byłaby luka
                # długości timeout_s (ok. 17% sekund w "czarnej dziurze").
                if age >= timeout or failing:
                    if not failing:
                        LOG.warning("odczyt PLC trwa dłużej niż timeout (%.1f s): zgłaszam PLC offline", timeout)
                        failing = True
                    evaluation = evaluator.on_read_failed()
                    if age >= ABANDON_FACTOR * timeout:
                        pending.cancel()
                        pending.add_done_callback(_consume)
                        pending = None
                        if not abandoned_logged:
                            LOG.warning("porzucono zawieszony odczyt PLC (%.1f s); nowy klient i nowy odczyt", age)
                            abandoned_logged = True
                        reset = getattr(driver, "reset", None)
                        if reset is not None:
                            await reset()
                else:
                    evaluation = Evaluation(link_status=None)        # wolna odpowiedź: cykl bez publikacji

            if evaluation.skipped:
                LOG.warning("pominięto metryki o wartości nieskończonej lub NaN: %s", ", ".join(evaluation.skipped))
            if evaluation.readings:
                publisher.publish_batch(
                    [build_message(config.site, config.line, reading, ts) for reading in evaluation.readings]
                )
            else:
                publisher.drain()               # także w rozgrzewce: opróżniamy to, co czeka w buforze
            states.update(evaluation.states, evaluation.details)
            health.touch(health_file)

            # Cykl trwa dokładnie jeden okres; opóźnione cykle są pomijane, a nie nadrabiane seriami.
            next_start = cycle_start + interval
            if next_start <= clock():
                next_start = clock()
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, next_start - clock()))
            except asyncio.TimeoutError:
                pass
            cycle_start = next_start
    finally:
        if pending is not None:
            pending.cancel()
            pending.add_done_callback(_consume)


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # pymodbus dopisuje do każdego komunikatu ERROR ostatnie surowe ramki (">>>>> send:/recv:"); logger `pymodbus.logging`
    # dziedziczy poziom po `pymodbus`, więc CRITICAL usuwa i wpisy, i ramki. Zdarzenia stanu loguje StateLogger.
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)


async def _amain() -> int:
    try:
        config = load_config(os.environ.get("DEVICES_CONFIG", "/config/devices.yaml"))
    except ConfigError as exc:
        LOG.error("błąd konfiguracji: %s", exc)
        return 2
    try:
        mqtt_user, mqtt_password = os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"]
    except KeyError as exc:
        LOG.error("brak zmiennej środowiskowej %s", exc)
        return 2

    buffer_max = int(os.environ.get("COLLECTOR_BUFFER_MAX", "20000"))
    transport = PahoTransport(
        os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")), mqtt_user, mqtt_password
    )
    publisher = Publisher(transport, buffer_max)
    driver = ModbusPlcDriver(config.plc)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    LOG.info("start: PLC %s:%s (FC04, rejestry %d-%d), temat %s/%s/<urządzenie>/<metryka>",
             config.plc.host, config.plc.port, config.plc.read_start,
             config.plc.read_start + config.plc.read_count - 1, config.site, config.line)
    publisher.start()
    try:
        await run(config, driver, publisher, Evaluator(config), stop,
                  health_file=os.environ.get("HEALTH_FILE", health.DEFAULT_PATH))
    finally:
        await driver.close()
        publisher.stop()
        LOG.info("zatrzymano")
    return 0


def main() -> int:
    _setup_logging()
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
