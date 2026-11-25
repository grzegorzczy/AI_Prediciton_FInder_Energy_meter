"""Agregaty energy_ext_1m i energy_ext_1h (007) oraz widok reactive_1h_calc (008): jakość, temperatura, czas pracy, energia bierna."""
from __future__ import annotations

import math
import random
import re
import shutil
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from dbtools import METER, MIGRATIONS, admin_connect, refresh_all, seed_devices, series

BASE = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=3)
MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)

V2 = ("thd_voltage", "thd_current", "phase_angle", "meter_temperature", "run_time", "reactive_pos_varh", "reactive_neg_varh")


def refresh_ext(conn) -> None:
    refresh_all(conn)          # energy_1m/_1h (te same polityki), potem agregaty ext (niżej)
    for view in ("energy_ext_1m", "energy_ext_1h"):
        for attempt in range(10):
            try:
                conn.execute(f"CALL refresh_continuous_aggregate('{view}', NULL, NULL)")
                break
            except psycopg.errors.LockNotAvailable:
                import time

                if attempt == 9:
                    raise
                time.sleep(1)


def fill_random(conn, seconds: int = 3 * 3600, seed: int = 11) -> None:
    """Dane z lukami; metryki v2 tylko w drugiej połowie (pierwsza to „sprzed v2”: tylko reactive_power i energia czynna)."""
    rng = random.Random(seed)
    pos, neg = 1000.0, 4500.0
    rows = []
    for i in range(seconds):
        if rng.random() < 0.08 or 500 < i % 900 < 560:
            continue
        t = BASE + timedelta(seconds=i)
        rows.append((t, "active_power", rng.uniform(0, 3000)))
        rows.append((t, "reactive_power", rng.uniform(-500, 500)))
        if i >= seconds // 2:
            if rng.random() < 0.01:
                pos += 100.0
            if rng.random() < 0.01:
                neg += 100.0
            if i == (3 * seconds) // 4:
                pos = 0.0                                               # reset licznika n2
            rows += [(t, "thd_voltage", rng.uniform(1, 5)), (t, "thd_current", rng.uniform(100, 160)),
                     (t, "phase_angle", rng.uniform(-80, -20)), (t, "meter_temperature", rng.uniform(25, 35)),
                     (t, "run_time", 1_000_000.0 + i), (t, "reactive_pos_varh", pos), (t, "reactive_neg_varh", neg)]
    with conn.cursor() as cur:
        with cur.copy("COPY measurements (time, device_id, metric, value, unit, source) FROM STDIN") as copy:
            for t, metric, value in rows:
                copy.write_row((t, METER, metric, value, "", "real"))


RAW_SQL = """
SELECT time_bucket(%(width)s::interval, time) AS bucket,
       count(value) FILTER (WHERE metric = 'thd_voltage') AS thd_voltage_n,
       sum(value) FILTER (WHERE metric = 'thd_voltage') AS thd_voltage_sum,
       min(value) FILTER (WHERE metric = 'thd_voltage') AS thd_voltage_min,
       max(value) FILTER (WHERE metric = 'thd_voltage') AS thd_voltage_max,
       count(value) FILTER (WHERE metric = 'thd_current') AS thd_current_n,
       sum(value) FILTER (WHERE metric = 'thd_current') AS thd_current_sum,
       min(value) FILTER (WHERE metric = 'thd_current') AS thd_current_min,
       max(value) FILTER (WHERE metric = 'thd_current') AS thd_current_max,
       count(value) FILTER (WHERE metric = 'phase_angle') AS phase_angle_n,
       sum(value) FILTER (WHERE metric = 'phase_angle') AS phase_angle_sum,
       min(value) FILTER (WHERE metric = 'phase_angle') AS phase_angle_min,
       max(value) FILTER (WHERE metric = 'phase_angle') AS phase_angle_max,
       sum(cos(radians(value))) FILTER (WHERE metric = 'phase_angle') AS phase_cos_sum,
       count(value) FILTER (WHERE metric = 'meter_temperature') AS temperature_n,
       sum(value) FILTER (WHERE metric = 'meter_temperature') AS temperature_sum,
       min(value) FILTER (WHERE metric = 'meter_temperature') AS temperature_min,
       max(value) FILTER (WHERE metric = 'meter_temperature') AS temperature_max,
       (array_agg(value ORDER BY time) FILTER (WHERE metric = 'run_time'))[1] AS run_time_first,
       (array_agg(value ORDER BY time DESC) FILTER (WHERE metric = 'run_time'))[1] AS run_time_last,
       min(value) FILTER (WHERE metric = 'run_time') AS run_time_min,
       max(value) FILTER (WHERE metric = 'run_time') AS run_time_max,
       (array_agg(value ORDER BY time) FILTER (WHERE metric = 'reactive_pos_varh'))[1] AS counter_pos_first,
       (array_agg(value ORDER BY time DESC) FILTER (WHERE metric = 'reactive_pos_varh'))[1] AS counter_pos_last,
       min(value) FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_min,
       max(value) FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_max,
       (array_agg(value ORDER BY time) FILTER (WHERE metric = 'reactive_neg_varh'))[1] AS counter_neg_first,
       (array_agg(value ORDER BY time DESC) FILTER (WHERE metric = 'reactive_neg_varh'))[1] AS counter_neg_last,
       min(value) FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_min,
       max(value) FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_max,
       count(value) FILTER (WHERE metric = 'reactive_power') AS reactive_power_n,
       sum(GREATEST(value, 0)) FILTER (WHERE metric = 'reactive_power') AS reactive_pos_sum,
       sum(LEAST(value, 0)) FILTER (WHERE metric = 'reactive_power') AS reactive_neg_sum
FROM measurements
WHERE device_id = %(device)s
  AND metric IN ('thd_voltage','thd_current','phase_angle','meter_temperature','run_time','reactive_pos_varh','reactive_neg_varh','reactive_power')
GROUP BY 1 ORDER BY 1
"""


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return a == pytest.approx(b, rel=1e-9, abs=1e-9)
    return a == b


def compare_with_raw(conn, view: str, width: str) -> int:
    cursor = conn.execute(RAW_SQL, {"width": width, "device": METER})
    names = [d.name for d in cursor.description]
    raw = cursor.fetchall()
    agg = conn.execute(f"SELECT {', '.join(names)} FROM {view} WHERE device_id = %s ORDER BY bucket", (METER,)).fetchall()
    assert len(agg) == len(raw), f"{view}: {len(agg)} wiaderek, z surowych danych {len(raw)}"
    for got, want in zip(agg, raw):
        for name, g, w in zip(names, got, want):
            assert same(g, w), f"{view} {got[0]} {name}: {g} != {w}"
    return len(raw)


@pytest.fixture
def data(admin):
    seed_devices(admin)
    fill_random(admin)
    refresh_ext(admin)
    return admin


def test_energy_ext_1m_equals_recomputation_from_raw_data(data):
    assert compare_with_raw(data, "energy_ext_1m", "1 minute") >= 170


def test_energy_ext_1h_equals_recomputation_from_raw_data(data):
    """Agregat godzinny złożony z minutowych równa się liczonemu wprost z surowych danych (hierarchia)."""
    assert compare_with_raw(data, "energy_ext_1h", "1 hour") >= 3


def test_buckets_before_v2_have_no_v2_values_instead_of_zeros(data):
    """Dane sprzed mapy v2: kolumny v2 to NULL, a liczności 0; całka mocy biernej istnieje (Q jest w bazie od v1)."""
    row = data.execute(
        "SELECT thd_voltage_n, thd_voltage_sum, thd_current_max, phase_angle_n, phase_cos_sum, temperature_n, temperature_min, "
        "run_time_last, counter_pos_last, counter_neg_last, reactive_power_n, reactive_pos_sum IS NOT NULL "
        "FROM energy_ext_1m WHERE device_id = %s ORDER BY bucket LIMIT 1", (METER,)).fetchone()
    assert row[0] == 0 and row[3] == 0 and row[5] == 0
    assert all(v is None for v in (row[1], row[2], row[4], row[6], row[7], row[8], row[9]))
    assert row[10] > 0 and row[11] is True


def test_phase_cos_sum_gives_the_exact_mean_cosine(admin):
    seed_devices(admin)
    series(admin, "phase_angle", BASE, 60, "-50.58", unit="°")
    series(admin, "phase_angle", BASE + MIN, 60, "CASE WHEN g < 30 THEN -30 ELSE -60 END", unit="°")
    refresh_ext(admin)
    first, second = admin.execute(
        "SELECT phase_cos_sum / phase_angle_n, phase_angle_sum / phase_angle_n FROM energy_ext_1m ORDER BY bucket").fetchall()
    assert first[0] == pytest.approx(math.cos(math.radians(-50.58)), abs=1e-12) and first[1] == pytest.approx(-50.58)
    assert second[0] == pytest.approx((math.cos(math.radians(30)) + math.cos(math.radians(60))) / 2, abs=1e-12)
    assert second[0] != pytest.approx(math.cos(math.radians(second[1])), abs=1e-3)       # średnia cos != cos średniej


def test_run_time_and_temperature_columns(admin):
    seed_devices(admin)
    series(admin, "run_time", BASE, 60, "1256171 + g", unit="s")
    series(admin, "meter_temperature", BASE, 60, "30 + mod(g, 3) * 0.1", unit="°C")
    refresh_ext(admin)
    row = admin.execute("SELECT run_time_first, run_time_last, run_time_min, run_time_max, temperature_n, temperature_min, temperature_max "
                        "FROM energy_ext_1h").fetchone()
    assert row[:4] == (1256171.0, 1256230.0, 1256171.0, 1256230.0)
    assert row[4] == 60 and row[5] == pytest.approx(30.0) and row[6] == pytest.approx(30.2)


# --- widok reactive_1h_calc --------------------------------------------------------------------------------------------------

def hourly(conn, columns="*"):
    refresh_ext(conn)
    cursor = conn.execute(f"SELECT {columns} FROM reactive_1h_calc WHERE device_id = %s ORDER BY bucket", (METER,))
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def seed_reactive_devices(conn, poll=1.0, resolution=100.0):
    import json

    conn.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
        "('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real', '{}'), (%s, 'Licznik', 'zaklad1', 'linia1', 'energy_meter', 'real', %s)",
        (METER, json.dumps({k: v for k, v in (("poll_interval_s", poll), ("reactive_resolution_varh", resolution)) if v is not None})))


def test_reactive_integral_splits_the_sign_of_q(admin):
    """Całka mocy biernej z podziałem na znak: 1800 s przy +10 var i 1800 s przy -20 var (niepełne pokrycie dopuszczone)."""
    seed_reactive_devices(admin)
    series(admin, "reactive_power", BASE, 1800, "10", unit="var")
    series(admin, "reactive_power", BASE + timedelta(seconds=1800), 1800, "-20", unit="var")
    row = hourly(admin)[0]
    assert row["reactive_pos_integral_varh"] == pytest.approx(10 * 1800 / 3600)
    assert row["reactive_neg_integral_varh"] == pytest.approx(20 * 1800 / 3600)         # moduł, porównywalny z licznikiem n4
    assert row["coverage"] == pytest.approx(1.0)


def test_only_negative_q_gives_zero_positive_integral_not_null(admin):
    seed_reactive_devices(admin)
    series(admin, "reactive_power", BASE, 3600, "-9", unit="var")
    row = hourly(admin)[0]
    assert row["reactive_pos_integral_varh"] == 0 and row["reactive_neg_integral_varh"] == pytest.approx(9.0)


def test_counter_delta_reset_gap_and_first_bucket(admin):
    seed_reactive_devices(admin)
    series(admin, "reactive_neg_varh", BASE, 3600, "4500", unit="varh")                                    # h0: pierwsze wiaderko
    series(admin, "reactive_neg_varh", BASE + HOUR, 3600, "4500 + CASE WHEN g >= 1800 THEN 100 ELSE 0 END", unit="varh")   # h1: +100
    series(admin, "reactive_power", BASE + 2 * HOUR, 3600, "-9", unit="var")                               # h2: bez odczytu licznika
    series(admin, "reactive_neg_varh", BASE + 3 * HOUR, 3600, "4600", unit="varh")                         # h3: bez zmiany
    series(admin, "reactive_neg_varh", BASE + 4 * HOUR, 3600, "200", unit="varh")                          # h4: reset
    series(admin, "reactive_neg_varh", BASE + 8 * HOUR, 3600, "300", unit="varh")                          # h8: po luce
    by = {r["bucket"]: r for r in hourly(admin)}
    h = lambda i: by[BASE + i * HOUR]                                                                       # noqa: E731
    assert h(0)["reactive_neg_delta_varh"] == 0 and not h(0)["gap_before"]
    assert h(1)["reactive_neg_delta_varh"] == 100 and not h(1)["neg_reset"]
    assert h(2)["reactive_neg_delta_varh"] is None                                                          # brak odczytu: NULL, nie zero
    assert h(3)["reactive_neg_delta_varh"] == 0 and h(3)["gap_before"] is True                              # nie zerowane przez h2
    assert h(4)["reactive_neg_delta_varh"] == 200 and h(4)["neg_reset"] is True
    assert h(8)["reactive_neg_delta_varh"] == 100 and h(8)["gap_before"] is True
    assert h(0)["reactive_pos_delta_varh"] is None                                                          # n2 bez danych


def test_pos_and_neg_counters_are_independent(admin):
    seed_reactive_devices(admin)
    series(admin, "reactive_pos_varh", BASE, 3600, "0", unit="varh")
    series(admin, "reactive_pos_varh", BASE + HOUR, 3600, "100", unit="varh")
    series(admin, "reactive_neg_varh", BASE, 3600, "4500", unit="varh")
    series(admin, "reactive_neg_varh", BASE + HOUR, 3600, "4500", unit="varh")
    rows = hourly(admin)
    assert [r["reactive_pos_delta_varh"] for r in rows] == [0, 100] and [r["reactive_neg_delta_varh"] for r in rows] == [0, 0]


def test_missing_meta_gives_null_not_a_default(admin):
    seed_reactive_devices(admin, poll=None, resolution=None)
    series(admin, "reactive_power", BASE, 600, "-9", unit="var")
    series(admin, "reactive_neg_varh", BASE, 600, "4500", unit="varh")
    row = hourly(admin)[0]
    assert row["reactive_neg_integral_varh"] is None and row["coverage"] is None and row["resolution_varh"] is None
    assert row["reactive_neg_delta_varh"] == 0                                # przyrost licznika nie zależy od meta


def test_bucket_complete_flag(admin):
    seed_reactive_devices(admin)
    now = datetime.now(timezone.utc)
    series(admin, "reactive_power", now - timedelta(seconds=5), 5, "-9", unit="var")
    series(admin, "reactive_power", BASE, 3600, "-9", unit="var")
    rows = hourly(admin)
    assert rows[0]["bucket_complete"] is True and rows[-1]["bucket_complete"] is False


# --- polityki, uprawnienia, migracje -----------------------------------------------------------------------------------------

def test_reader_reads_and_writer_cannot_change_the_new_objects(reader, writer):
    for name in ("energy_ext_1m", "energy_ext_1h", "reactive_1h_calc"):
        reader.execute(f"SELECT * FROM {name} LIMIT 1").fetchall()
    for name in ("energy_ext_1m", "energy_ext_1h"):
        with pytest.raises(psycopg.Error):
            writer.execute(f"INSERT INTO {name} (bucket, device_id) VALUES (now(), 'x')")
        with pytest.raises(psycopg.Error):
            reader.execute(f"DELETE FROM {name}")


def test_policies_of_the_new_aggregates(admin):
    def jobs_for(view):
        rows = admin.execute(
            "SELECT j.proc_name, j.config, j.schedule_interval FROM timescaledb_information.jobs j "
            "JOIN timescaledb_information.continuous_aggregates c ON j.hypertable_name IN (c.view_name, c.materialization_hypertable_name) "
            "WHERE c.view_name = %s", (view,)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def interval(text):
        return admin.execute("SELECT %s::interval", (text,)).fetchone()[0]

    m, h = jobs_for("energy_ext_1m"), jobs_for("energy_ext_1h")
    assert interval(m["policy_refresh_continuous_aggregate"][0]["start_offset"]) == interval("7 days")
    assert interval(h["policy_refresh_continuous_aggregate"][0]["start_offset"]) == interval("30 days")
    assert interval(m["policy_compression"][0]["compress_after"]) == interval("14 days")
    assert interval(h["policy_compression"][0]["compress_after"]) == interval("60 days")
    assert interval(m["policy_retention"][0]["drop_after"]) == interval("1 year") and "policy_retention" not in h
    flags = admin.execute("SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates "
                          "WHERE view_name LIKE 'energy_ext%' ORDER BY 1").fetchall()
    assert flags == [("energy_ext_1h", False), ("energy_ext_1m", False)]


def statements_of_007() -> list[str]:
    text = (MIGRATIONS / "007_energy_ext_aggregates.sql").read_text(encoding="utf-8")
    return [part for part in re.split(r"^-- migrate: next\s*$", text, flags=re.MULTILINE) if part.strip()]


@pytest.mark.parametrize("applied_before_interrupt", [1, 2, 5, 9, 13])
def test_migration_007_interrupted_midway_completes_on_the_next_run(pg, fresh_db, run_migrate, tmp_path, applied_before_interrupt):
    """Jak K6-U3: przerwanie po k-tej instrukcji, ponowny migrate kończy się sukcesem i daje ten sam katalog co czysta baza."""
    statements = statements_of_007()
    assert len(statements) > applied_before_interrupt
    early = tmp_path / "early"
    early.mkdir()
    for name in ("001_core.sql", "002_energy_aggregates.sql", "003_energy_views.sql", "004_data_windows.sql",
                 "005_data_windows_plc_program_download.sql", "006_data_windows_plc1_download.sql"):
        shutil.copy(MIGRATIONS / name, early / name)
    assert run_migrate(fresh_db, early).returncode == 0
    with admin_connect(pg, fresh_db) as conn:
        for statement in statements[:applied_before_interrupt]:
            conn.execute(statement)
    result = run_migrate(fresh_db)
    assert result.returncode == 0, result.stderr

    from psycopg import sql

    clean = fresh_db + "_clean"
    with admin_connect(pg) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(clean)))
    try:
        assert run_migrate(clean).returncode == 0

        def fingerprint(conn):
            return (conn.execute("SELECT view_name, materialized_only, compression_enabled FROM timescaledb_information.continuous_aggregates ORDER BY 1").fetchall(),
                    conn.execute("SELECT proc_name, schedule_interval FROM timescaledb_information.jobs WHERE proc_name LIKE 'policy_%' ORDER BY 1, 2").fetchall())

        with admin_connect(pg, fresh_db) as interrupted, admin_connect(pg, clean) as fresh:
            assert fingerprint(interrupted) == fingerprint(fresh)
    finally:
        with admin_connect(pg) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(clean)))
