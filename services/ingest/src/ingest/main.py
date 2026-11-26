"""Pętla ingestu. Uruchomienie: python -m ingest.main.

Kolejność: konfiguracja (błąd = kod 2) -> czekanie na bazę i schemat + synchronizacja devices -> start MQTT -> pętla.
Brak bazy, schematu lub brokera to stany (z ponawianiem i logiem), a nie powód zakończenia procesu (uwaga U4).
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from collections.abc import Callable

from . import health
from .config import ConfigError, IngestConfig, load_config
from .mqtt_in import MqttInput
from .pipeline import BACKOFF_INITIAL_S, BACKOFF_MAX_S, Incoming, Pipeline
from .store import Store, StoreUnavailable

LOG = logging.getLogger("ingest")

SUMMARY_S = 60.0


def wait_for_database(config: IngestConfig, store, stop: threading.Event, health_file: str) -> bool:
    """Synchronizuje devices; do skutku ponawia z cofaniem. False, jeśli przerwano sygnałem zatrzymania."""
    failures = 0
    announced = False
    while not stop.is_set():
        try:
            upserted, disabled = store.sync_devices(config)
            LOG.info("devices zsynchronizowane z configiem: %d wpisów, wyłączono %d", upserted, disabled)
            if announced:
                LOG.info("baza i schemat gotowe")
            return True
        except StoreUnavailable as exc:
            failures += 1
            if not announced:
                announced = True
                LOG.warning("czekam na bazę i schemat: %s", exc)
            delay = min(BACKOFF_INITIAL_S * 2 ** (failures - 1), BACKOFF_MAX_S)
            deadline = time.monotonic() + delay
            while not stop.is_set() and time.monotonic() < deadline:
                health.touch(health_file)
                stop.wait(0.2)
    return False


def serve(
    config: IngestConfig,
    store,
    source,
    pipeline: Pipeline,
    stop: threading.Event,
    health_file: str = health.DEFAULT_PATH,
    summary_s: float = SUMMARY_S,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Pętla główna. `source` ma start(), stop(), get(timeout); potwierdzenia wysyła potok."""
    if not wait_for_database(config, store, stop, health_file):
        return
    source.start()
    next_summary = clock() + summary_s
    try:
        while not stop.is_set():
            item = source.get(0.2)
            while item is not None:
                pipeline.feed(item)
                if pipeline.batch_full:
                    break
                item = source.get(0.0)
            pipeline.tick()
            health.touch(health_file)
            if clock() >= next_summary:
                LOG.info(pipeline.summary())
                next_summary = clock() + summary_s
    finally:
        pipeline.flush()          # przy niedostępnej bazie nic nie zostanie potwierdzone: broker dostarczy ponownie
        source.stop()
        LOG.info(pipeline.summary())


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main() -> int:
    _setup_logging()
    try:
        config = load_config(os.environ.get("DEVICES_CONFIG", "/config/devices.yaml"))
    except ConfigError as exc:
        LOG.error("błąd konfiguracji: %s", exc)
        return 2
    try:
        mqtt_user, mqtt_password = os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"]
        db_password = os.environ["DB_PASSWORD"]
    except KeyError as exc:
        LOG.error("brak zmiennej środowiskowej %s", exc)
        return 2

    store = Store(
        host=os.environ.get("DB_HOST", "timescaledb"), port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "energy"), user=os.environ.get("DB_USER", "app_writer"),
        password=db_password,
    )
    source = MqttInput(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")),
                       mqtt_user, mqtt_password, client_id=os.environ.get("INGEST_CLIENT_ID", "aip-ingest"))
    pipeline = Pipeline(
        config, store, ack=source.ack,
        batch_max=int(os.environ.get("INGEST_BATCH_MAX", "100")),
        flush_s=float(os.environ.get("INGEST_FLUSH_S", "1.0")),
        max_future_s=float(os.environ.get("INGEST_MAX_FUTURE_S", "300")),
        max_past_days=float(os.environ.get("INGEST_MAX_PAST_DAYS", "400")),
    )
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    LOG.info("start: tematy %s/<urządzenie>/<metryka>, urządzeń w configu: %d, paczka %s lub %s s",
             ", ".join(f"{s}/{l}" for s, l in config.site_lines()), len(config.devices), os.environ.get("INGEST_BATCH_MAX", "100"),
             os.environ.get("INGEST_FLUSH_S", "1.0"))
    try:
        serve(config, store, source, pipeline, stop, health_file=os.environ.get("HEALTH_FILE", health.DEFAULT_PATH))
    finally:
        store.close()
        LOG.info("zatrzymano")
    return 0


if __name__ == "__main__":
    sys.exit(main())
