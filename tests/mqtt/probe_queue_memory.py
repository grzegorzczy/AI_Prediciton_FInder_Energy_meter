#!/usr/bin/env python3
"""Sonda pamięci Mosquitto przy pełnej kolejce sesji ingestu (E2-PLC2, P2-g). Uruchamiana ręcznie w projekcie aip-test
(tylko tam, nie na produkcji): zapisuje sesję trwałą ingestu, rozłącza ją, publikuje N wiadomości QoS 1 jak collector
i zostawia je w kolejce. Pamięć kontenera odczytuje się potem `docker stats` z hosta. Hasła z env (MQTT_*), nie z argumentów."""
from __future__ import annotations

import json
import os
import sys
import time

import paho.mqtt.client as mqtt

HOST, PORT = os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883"))
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 80000
METRICS = ["active_power", "reactive_power", "apparent_power", "power_factor", "frequency", "voltage", "current", "energy_import_wh",
           "energy_export_wh", "meter_status", "meter_error_count", "meter_data_age_ms", "reactive_pos_varh", "reactive_neg_varh",
           "thd_voltage", "thd_current", "phase_angle", "meter_temperature", "run_time", "link_status"]


def client(user_env: str, password_env: str, client_id: str, clean: bool) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311, clean_session=clean)
    c.username_pw_set(os.environ[user_env], os.environ[password_env])
    c.connect(HOST, PORT)
    c.loop_start()
    return c


def main() -> int:
    ingest = client("MQTT_INGEST_USER", "MQTT_INGEST_PASSWORD", "ingest-probe", False)
    ingest.subscribe("+/+/+/+", qos=1)
    time.sleep(1.0)
    ingest.loop_stop()
    ingest.disconnect()                                           # sesja trwała zostaje, wiadomości będą kolejkowane
    time.sleep(0.5)
    collector = client("MQTT_COLLECTOR_USER", "MQTT_COLLECTOR_PASSWORD", "collector-probe", True)
    sent = 0
    start = time.monotonic()
    pending = []
    for i in range(COUNT):
        metric = METRICS[i % len(METRICS)]
        device = "plc-01" if metric == "link_status" else "finder_7m24_1"
        payload = json.dumps({"ts": "2026-11-25T08:16:10.574Z", "value": 1256171.0 + i, "unit": "varh", "source": "real"})
        pending.append(collector.publish(f"zaklad1/linia1/{device}/{metric}", payload, qos=1))
        sent += 1
        if len(pending) >= 500:
            for info in pending:
                info.wait_for_publish(timeout=30)
            pending.clear()
    for info in pending:
        info.wait_for_publish(timeout=30)
    print(f"opublikowano {sent} wiadomości w {time.monotonic() - start:.1f} s")
    collector.loop_stop()
    collector.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
