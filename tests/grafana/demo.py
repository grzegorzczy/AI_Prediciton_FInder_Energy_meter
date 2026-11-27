"""Stos demonstracyjny do zrzutów E3-k6 (K6-D3), uruchamiany przez tests/run-demo.sh w kontenerze pytest projektu aip-demo.

1. migracje bazy `energy` i dane syntetyczne Findera (jak testy paneli etapu 2; Finder nie ma tu danych na żywo – bez PLC);
2. ingest (prawdziwy `ingest.main`) i symulator na żywo (`simulator.main`, daty jak w k7: kotwica liczników = koniec − 24 h,
   łożysko = koniec − 84 dni);
3. historia narzędziem `simulator.backfill` (liczniki AIP_DEMO_METER_HOURS h co 1 s, pompa 84 dni co 1 min), ręczne
   odświeżenie agregatów, potem uzupełnienie minut między końcem historii a startem trybu na żywo;
4. ingest i symulator działają dalej, aż `sh tests/run-demo.sh down`."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))      # dbtools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dbtools import MIGRATE, MIGRATIONS, admin_connect, build_panel_data          # noqa: E402
from sim_history import dated_config, load_history, start_ingest                 # noqa: E402


def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def main() -> int:
    pg = {"host": os.environ["DB_HOST"], "port": int(os.environ.get("DB_PORT", "5432")), "user": "postgres",
          "password": os.environ["POSTGRES_PASSWORD"]}
    writer, reader = secrets.token_hex(16), os.environ["TEST_APP_READER_PASSWORD"]
    env = {**os.environ, "POSTGRES_DB": "energy", "POSTGRES_USER": "postgres", "APP_WRITER_PASSWORD": writer,
           "APP_READER_PASSWORD": reader, "MIGRATIONS_DIR": str(MIGRATIONS), "DB_WAIT_S": "30"}
    subprocess.run([sys.executable, str(MIGRATE)], env=env, check=True, timeout=300)
    with admin_connect(pg, "energy") as conn:
        if not conn.execute("SELECT count(*) FROM devices").fetchone()[0]:
            build_panel_data(conn)
            log("dane syntetyczne Findera gotowe")
    hours = float(os.environ.get("AIP_DEMO_METER_HOURS", "24"))
    end = int(time.time()) // 60 * 60
    anchor, bearing = end - int(hours * 3600), end - 84 * 86400
    config_path = "/tmp/demo-devices.yaml"
    with open(config_path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(dated_config(anchor, bearing), handle, allow_unicode=True, sort_keys=False)
    ingest = start_ingest(pg, "energy", writer, "aip-demo-ingest")
    live = subprocess.Popen([sys.executable, "-m", "simulator.main"], env={
        **os.environ, "DEVICES_CONFIG": config_path, "MQTT_USER": os.environ["MQTT_SIM_USER"],
        "MQTT_PASSWORD": os.environ["MQTT_SIM_PASSWORD"], "SIM_CACHE": "/tmp/energy-days.json", "SIM_CLIENT_ID": "aip-demo-simulator",
        "HEALTH_FILE": "/tmp/simulator-health", "LOG_LEVEL": "WARNING"})
    log(f"ingest i symulator na żywo działają; historia: liczniki {hours:g} h, pompa 84 dni")
    info = load_history(pg, "energy", reader, writer, meter_hours=hours, pump_days=84, keep_devices=False, ingest=ingest, end=end)
    log(f"historia gotowa: {info['stats']['messages']} wiadomości, {info['stats']['rate']:.0f}/s")
    # minuty trybu na żywo odrzucone przez limit sim ingestu w czasie wgrywania (K4) – uzupełnienie tym samym narzędziem
    import paho.mqtt.client as mqtt
    import psycopg
    from simulator.backfill import Db, Plan, Window, run
    from simulator.config import load_config_dict
    from simulator.samples import Simulator

    sim =Simulator(load_config_dict(dated_config(anchor, bearing)), None)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aip-demo-fill", protocol=mqtt.MQTTv5)
    client.username_pw_set(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    fill_end = int(time.time()) // 60 * 60 - 60
    with psycopg.connect(host=pg["host"], port=pg["port"], dbname="energy", user="app_reader", password=reader,
                         autocommit=True, options="-c statement_timeout=10000") as conn:
        stats = run(Plan(sim, end, fill_end), Window(client, 100), Db(conn), end, fill_end)
    client.loop_stop()
    client.disconnect()
    log(f"uzupełniono minuty od końca historii do teraz: {stats['messages']} wiadomości; stos gotowy do zrzutów")
    while ingest.poll() is None and live.poll() is None:
        time.sleep(30)
    log(f"proces zakończony: ingest {ingest.poll()}, symulator {live.poll()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
