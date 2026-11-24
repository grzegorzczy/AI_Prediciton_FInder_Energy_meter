"""Polityki agregatów energii, uprawnienia ról i odporność migracji 002 na przerwanie (K6-U3)."""
from __future__ import annotations

import re
import shutil
from datetime import timedelta

import psycopg
import pytest

from dbtools import MIGRATIONS, admin_connect

AGGREGATES = ("energy_1m", "energy_1h")
VIEWS = ("energy_1m_calc", "energy_1h_calc", "energy_daily_check")
SPLIT = re.compile(r"^-- migrate: next\s*$", flags=re.MULTILINE)


def jobs_for(conn, view: str) -> dict[str, dict]:
    """Zadania agregatu: odświeżanie, kompresja, retencja (kompresja i retencja wiszą na tabeli materializacji)."""
    rows = conn.execute(
        "SELECT j.proc_name, j.config, j.schedule_interval, j.scheduled "
        "FROM timescaledb_information.jobs j "
        "JOIN timescaledb_information.continuous_aggregates c "
        "  ON j.hypertable_name IN (c.view_name, c.materialization_hypertable_name) "
        "WHERE c.view_name = %s", (view,)).fetchall()
    return {r[0]: {"config": r[1], "interval": r[2], "scheduled": r[3]} for r in rows}


def as_interval(conn, text: str) -> timedelta | object:
    return conn.execute("SELECT %s::interval", (text,)).fetchone()[0]


def test_refresh_policies(admin):
    expected = {"energy_1m": ("7 days", "1 minute", "1 minute"), "energy_1h": ("30 days", "1 hour", "15 minutes")}
    for view, (start, end, every) in expected.items():
        job = jobs_for(admin, view)["policy_refresh_continuous_aggregate"]
        assert as_interval(admin, job["config"]["start_offset"]) == as_interval(admin, start)
        assert as_interval(admin, job["config"]["end_offset"]) == as_interval(admin, end)
        assert job["interval"] == as_interval(admin, every) and job["scheduled"] is True


def test_compression_and_retention_policies(admin):
    m, h = jobs_for(admin, "energy_1m"), jobs_for(admin, "energy_1h")
    assert as_interval(admin, m["policy_compression"]["config"]["compress_after"]) == as_interval(admin, "14 days")
    assert as_interval(admin, h["policy_compression"]["config"]["compress_after"]) == as_interval(admin, "60 days")
    assert as_interval(admin, m["policy_retention"]["config"]["drop_after"]) == as_interval(admin, "1 year")
    assert "policy_retention" not in h, "godzinowe agregaty bez limitu retencji"


def test_refresh_windows_are_shorter_than_raw_retention_and_compression_follows_them(admin):
    raw_retention = as_interval(admin, "90 days")
    for view in AGGREGATES:
        jobs = jobs_for(admin, view)
        window = as_interval(admin, jobs["policy_refresh_continuous_aggregate"]["config"]["start_offset"])
        compress_after = as_interval(admin, jobs["policy_compression"]["config"]["compress_after"])
        assert window < raw_retention
        assert compress_after > window


def test_compression_settings_of_the_aggregates(admin):
    rows = admin.execute(
        "SELECT view_name, compression_enabled FROM timescaledb_information.continuous_aggregates ORDER BY 1").fetchall()
    assert rows == [("energy_1h", True), ("energy_1m", True)]


def test_reader_reads_every_aggregate_and_view(reader):
    for name in AGGREGATES + VIEWS:
        reader.execute(f"SELECT * FROM {name} LIMIT 1").fetchall()


def test_writer_cannot_change_aggregates_or_views(writer):
    for name in AGGREGATES:
        with pytest.raises(psycopg.Error):
            writer.execute(f"INSERT INTO {name} (bucket, device_id) VALUES (now(), 'x')")
    for name in AGGREGATES:
        with pytest.raises(psycopg.errors.Error):
            writer.execute(f"ALTER MATERIALIZED VIEW {name} SET (timescaledb.materialized_only = true)")
    with pytest.raises(psycopg.errors.Error):
        writer.execute("CALL refresh_continuous_aggregate('energy_1m', NULL, NULL)")


def test_reader_cannot_write(reader):
    for name in AGGREGATES:
        with pytest.raises(psycopg.errors.Error):
            reader.execute(f"DELETE FROM {name}")


def test_second_migrate_run_changes_nothing_in_the_catalog(pg, migrated_db, run_migrate):
    def catalog(conn):
        return (
            conn.execute("SELECT view_name, materialized_only, compression_enabled "
                         "FROM timescaledb_information.continuous_aggregates ORDER BY 1").fetchall(),
            conn.execute("SELECT proc_name, schedule_interval, hypertable_name FROM timescaledb_information.jobs "
                         "WHERE proc_name LIKE 'policy_%' ORDER BY 1, 3").fetchall(),
            conn.execute("SELECT version, checksum FROM schema_migrations ORDER BY 1").fetchall(),
        )

    with admin_connect(pg, migrated_db) as conn:
        before = catalog(conn)
    result = run_migrate(migrated_db)
    assert result.returncode == 0, result.stderr
    with admin_connect(pg, migrated_db) as conn:
        assert catalog(conn) == before


def statements_of_002() -> list[str]:
    text = (MIGRATIONS / "002_energy_aggregates.sql").read_text(encoding="utf-8")
    return [part for part in SPLIT.split(text) if part.strip()]


def catalog_fingerprint(conn):
    return (
        conn.execute("SELECT view_name, materialized_only, compression_enabled "
                     "FROM timescaledb_information.continuous_aggregates ORDER BY 1").fetchall(),
        conn.execute("SELECT proc_name, schedule_interval FROM timescaledb_information.jobs "
                     "WHERE proc_name LIKE 'policy_%' ORDER BY 1, 2").fetchall(),
    )


@pytest.mark.parametrize("applied_before_interrupt", [1, 2, 4, 7, 11])
def test_migration_002_interrupted_midway_completes_on_the_next_run(
        pg, fresh_db, run_migrate, tmp_path, applied_before_interrupt):
    """K6-U3: przerwanie po k-tej instrukcji (runner nie zdążył zapisać sumy kontrolnej) i ponowny migrate."""
    statements = statements_of_002()
    assert len(statements) > applied_before_interrupt
    only_001 = tmp_path / "only001"
    only_001.mkdir()
    shutil.copy(MIGRATIONS / "001_core.sql", only_001 / "001_core.sql")
    assert run_migrate(fresh_db, only_001).returncode == 0

    with admin_connect(pg, fresh_db) as conn:
        for statement in statements[:applied_before_interrupt]:
            conn.execute(statement)

    result = run_migrate(fresh_db)                                       # pełny zestaw: 002 od początku, potem 003
    assert result.returncode == 0, result.stderr

    clean_name = fresh_db + "_clean"
    from psycopg import sql
    with admin_connect(pg) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(clean_name)))
    try:
        assert run_migrate(clean_name).returncode == 0
        with admin_connect(pg, fresh_db) as interrupted, admin_connect(pg, clean_name) as clean:
            assert catalog_fingerprint(interrupted) == catalog_fingerprint(clean)
            assert interrupted.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == len(
                list(MIGRATIONS.glob("*.sql")))
    finally:
        with admin_connect(pg) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(clean_name)))


def test_no_transaction_runner_creates_continuous_aggregates(admin):
    names = {r[0] for r in admin.execute(
        "SELECT view_name FROM timescaledb_information.continuous_aggregates").fetchall()}
    assert names == set(AGGREGATES)
    assert (MIGRATIONS / "002_energy_aggregates.sql").read_text(encoding="utf-8").startswith("-- migrate: no-transaction")
