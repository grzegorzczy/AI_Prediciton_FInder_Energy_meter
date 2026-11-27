"""Migracja 012 (E3-k4): pump_1m i pump_1m_calc – wartości, minuta pracy, polityki, uprawnienia, przerwanie, odświeżanie
starego zakresu i zakresu skompresowanego (K4-U2)."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from dbtools import MIGRATIONS, admin_connect, series

PUMP = "sim_pump_p101"
SPLIT = re.compile(r"^-- migrate: next\s*$", flags=re.MULTILINE)
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=2)
MIN = timedelta(minutes=1)


def seed_pump(conn):
    conn.execute("INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
                 "(%s, 'Pompa', 'zaklad1', 'linia2', 'pump', 'sim', '{}') ON CONFLICT DO NOTHING", (PUMP,))


def pump_minute(conn, start, speed_expr="2950", seconds=60, vib="3.0 + g / 600.0"):
    for metric, expr, unit in (("vibration_rms", vib, "mm/s"), ("bearing_temperature", "60", "°C"),
                               ("motor_current", "18.5", "A"), ("flow", "35", "m³/h"), ("speed", speed_expr, "rpm")):
        series(conn, metric, start, seconds, expr, device=PUMP, unit=unit)


def refresh(conn, view="pump_1m", start=None, end=None):
    conn.execute(f"CALL refresh_continuous_aggregate('{view}', %s::timestamptz, %s::timestamptz)", (start, end))


def test_values_and_running_flag(pg, migrated_db):
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        pump_minute(conn, BASE)                                               # pełna minuta pracy
        pump_minute(conn, BASE + MIN, speed_expr="0", vib="0.1")              # postój
        pump_minute(conn, BASE + 2 * MIN, speed_expr="CASE WHEN g < 20 THEN 0 ELSE 2950 END")   # start zmiany: częściowa
        pump_minute(conn, BASE + 3 * MIN, seconds=1)                          # jedna próbka (np. po restarcie, K4-U4)
        refresh(conn)
        rows = conn.execute("SELECT bucket, vibration_n, vibration_avg, vibration_min, vibration_max, speed_n, run_n, "
                            "run_share, running, bearing_temperature_avg, flow_avg FROM pump_1m_calc ORDER BY bucket").fetchall()
    assert [r[0] for r in rows] == [BASE, BASE + MIN, BASE + 2 * MIN, BASE + 3 * MIN]
    full, stop, partial, single = rows
    assert full[1] == 60 and full[2] == pytest.approx(3.0 + 59 / 1200.0) and full[3] == 3.0
    assert (full[5], full[6], full[7], full[8]) == (60, 60, 1.0, True)
    assert (stop[6], stop[7], stop[8]) == (0, 0.0, False)
    assert (partial[5], partial[6], partial[8]) == (60, 40, False) and partial[7] == pytest.approx(40 / 60)
    assert (single[5], single[6], single[8]) == (1, 1, True)                  # K4-U4: etap 5 może wymagać min. speed_n
    assert full[9] == 60 and full[10] == 35


def test_minute_samples_like_history_give_the_same_flags(pg, migrated_db):
    """Historia k5 co 1 min: jedna próbka na minutę, ten sam znacznik pracy."""
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        for i, speed in enumerate((2950, 0, 2950)):
            for metric, value in (("vibration_rms", 3.3), ("speed", speed)):
                conn.execute("INSERT INTO measurements (time, device_id, metric, value, unit, source) "
                             "VALUES (%s, %s, %s, %s, '', 'sim')", (BASE + i * MIN, PUMP, metric, value))
        refresh(conn)
        flags = [r[0] for r in conn.execute("SELECT running FROM pump_1m_calc ORDER BY bucket").fetchall()]
    assert flags == [True, False, True]


def test_other_devices_create_no_rows(pg, migrated_db):
    with admin_connect(pg, migrated_db) as conn:
        conn.execute("INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
                     "('m1', 'Licznik', 'zaklad1', 'linia1', 'energy_meter', 'real', '{}')")
        series(conn, "active_power", BASE, 120, "100", device="m1", unit="W")
        refresh(conn)
        assert conn.execute("SELECT count(*) FROM pump_1m").fetchone()[0] == 0


def test_real_time_mode_shows_the_current_minute(pg, migrated_db):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        pump_minute(conn, now - timedelta(seconds=5), seconds=3)
        assert conn.execute("SELECT count(*) FROM pump_1m WHERE bucket >= %s", (now - 2 * MIN,)).fetchone()[0] >= 1


def jobs(conn):
    rows = conn.execute(
        "SELECT j.proc_name, j.config FROM timescaledb_information.jobs j "
        "JOIN timescaledb_information.continuous_aggregates c ON j.hypertable_name IN (c.view_name, c.materialization_hypertable_name) "
        "WHERE c.view_name = 'pump_1m'").fetchall()
    return {r[0]: r[1] for r in rows}


def test_policies(admin):
    j = jobs(admin)
    iv = lambda text: admin.execute("SELECT %s::interval", (text,)).fetchone()[0]  # noqa: E731
    refresh_cfg = j["policy_refresh_continuous_aggregate"]
    assert iv(refresh_cfg["start_offset"]) == iv("7 days") and iv(refresh_cfg["end_offset"]) == iv("1 minute")
    assert iv(j["policy_compression"]["compress_after"]) == iv("14 days")
    assert iv(j["policy_retention"]["drop_after"]) == iv("1 year")
    flags = admin.execute("SELECT materialized_only, compression_enabled FROM timescaledb_information.continuous_aggregates "
                          "WHERE view_name = 'pump_1m'").fetchone()
    assert flags == (False, True)


def test_permissions(reader, writer):
    for name in ("pump_1m", "pump_1m_calc"):
        reader.execute(f"SELECT * FROM {name} LIMIT 1").fetchall()
        with pytest.raises(psycopg.Error):
            reader.execute(f"DELETE FROM {name}")
    with pytest.raises(psycopg.Error):
        writer.execute("INSERT INTO pump_1m (bucket, device_id) VALUES (now(), 'x')")


def test_manual_refresh_of_a_range_older_than_the_policy_window(pg, migrated_db):
    """Historia k5 (84 dni) jest starsza niż okno odświeżania (7 dni): ręczne odświeżenie zakresu."""
    old = (datetime.now(timezone.utc) - timedelta(days=60)).replace(second=0, microsecond=0)
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        pump_minute(conn, old)
        refresh(conn, start=old - timedelta(hours=1), end=old + timedelta(hours=1))
        assert conn.execute("SELECT running FROM pump_1m_calc WHERE bucket = %s", (old,)).fetchone() == (True,)


def test_refresh_and_insert_into_compressed_chunks(pg, migrated_db):
    """K4-U2: (a) odświeżenie zakresu, w którym chunk pump_1m jest skompresowany; (b) wstawienie surowych wierszy pompy do
    skompresowanego chunku measurements. Wynik zapisany w raporcie k4 (od niego zależy kolejność kroków k5)."""
    old = (datetime.now(timezone.utc) - timedelta(days=40)).replace(second=0, microsecond=0)
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        pump_minute(conn, old)
        refresh(conn, start=old - timedelta(days=1), end=old + timedelta(days=1))
        conn.execute("SELECT compress_chunk(c, if_not_compressed => true) FROM show_chunks('measurements', older_than => %s) c",
                     (old + timedelta(days=1),))
        mat = conn.execute("SELECT materialization_hypertable_schema || '.' || materialization_hypertable_name "
                           "FROM timescaledb_information.continuous_aggregates WHERE view_name = 'pump_1m'").fetchone()[0]
        # chunki agregatu obejmują po 10 dób, więc granica „older_than” musi być za końcem chunku z danymi testu
        conn.execute(f"SELECT compress_chunk(c, if_not_compressed => true) FROM show_chunks('{mat}', older_than => %s) c",
                     (old + timedelta(days=15),))
        compressed = conn.execute("SELECT hypertable_name, count(*) FILTER (WHERE is_compressed) FROM timescaledb_information.chunks "
                                  "GROUP BY 1").fetchall()
        counts = dict(compressed)
        assert counts.get("measurements", 0) >= 1 and counts.get(mat.split(".")[1], 0) >= 1, compressed
        # (b) wstawienie do skompresowanego chunku measurements (minuta obok)
        pump_minute(conn, old + MIN, speed_expr="0", vib="0.1")
        # (a) odświeżenie zakresu ze skompresowanym chunkiem pump_1m
        refresh(conn, start=old - timedelta(days=1), end=old + timedelta(days=1))
        rows = conn.execute("SELECT bucket, running, vibration_n FROM pump_1m_calc WHERE bucket IN (%s, %s) ORDER BY bucket",
                            (old, old + MIN)).fetchall()
    assert rows == [(old, True, 60), (old + MIN, False, 60)]


def statements_of_012():
    text = (MIGRATIONS / "012_pump_aggregates.sql").read_text(encoding="utf-8")
    return [part for part in SPLIT.split(text) if part.strip()]


@pytest.fixture
def before_012(tmp_path):
    path = tmp_path / "early"
    path.mkdir()
    for file in sorted(MIGRATIONS.glob("*.sql")):
        if file.name < "012":
            shutil.copy(file, path / file.name)
    return path


@pytest.mark.parametrize("applied_before_interrupt", [1, 2, 3, 5, 7])
def test_migration_012_interrupted_midway_completes_on_the_next_run(pg, fresh_db, run_migrate, before_012, applied_before_interrupt):
    statements = statements_of_012()
    assert len(statements) == 8
    assert run_migrate(fresh_db, before_012).returncode == 0
    with admin_connect(pg, fresh_db) as conn:
        for statement in statements[:applied_before_interrupt]:
            conn.execute(statement)
    result = run_migrate(fresh_db)
    assert result.returncode == 0, result.stderr
    assert "applied 012_pump_aggregates.sql" in result.stderr
    with admin_connect(pg, fresh_db) as conn:
        assert set(jobs(conn)) == {"policy_refresh_continuous_aggregate", "policy_compression", "policy_retention"}
        assert conn.execute("SELECT has_table_privilege('app_reader', 'pump_1m_calc', 'SELECT')").fetchone()[0]
    again = run_migrate(fresh_db)
    assert again.returncode == 0 and "0 applied" in again.stderr


def test_simulator_pump_samples_give_model_means_and_running_flags(pg, migrated_db):
    """Dane z modelu pompy (samples_at) wstawione do measurements: średnie w pump_1m_calc równe średnim z modelu, minuta w zmianie
    = praca, minuta nocą = postój (zamiast e2e przez MQTT – ścieżkę MQTT -> ingest sprawdza test_sim_e2e)."""
    import copy
    import sys
    from pathlib import Path

    import yaml

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulator"))
    from sim_support import set_dates
    from simulator.config import load_config_dict
    from simulator.samples import Simulator
    from zoneinfo import ZoneInfo

    from dbtools import REPO

    raw = set_dates(copy.deepcopy(yaml.safe_load((REPO / "config" / "devices.yaml").read_text(encoding="utf-8"))))
    sim = Simulator(load_config_dict(raw))
    waw = ZoneInfo("Europe/Warsaw")
    work = int(datetime(2026, 11, 24, 9, 0, tzinfo=waw).timestamp())          # wtorek, praca
    night = int(datetime(2026, 11, 24, 23, 30, tzinfo=waw).timestamp())       # postój
    expected = {}
    with admin_connect(pg, migrated_db) as conn:
        seed_pump(conn)
        for start in (work, night):
            rows = [(t, d, m, v, u) for t in range(start, start + 60) for d, m, v, u in sim.samples_at(t, devices={PUMP})]
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO measurements (time, device_id, metric, value, unit, source) "
                                "VALUES (to_timestamp(%s), %s, %s, %s, %s, 'sim')", rows)
            vib = [v for _, _, m, v, _ in rows if m == "vibration_rms"]
            expected[start] = sum(vib) / len(vib)
        refresh(conn, start=datetime.fromtimestamp(work, timezone.utc) - timedelta(hours=1),
                end=datetime.fromtimestamp(night, timezone.utc) + timedelta(hours=1))
        got = {int(r[0].timestamp()): (r[1], r[2]) for r in conn.execute(
            "SELECT bucket, vibration_avg, running FROM pump_1m_calc ORDER BY bucket").fetchall()}
    assert got[work][0] == pytest.approx(expected[work]) and got[work][1] is True
    assert got[night][0] == pytest.approx(expected[night]) and got[night][1] is False
