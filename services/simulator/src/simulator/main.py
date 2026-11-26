"""Usługa symulatora (E3-k3): tryb na żywo. Konfiguracja z config/devices.yaml (sekcja `simulator`), konto MQTT z .env.

Kod wyjścia 2 = błąd konfiguracji (np. brak `meter_anchor` lub `bearing_installed_at` do wdrożenia k7, brak konta MQTT);
komunikat w logu mówi, co ustawić.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time

from . import MODEL_VERSION, health
from .config import ConfigError, load_config
from .live import LiveLoop
from .publisher import PahoTransport, Publisher
from .samples import Simulator

LOG = logging.getLogger("simulator")


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = load_config(os.environ.get("DEVICES_CONFIG", "/config/devices.yaml"))
        cache_path = os.environ.get("SIM_CACHE", "/var/lib/simulator/energy-days.json") or None
        t0 = time.perf_counter()
        sim = Simulator(config, cache_path)
        user, password = os.environ.get("MQTT_USER", ""), os.environ.get("MQTT_PASSWORD", "")
    except ConfigError as exc:
        LOG.error("błąd konfiguracji: %s", exc)
        return 2
    if not user or not password:
        # K3-D1: bez konta nie kończymy procesu (pętla restartów); broker odrzuci połączenie, paho ponawia z cofaniem,
        # a błąd autoryzacji jest logowany raz na epizod
        LOG.error("brak konta MQTT symulatora (MQTT_SIM_USER / MQTT_SIM_PASSWORD w .env): dane nie będą wysyłane, "
                  "dopóki konto nie zostanie dopisane i kontener odtworzony")
    now = int(time.time())
    source = sim.cache.source
    sim.prime(now)
    LOG.info("start: model %s, %d liczników i %d pomp w %s/%s, kotwica liczników %s, pamięć sum: %s, start liczników %.1f s",
             MODEL_VERSION, len(sim.meters), len(sim.pumps), config.site, config.line,
             config.require_meter_anchor().isoformat(), source, time.perf_counter() - t0)
    for dev_id, pump in sim.pumps.items():
        LOG.info("pompa %s: montaż łożyska %s, postęp x = %.3f", dev_id,
                 config.require_bearing_installed_at(config.device(dev_id)).isoformat(), pump.progress(now))
    transport = PahoTransport(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")),
                              user, password, os.environ.get("SIM_CLIENT_ID", "aip-simulator"))
    publisher = Publisher(transport, int(os.environ.get("SIM_BUFFER_MAX", "36000")))
    health_file = os.environ.get("HEALTH_FILE", health.DEFAULT_PATH)
    loop = LiveLoop(sim, publisher, on_tick=lambda _n: health.touch(health_file))
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    publisher.start()
    try:
        loop.run(stop)
    finally:
        publisher.stop()
        sim.cache.flush()
        LOG.info("zatrzymano: wysłano %d wiadomości, odrzucono z bufora %d, pominięto %d s",
                 publisher.sent_total, publisher.dropped_total, loop.skipped_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
