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
from .evaluator import Evaluator
from .messages import build_message, format_ts
from .publisher import PahoTransport, Publisher
from .statelog import StateLogger

LOG = logging.getLogger("collector")


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
    interval = config.plc.poll_interval_s
    states = state_logger or StateLogger(clock)
    failing = False
    next_tick = clock()

    while not stop.is_set():
        try:
            registers = await driver.read()
            ts = format_ts(wall())          # jeden znacznik na cały odczyt (D2), chwila odbioru odpowiedzi
            evaluation = evaluator.evaluate(registers)
            if failing:
                failing = False
        except SourceError as exc:
            ts = format_ts(wall())
            if not failing:
                LOG.warning("odczyt PLC nie powiódł się: %s", exc)
                failing = True
            evaluation = evaluator.on_read_failed()

        if evaluation.skipped:
            LOG.warning("pominięto metryki o wartości nieskończonej lub NaN: %s", ", ".join(evaluation.skipped))
        if evaluation.readings:
            publisher.publish_batch(
                [build_message(config.site, config.line, reading, ts) for reading in evaluation.readings]
            )
        else:
            publisher.drain()               # także w rozgrzewce: opróżniamy to, co czeka w buforze
        states.update(evaluation.states)
        health.touch(health_file)

        # Pomijamy opóźnione cykle zamiast nadrabiać je seriami.
        next_tick += interval
        now = clock()
        if next_tick <= now:
            next_tick = now + interval
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, next_tick - clock()))
        except asyncio.TimeoutError:
            pass


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("pymodbus").setLevel(logging.ERROR)   # biblioteka loguje każdą próbę łączenia


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
