"""Historia symulatora przez Mosquitto i ingest do bazy (aip-test): dokładne liczby wierszy, idempotencja, uzupełnianie luk
jednej metryki (K5-U1), sterowanie przepływem z odczytem bazy kontem app_reader (K5-D1). Pilotaż 1 doby – run-perf.sh."""
from __future__ import annotations

import os
import time
import uuid

import pytest
import psycopg

from dbtools import REPO, admin_connect
from ingest.config import load_config as load_ingest_config
from ingest_support import HAS_BROKER, IngestHarness, count_rows, make_store
from simulator.backfill import Db, Plan, Window, fill_gaps, refresh_statements, run

pytestmark = pytest.mark.skipif(not HAS_BROKER, reason="wymaga brokera Mosquitto i bazy (projekt aip-test)")

# Zakresy przed „teraz” (ingest odrzuca przyszłość), po kotwicy liczników testów 17.11.2026 i montażu łożyska 08.09.2026.
END = (int(time.time()) // 3600 - 2) * 3600


def sim_client():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t-bf-" + uuid.uuid4().hex[:6], protocol=mqtt.MQTTv5)
    client.username_pw_set(os.environ["MQTT_SIM_USER"], os.environ["MQTT_SIM_PASSWORD"])
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    return client


@pytest.fixture
def env(pg, migrated_db, role_passwords, make_sim):
    config = load_ingest_config(REPO / "config" / "devices.yaml")
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    harness = IngestHarness(config, store, "t-ingest-" + uuid.uuid4().hex[:6]).start()
    harness.wait_connected()
    reader = psycopg.connect(host=pg["host"], port=pg["port"], dbname=migrated_db, user="app_reader",
                             password=role_passwords["app_reader"], autocommit=True, options="-c statement_timeout=10000")
    client = sim_client()
    yield {"sim": make_sim(), "db": Db(reader), "client": client, "pg": pg, "dbname": migrated_db}
    client.loop_stop()
    client.disconnect()
    reader.close()
    harness.stop(forget=True)
    store.close()


def test_history_lands_exactly_once_and_gaps_of_one_metric_are_refilled(env):
    sim, db, pg, dbname = env["sim"], env["db"], env["pg"], env["dbname"]
    start = END - 600                                                   # 10 min liczników (1 s) + 10 min pompy (1 min)
    plan = Plan(sim, start, END)
    stats = run(plan, Window(env["client"], 100), db, start, END, chunk_s=300)
    expected = 600 * 4 * 6 + 10 * 5
    assert stats["messages"] == expected and stats["chunks"] == 2
    time.sleep(2)
    assert count_rows(pg, dbname, "source = 'sim'") == expected
    again = run(plan, Window(env["client"], 100), db, start, END, chunk_s=300)          # idempotencja
    time.sleep(2)
    assert again["messages"] == expected and count_rows(pg, dbname, "source = 'sim'") == expected
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


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get("AIP_PERF") != "1", reason="pilotaż 1 doby: tests/run-perf.sh -k backfill_pilot")
def test_backfill_pilot_one_day(env):
    """Pilotaż 1 doby (K5-U2, K5-U3): tempo, przyrost bazy i bajty na wiersz. RAM/CPU kontenerów i kolejkę brokera
    mierzy równolegle `docker stats` na hoście (procedura w raporcie k5). Ingest działa tu w kontenerze pytest
    (IngestHarness, wartości domyślne usługi: paczka 100, flush 1 s)."""
    sim, db, pg, dbname = env["sim"], env["db"], env["pg"], env["dbname"]
    end = END - END % 86400
    start = end - 86400
    plan = Plan(sim, start, end)
    with admin_connect(pg, dbname) as conn:
        size0 = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    stats = run(plan, Window(env["client"], 100), db, start, end, chunk_s=300)
    until_rows = time.monotonic() + 120
    expected = 86400 * 4 * 6 + 1440 * 5
    while count_rows(pg, dbname, "source = 'sim'") < expected and time.monotonic() < until_rows:
        time.sleep(2)
    with admin_connect(pg, dbname) as conn:
        conn.execute("CHECKPOINT")
        size1 = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        table = conn.execute("SELECT hypertable_size('measurements')").fetchone()[0]
    rows = count_rows(pg, dbname, "source = 'sim'")
    print(f"\n[pilotaż] {stats['messages']} wiadomości w {stats['elapsed_s']:.0f} s ({stats['rate']:.0f}/s), porcji "
          f"{stats['chunks']}, oczekiwanie na bazę {stats['waited_s']:.0f} s; wiersze {rows}; przyrost bazy "
          f"{(size1 - size0) / 2**20:.0f} MiB, measurements {table / 2**20:.0f} MiB = {table / max(rows, 1):.0f} B/wiersz "
          f"(bez kompresji); 14 dób liczników ok. {table / max(rows, 1) * 14 * 86400 * 24 / 2**30:.1f} GiB przed kompresją")
    assert rows == expected == stats["messages"]
