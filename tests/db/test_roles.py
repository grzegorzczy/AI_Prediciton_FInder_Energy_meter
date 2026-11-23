"""Role (U5): app_reader tylko do odczytu z limitem czasu, app_writer bez DDL, hasła odświeżane przez migrate."""
from __future__ import annotations

import time

import psycopg
import pytest

from conftest import admin_connect, role_connect


def test_reader_can_select_but_not_write(reader, writer):
    writer.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source) "
        "VALUES ('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real')")
    assert reader.execute("SELECT count(*) FROM devices").fetchone()[0] == 1
    assert reader.execute("SELECT count(*) FROM measurements").fetchone()[0] == 0
    # Pierwsza bariera: domyślna transakcja tylko do odczytu.
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        reader.execute("INSERT INTO devices (device_id, name, site, line, kind, source) "
                       "VALUES ('x', 'x', 'x', 'x', 'plc', 'real')")


def test_reader_privileges_are_the_real_boundary(reader):
    """Rola może sama przestawić default_transaction_read_only (to tylko zabezpieczenie domyślne).
    Granicą są uprawnienia: nawet po wyłączeniu read-only zapis i DDL są odrzucane."""
    reader.execute("SET default_transaction_read_only = off")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("INSERT INTO devices (device_id, name, site, line, kind, source) "
                       "VALUES ('x', 'x', 'x', 'x', 'plc', 'real')")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("UPDATE devices SET name = 'x'")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("DELETE FROM devices")


def test_reader_cannot_create_objects(reader):
    reader.execute("SET default_transaction_read_only = off")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("CREATE TABLE zly (a int)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("CREATE SCHEMA zly")


def test_reader_session_settings(reader):
    assert reader.execute("SHOW statement_timeout").fetchone()[0] == "10s"
    assert reader.execute("SHOW idle_in_transaction_session_timeout").fetchone()[0] == "30s"
    assert reader.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"


@pytest.mark.slow
def test_reader_query_over_limit_is_cancelled(reader):
    started = time.monotonic()
    with pytest.raises(psycopg.errors.QueryCanceled):
        reader.execute("SELECT pg_sleep(15)")
    assert time.monotonic() - started < 13


def test_reader_sees_tables_created_by_later_migrations(pg, migrated_db, reader):
    """ALTER DEFAULT PRIVILEGES: bez ponownego uruchamiania migrate."""
    with admin_connect(pg, migrated_db) as admin_conn:
        admin_conn.execute("CREATE TABLE later_table (a int)")
        admin_conn.execute("INSERT INTO later_table VALUES (1)")
    assert reader.execute("SELECT a FROM later_table").fetchone()[0] == 1


def test_writer_can_insert_but_not_change_schema(writer):
    writer.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source) "
        "VALUES ('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real')")
    writer.execute("UPDATE devices SET name = 'PLC 1' WHERE device_id = 'plc-01'")
    for statement in (
        "DROP TABLE devices",
        "ALTER TABLE devices ADD COLUMN x int",
        "CREATE TABLE zly (a int)",
        "DELETE FROM devices",
        "TRUNCATE measurements",
    ):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            writer.execute(statement)


def test_roles_have_no_dangerous_attributes(admin):
    rows = admin.execute(
        "SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolconnlimit FROM pg_roles "
        "WHERE rolname IN ('app_writer', 'app_reader')").fetchall()
    assert {r[0] for r in rows} == {"app_writer", "app_reader"}
    for _, superuser, createdb, createrole, limit in rows:
        assert not superuser and not createdb and not createrole
        assert limit == 10


def test_password_change_is_applied_by_migrate(pg, migrated_db, run_migrate, role_passwords):
    new_password = "nowe-haslo-testowe-" + role_passwords["app_reader"][:8]
    result = run_migrate(migrated_db, reader_password=new_password)
    assert result.returncode == 0, result.stderr
    with role_connect(pg, migrated_db, "app_reader", new_password) as conn:
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(psycopg.OperationalError):
        role_connect(pg, migrated_db, "app_reader", role_passwords["app_reader"])
    # przywracamy hasło sesyjne dla pozostałych testów
    assert run_migrate(migrated_db).returncode == 0


def test_public_has_no_connect_privilege(admin, migrated_db):
    row = admin.execute(
        "SELECT has_database_privilege('public', %s, 'CONNECT')", (migrated_db,)).fetchone()
    assert row[0] is False
