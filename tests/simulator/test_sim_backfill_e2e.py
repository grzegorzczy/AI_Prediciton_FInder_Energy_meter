"""Historia symulatora przez Mosquitto i ingest do bazy (aip-test): dokładne liczby wierszy, idempotencja, uzupełnianie luk
jednej metryki (K5-U1), sterowanie przepływem z odczytem bazy kontem app_reader (K5-D1). Pilotaż 1 doby – run-perf.sh."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid

import pytest
import psycopg

from dbtools import REPO, admin_connect
from ingest.config import load_config as load_ingest_config
from ingest_support import HAS_BROKER, IngestHarness, count_rows, make_store
from simulator.backfill import Db, Plan, Window, fill_gaps, incomplete_minutes, refresh_statements, run

pytestmark = pytest.mark.skipif(not HAS_BROKER, reason="wymaga brokera Mosquitto i bazy (projekt aip-test)")

# Zakresy przed „teraz” (ingest odrzuca przyszłość), po kotwicy liczników testów 17.11.2026 i montażu łożyska 08.09.2026.
END = (int(time.time()) // 3600 - 2) * 3600            # pełna godzina


def sim_client():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t-bf-" + uuid.uuid4().hex[:6], protocol=mqtt.MQTTv5)
    client.username_pw_set(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    return client


@pytest.fixture
def base(pg, migrated_db, role_passwords, make_sim):
    reader = psycopg.connect(host=pg["host"], port=pg["port"], dbname=migrated_db, user="app_reader",
                             password=role_passwords["app_reader"], autocommit=True, options="-c statement_timeout=10000")
    client = sim_client()
    yield {"sim": make_sim(), "db": Db(reader), "client": client, "pg": pg, "dbname": migrated_db,
           "writer_password": role_passwords["app_writer"]}
    client.loop_stop()
    client.disconnect()
    reader.close()


@pytest.fixture
def env(base):
    config = load_ingest_config(REPO / "config" / "devices.yaml")
    store = make_store(base["pg"], base["dbname"], base["writer_password"])
    harness = IngestHarness(config, store, "t-ingest-" + uuid.uuid4().hex[:6]).start()
    harness.wait_connected()
    yield base
    harness.stop(forget=True)
    store.close()


def test_history_lands_exactly_once_and_gaps_of_one_metric_are_refilled(env):
    sim, db, pg, dbname = env["sim"], env["db"], env["pg"], env["dbname"]
    start = END - 600                                                   # 10 min liczników (1 s) + 10 min pompy (1 min)
    plan = Plan(sim, start, END)
    stats = run(plan, Window(env["client"], 100), db, start, END)
    expected = 600 * 4 * 6 + 10 * 5
    assert stats["messages"] == expected and stats["chunks"] == 2
    time.sleep(2)
    assert count_rows(pg, dbname, "source = 'sim'") == expected
    again = run(plan, Window(env["client"], 100), db, start, END)          # wznowienie: pełne minuty pominięte
    time.sleep(2)
    assert again["messages"] == 0 and again["device_minutes_skipped"] == 50 and count_rows(pg, dbname, "source = 'sim'") == expected
    with admin_connect(pg, dbname) as conn:                                  # luka jednej metryki (K5-U1)
        conn.execute("DELETE FROM measurements WHERE device_id = 'sim_chlodnia' AND metric = 'reactive_power' "
                     "AND time >= to_timestamp(%s) AND time < to_timestamp(%s)", (start + 120, start + 130))
        conn.execute("DELETE FROM measurements WHERE device_id = 'sim_pump_p101' AND metric = 'flow' "
                     "AND time = to_timestamp(%s)", (start + 300,))
    assert count_rows(pg, dbname, "source = 'sim'") == expected - 11
    result = fill_gaps(plan, Window(env["client"], 100), db, start, END)
    assert result["missing_before"] == 2 and result["missing_after"] == 0
    assert result["messages"] == 60 * 6 + 5                              # minuta licznika + minuta pompy, nic więcej
    assert count_rows(pg, dbname, "source = 'sim'") == expected
    with admin_connect(pg, dbname) as conn:                                  # ręczne odświeżenie agregatów (procedura k7)
        for statement in refresh_statements(start, END):
            conn.execute(statement)
        minutes = conn.execute("SELECT count(*), min(active_power_n), max(active_power_n) FROM energy_1m "
                               "WHERE device_id LIKE 'sim_%%' AND bucket >= to_timestamp(%s) AND bucket < to_timestamp(%s)",
                               (start, END)).fetchone()
        pump = conn.execute("SELECT count(*), min(vibration_n), max(vibration_n), count(*) FILTER (WHERE speed_n = 1) "
                            "FROM pump_1m_calc WHERE device_id = 'sim_pump_p101' "
                            "AND bucket >= to_timestamp(%s) AND bucket < to_timestamp(%s)", (start, END)).fetchone()
    assert minutes == (40, 60, 60) and pump == (10, 1, 1, 10)


def test_reader_account_cannot_write(env):
    with pytest.raises(psycopg.Error):
        env["db"].conn.execute("DELETE FROM measurements")


def proc_usage(pid: int) -> tuple[float, int]:
    """CPU (s) i szczyt RSS (KiB) procesu z /proc."""
    with open(f"/proc/{pid}/stat") as handle:
        fields = handle.read().rsplit(")", 1)[1].split()
    cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    with open(f"/proc/{pid}/status") as handle:
        hwm = next(int(line.split()[1]) for line in handle if line.startswith("VmHWM"))
    return cpu, hwm


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get("AIP_PERF") != "1", reason="pilotaż 1 doby: tests/run-perf.sh -k backfill_pilot")
def test_backfill_pilot_one_day(base):
    """Pilotaż 1 doby (K5-U2, K5-U3): tempo, przyrost bazy, bajty na wiersz, zaległość (wysłane − w bazie), CPU i szczyt RAM
    osobno dla ingestu (prawdziwy `python -m ingest.main` w osobnym procesie, ustawienia domyślne usługi) i narzędzia.
    Baza perf: poza tmpfs, ale fsync=off – tempo to górna granica; produkcyjny pilotaż w k7."""
    sim, db, pg, dbname = base["sim"], base["db"], base["pg"], base["dbname"]
    ingest_env = dict(os.environ, MQTT_USER=os.environ["MQTT_INGEST_USER"], MQTT_PASSWORD=os.environ["MQTT_INGEST_PASSWORD"],
                      DB_HOST=pg["host"], DB_PORT=str(pg["port"]), DB_NAME=dbname, DB_USER="app_writer",
                      DB_PASSWORD=base["writer_password"], DEVICES_CONFIG=str(REPO / "config" / "devices.yaml"),
                      INGEST_CLIENT_ID="t-ingest-pilot-" + uuid.uuid4().hex[:6], HEALTH_FILE="/tmp/ingest-pilot-health",
                      LOG_LEVEL="WARNING")
    ingest = subprocess.Popen([sys.executable, "-m", "ingest.main"], env=ingest_env)
    try:
        time.sleep(3)
        assert ingest.poll() is None, "ingest nie wystartował"
        end = END - END % 86400
        start = end - 86400
        plan = Plan(sim, start, end)
        with admin_connect(pg, dbname) as conn:
            size0 = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        window = Window(base["client"], 100)
        backlog, stop = [], threading.Event()

        def sample():                 # K5-U3: wysłane, a jeszcze nie w bazie (kolejka brokera + ingest) co 10 s
            while not stop.wait(10):
                backlog.append(window.sent - count_rows(pg, dbname, "source = 'sim'"))

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        tool_cpu0 = time.process_time()
        stats = run(plan, window, db, start, end)
        tool_cpu = time.process_time() - tool_cpu0
        stop.set()
        sampler.join()
        ingest_cpu, ingest_hwm = proc_usage(ingest.pid)
        tool_hwm = proc_usage(os.getpid())[1]
        expected = 86400 * 4 * 6 + 1440 * 5
        with admin_connect(pg, dbname) as conn:
            conn.execute("CHECKPOINT")
            size1 = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            table = conn.execute("SELECT hypertable_size('measurements')").fetchone()[0]
            t0 = time.monotonic()
            gaps = incomplete_minutes(plan, db, start, end)
            check_s = time.monotonic() - t0
        rows = count_rows(pg, dbname, "source = 'sim'")
        print(f"\n[pilotaż] {stats['messages']} wiadomości w {stats['elapsed_s']:.0f} s ({stats['rate']:.0f}/s), porcji "
              f"{stats['chunks']}, oczekiwanie na bazę {stats['waited_s']:.0f} s; wiersze {rows}"
              f"\n[pilotaż] zaległość (wysłane − w bazie) co 10 s: maks. {max(backlog, default=0)}, "
              f"średnio {sum(backlog) / max(len(backlog), 1):.0f}, próbek {len(backlog)}"
              f"\n[pilotaż] ingest: CPU {ingest_cpu:.0f} s ({100 * ingest_cpu / stats['elapsed_s']:.0f}% rdzenia), "
              f"szczyt RSS {ingest_hwm / 1024:.0f} MiB; narzędzie: CPU {tool_cpu:.0f} s "
              f"({100 * tool_cpu / stats['elapsed_s']:.0f}%), szczyt RSS procesu pytest {tool_hwm / 1024:.0f} MiB"
              f"\n[pilotaż] przyrost bazy {(size1 - size0) / 2**20:.0f} MiB, measurements {table / 2**20:.0f} MiB = "
              f"{table / max(rows, 1):.0f} B/wiersz (bez kompresji); 14 dób liczników ok. "
              f"{table / max(rows, 1) * 14 * 86400 * 24 / 2**30:.1f} GiB przed kompresją; kontrola luk doby {check_s:.1f} s")
        assert rows == expected == stats["messages"] and gaps == {}
    finally:
        ingest.terminate()
        ingest.wait(15)
