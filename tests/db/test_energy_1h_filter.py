"""Migracja 009 (E2-PLC2, krok 4): energy_1h odtworzony z FILTER w first()/last(); zgodność przed i po, naprawa wiaderek granicznych."""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from dbtools import METER, MIGRATIONS, admin_connect, refresh_all, seed_devices, series
from test_energy_aggregates import fill_random

BASE = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=3)
MIN = timedelta(minutes=1)
EARLY = ["001_core.sql", "002_energy_aggregates.sql", "003_energy_views.sql", "004_data_windows.sql",
         "005_data_windows_plc_program_download.sql", "006_data_windows_plc1_download.sql", "007_energy_ext_aggregates.sql",
         "008_energy_ext_views.sql"]


@pytest.fixture
def early_dir(tmp_path):
    """Katalog z migracjami 001-008 (stan przed 009)."""
    path = tmp_path / "early"
    path.mkdir()
    for name in EARLY:
        shutil.copy(MIGRATIONS / name, path / name)
    return path


def hourly_rows(conn):
    cursor = conn.execute("SELECT * FROM energy_1h ORDER BY bucket, device_id")
    names = [d.name for d in cursor.description]
    return names, cursor.fetchall()


def viewdefs(conn):
    return {name: conn.execute("SELECT pg_get_viewdef(%s::regclass, true)", (name,)).fetchone()[0]
            for name in ("energy_1h_calc", "energy_daily_check", "energy_1m_calc")}


def test_hourly_rows_are_identical_before_and_after_for_data_without_null_edges(pg, fresh_db, run_migrate, early_dir):
    """Zgodność przed/po: dla danych bez wiaderek z NULL na brzegu godziny wszystkie kolumny energy_1h są bez zmian."""
    assert run_migrate(fresh_db, early_dir).returncode == 0
    with admin_connect(pg, fresh_db) as conn:
        seed_devices(conn)
        fill_random(conn)
        refresh_all(conn)
        before_names, before = hourly_rows(conn)
        defs_before = viewdefs(conn)
        daily_before = conn.execute("SELECT * FROM energy_daily_check ORDER BY day").fetchall()
        calc_before = conn.execute("SELECT * FROM energy_1h_calc ORDER BY bucket").fetchall()
    assert len(before) >= 3
    result = run_migrate(fresh_db)
    assert result.returncode == 0, result.stderr
    assert "applied 009_energy_1h_first_last_filter.sql" in result.stderr
    with admin_connect(pg, fresh_db) as conn:
        after_names, after = hourly_rows(conn)
        assert after_names == before_names
        assert after == before, "sumy i stany godzinowe muszą być identyczne przed i po odtworzeniu agregatu"
        assert viewdefs(conn) == defs_before                                       # widoki odtworzone identycznie
        assert conn.execute("SELECT * FROM energy_daily_check ORDER BY day").fetchall() == daily_before
        assert conn.execute("SELECT * FROM energy_1h_calc ORDER BY bucket").fetchall() == calc_before


def edge_data(conn):
    """Godzina, w której pierwsza i ostatnia minuta nie mają energii (cała minuta błędu licznika), a środek ma."""
    series(conn, "meter_status", BASE, 60, "1")                                                        # minuta 0: tylko status (błąd)
    series(conn, "energy_import_wh", BASE + MIN, 58 * 60, "1000 + floor(g / 3000.0) * 100", unit="Wh")   # minuty 1-58
    series(conn, "meter_status", BASE + 59 * MIN, 60, "1")                                             # minuta 59: tylko status
    series(conn, "energy_export_wh", BASE + MIN, 58 * 60, "50", unit="Wh")


def test_null_edge_hour_is_repaired(pg, fresh_db, run_migrate, early_dir):
    assert run_migrate(fresh_db, early_dir).returncode == 0
    with admin_connect(pg, fresh_db) as conn:
        seed_devices(conn)
        edge_data(conn)
        refresh_all(conn)
        row = conn.execute("SELECT import_first, import_last, export_first, export_last FROM energy_1h").fetchone()
        assert row == (None, None, None, None), "przed poprawką brzegowe minuty bez energii dają NULL (wada z migracji 002)"
        before_delta = conn.execute("SELECT energy_import_delta_wh FROM energy_1h_calc").fetchone()[0]
        assert before_delta is None
    assert run_migrate(fresh_db).returncode == 0
    with admin_connect(pg, fresh_db) as conn:
        row = conn.execute("SELECT import_first, import_last, export_first, export_last FROM energy_1h").fetchone()
        raw_first, raw_last = conn.execute(
            "SELECT (array_agg(value ORDER BY time))[1], (array_agg(value ORDER BY time DESC))[1] FROM measurements "
            "WHERE metric = 'energy_import_wh'").fetchone()
        assert row == (raw_first, raw_last, 50.0, 50.0)                            # pierwsza i ostatnia wartość z minut, które ją mają
        assert conn.execute("SELECT energy_import_delta_wh FROM energy_1h_calc").fetchone()[0] == raw_last - raw_first


def test_policies_permissions_and_idempotence_after_009(pg, fresh_db, run_migrate, reader, writer):
    for name in ("energy_1h", "energy_1h_calc", "energy_daily_check"):
        reader.execute(f"SELECT * FROM {name} LIMIT 1").fetchall()
    with pytest.raises(psycopg.Error):
        writer.execute("INSERT INTO energy_1h (bucket, device_id) VALUES (now(), 'x')")
    with admin_connect(pg, fresh_db) as conn:
        jobs = conn.execute(
            "SELECT j.proc_name FROM timescaledb_information.jobs j JOIN timescaledb_information.continuous_aggregates c "
            "ON j.hypertable_name IN (c.view_name, c.materialization_hypertable_name) WHERE c.view_name = 'energy_1h' ORDER BY 1").fetchall()
        assert [r[0] for r in jobs] == ["policy_compression", "policy_refresh_continuous_aggregate"]     # bez retencji, jak w 002
        flags = conn.execute("SELECT materialized_only, compression_enabled FROM timescaledb_information.continuous_aggregates "
                             "WHERE view_name = 'energy_1h'").fetchone()
        assert flags == (False, True)
        before = conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY 1").fetchall()
    result = run_migrate(fresh_db)
    assert result.returncode == 0 and "0 applied" in result.stderr
    with admin_connect(pg, fresh_db) as conn:
        assert conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY 1").fetchall() == before


def statements_of_009() -> list[str]:
    text = (MIGRATIONS / "009_energy_1h_first_last_filter.sql").read_text(encoding="utf-8")
    return [part for part in re.split(r"^-- migrate: next\s*$", text, flags=re.MULTILINE) if part.strip()]


@pytest.mark.parametrize("applied_before_interrupt", [1, 2, 3, 4, 7, 9, 11])
def test_migration_009_interrupted_midway_completes_on_the_next_run(pg, fresh_db, run_migrate, early_dir, applied_before_interrupt):
    """Jak K6-U3: przerwanie po k-tej instrukcji, ponowny migrate daje ten sam katalog, polityki i definicje widoków co czysta baza."""
    statements = statements_of_009()
    assert len(statements) >= 12 and len(statements) > applied_before_interrupt
    assert run_migrate(fresh_db, early_dir).returncode == 0
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
                    conn.execute("SELECT proc_name, schedule_interval FROM timescaledb_information.jobs WHERE proc_name LIKE 'policy_%' ORDER BY 1, 2").fetchall(),
                    viewdefs(conn))

        with admin_connect(pg, fresh_db) as interrupted, admin_connect(pg, clean) as fresh:
            assert fingerprint(interrupted) == fingerprint(fresh)
    finally:
        with admin_connect(pg) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(clean)))
