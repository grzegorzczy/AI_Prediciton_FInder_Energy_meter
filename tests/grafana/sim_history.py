"""Dane symulatora dla paneli „Flota” i „Pompa” (E3-k6): historia wgrana narzędziem `simulator.backfill` przez MQTT (QoS 1,
sterowanie przepływem) i prawdziwy ingest (`python -m ingest.main` w osobnym procesie) do bazy, którą widzi Grafana.
Używane przez fixturę testów `slow` (test_grafana_sim_panels.py) i przez stos demonstracyjny (tests/run-demo.sh, demo.py).

Daty liczone od „teraz” (ingest odrzuca przyszłość): kotwica liczników = koniec − `meter_hours`, montaż łożyska =
koniec − `pump_days` (jak w k7: 84 dni → postęp degradacji x = 0,70 na końcu)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import yaml

REPO = Path(os.environ.get("REPO_DIR", Path(__file__).resolve().parents[2]))
DEVICES = REPO / "config" / "devices.yaml"
ISO = "%Y-%m-%dT%H:%M:%SZ"


def dated_config(anchor: int, bearing: int) -> dict:
    """Surowy config z devices.yaml z ustawioną kotwicą liczników i montażem łożyska (daty testu zamiast dat wdrożenia k7)."""
    raw = yaml.safe_load(DEVICES.read_text(encoding="utf-8"))
    section = raw["simulator"]
    section["meter_anchor"] = datetime.fromtimestamp(anchor, timezone.utc).strftime(ISO)
    for dev in section["devices"]:
        if dev["kind"] == "pump":
            dev["bearing_installed_at"] = datetime.fromtimestamp(bearing, timezone.utc).strftime(ISO)
    return raw


def start_ingest(pg: dict, dbname: str, writer_password: str, client_id: str | None = None) -> subprocess.Popen:
    env = dict(os.environ, MQTT_USER=os.environ["MQTT_INGEST_USER"], MQTT_PASSWORD=os.environ["MQTT_INGEST_PASSWORD"],
               DB_HOST=pg["host"], DB_PORT=str(pg["port"]), DB_NAME=dbname, DB_USER="app_writer", DB_PASSWORD=writer_password,
               DEVICES_CONFIG=str(DEVICES), INGEST_CLIENT_ID=client_id or "t-ingest-hist-" + uuid.uuid4().hex[:6],
               HEALTH_FILE=f"/tmp/ingest-hist-{uuid.uuid4().hex[:6]}", LOG_LEVEL="WARNING")
    return subprocess.Popen([sys.executable, "-m", "ingest.main"], env=env)


def admin(pg: dict, dbname: str) -> psycopg.Connection:
    return psycopg.connect(dbname=dbname, autocommit=True, connect_timeout=5, **pg)


def wait_for_sim_devices(pg: dict, dbname: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        with admin(pg, dbname) as conn:
            if conn.execute("SELECT count(*) FROM devices WHERE source = 'sim'").fetchone()[0] >= 5:
                return
        if time.monotonic() > deadline:
            raise RuntimeError("ingest nie zarejestrował urządzeń symulatora")
        time.sleep(0.5)


def load_history(pg: dict, dbname: str, reader_password: str, writer_password: str, meter_hours: float = 2.0,
                 pump_days: int = 84, keep_devices: bool = True, ingest: subprocess.Popen | None = None,
                 end: int | None = None) -> dict:
    """Wgrywa historię: liczniki sim co 1 s przez `meter_hours`, pompa co 1 min przez `pump_days`, do pełnej minuty „teraz”.
    keep_devices: przywraca po synchronizacji ingestu dotychczasowe wiersze `devices` (ingest wyłącza urządzenia spoza configu,
    a dane syntetyczne testów etapu 2 mają drugi licznik)."""
    import paho.mqtt.client as mqtt

    from simulator.backfill import Db, Plan, Window, refresh_statements, run
    from simulator.config import load_config_dict
    from simulator.samples import Simulator

    end = end or int(time.time()) // 60 * 60
    anchor, bearing = end - int(meter_hours * 3600), end - pump_days * 86400
    with admin(pg, dbname) as conn:
        snapshot = conn.execute("SELECT device_id, name, enabled, meta FROM devices").fetchall()
    own_ingest = ingest is None
    ingest = ingest or start_ingest(pg, dbname, writer_password)
    client = None
    try:
        wait_for_sim_devices(pg, dbname)
        if keep_devices:
            with admin(pg, dbname) as conn:
                for device_id, name, enabled, meta in snapshot:
                    conn.execute("UPDATE devices SET name = %s, enabled = %s, meta = %s WHERE device_id = %s",
                                 (name, enabled, psycopg.types.json.Jsonb(meta), device_id))
        sim = Simulator(load_config_dict(dated_config(anchor, bearing)), None)
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t-hist-" + uuid.uuid4().hex[:6], protocol=mqtt.MQTTv5)
        client.username_pw_set(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
        client.max_inflight_messages_set(100)
        client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
        client.loop_start()
        reader = psycopg.connect(host=pg["host"], port=pg["port"], dbname=dbname, user="app_reader", password=reader_password,
                                 autocommit=True, options="-c statement_timeout=10000")
        with reader:
            plan = Plan(sim, bearing, end)
            stats = run(plan, Window(client, 100), Db(reader), bearing, end)
        with admin(pg, dbname) as conn:                     # ręczne odświeżenie agregatów jak w procedurze k7
            for statement in refresh_statements(bearing, end):
                conn.execute(statement)
        return {"end": end, "anchor": anchor, "bearing": bearing, "stats": stats, "raw_config": dated_config(anchor, bearing)}
    finally:
        if client is not None:
            client.loop_stop()
            client.disconnect()
        if own_ingest:
            ingest.terminate()
            ingest.wait(15)
