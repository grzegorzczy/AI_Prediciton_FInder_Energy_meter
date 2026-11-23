"""Runner migracji (D4): idempotencja, sumy kontrolne, tryb bez transakcji."""
from __future__ import annotations

import shutil

import psycopg

from dbtools import MIGRATIONS, admin_connect


def migration_files():
    return sorted(p for p in MIGRATIONS.iterdir() if p.suffix == ".sql")


def test_applies_on_empty_database(pg, migrated_db):
    with admin_connect(pg, migrated_db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}
        versions = [r[0] for r in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    assert {"devices", "measurements", "schema_migrations"} <= tables
    assert len(versions) == len(migration_files())


def test_second_run_changes_nothing(pg, migrated_db, run_migrate):
    with admin_connect(pg, migrated_db) as conn:
        before = conn.execute("SELECT version, checksum, applied_at FROM schema_migrations ORDER BY 1").fetchall()
    result = run_migrate(migrated_db)
    assert result.returncode == 0, result.stderr
    with admin_connect(pg, migrated_db) as conn:
        after = conn.execute("SELECT version, checksum, applied_at FROM schema_migrations ORDER BY 1").fetchall()
    assert before == after
    assert "0 applied" in result.stderr


def test_modified_applied_migration_is_an_error(fresh_db, run_migrate, tmp_path):
    shutil.copytree(MIGRATIONS, tmp_path / "m")
    assert run_migrate(fresh_db, tmp_path / "m").returncode == 0
    first = sorted((tmp_path / "m").iterdir())[0]
    first.write_text(first.read_text(encoding="utf-8") + "\n-- zmiana po zastosowaniu\n", encoding="utf-8")
    result = run_migrate(fresh_db, tmp_path / "m")
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr


def test_bad_file_name_is_rejected(fresh_db, run_migrate, tmp_path):
    (tmp_path / "zla_nazwa.sql").write_text("SELECT 1;", encoding="utf-8")
    result = run_migrate(fresh_db, tmp_path)
    assert result.returncode == 1
    assert "bad migration file name" in result.stderr


def test_failed_migration_rolls_back_and_is_not_recorded(pg, fresh_db, run_migrate, tmp_path):
    (tmp_path / "001_bad.sql").write_text(
        "CREATE TABLE half_done (a int);\nSELECT 1/0;\n", encoding="utf-8")
    result = run_migrate(fresh_db, tmp_path)
    assert result.returncode == 1
    with admin_connect(pg, fresh_db) as conn:
        assert conn.execute("SELECT to_regclass('public.half_done')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0


def test_no_transaction_migration_with_statement_separator(pg, fresh_db, run_migrate, tmp_path):
    """CREATE INDEX CONCURRENTLY nie działa w transakcji: tryb potrzebny agregatom ciągłym (k6)."""
    (tmp_path / "001_concurrent.sql").write_text(
        "-- migrate: no-transaction\n"
        "CREATE TABLE t (a int);\n"
        "-- migrate: next\n"
        "CREATE INDEX CONCURRENTLY t_a_idx ON t (a);\n",
        encoding="utf-8",
    )
    result = run_migrate(fresh_db, tmp_path)
    assert result.returncode == 0, result.stderr
    with admin_connect(pg, fresh_db) as conn:
        assert conn.execute("SELECT to_regclass('public.t_a_idx')").fetchone()[0] is not None


def test_wrong_superuser_password_fails_fast_with_hint(pg, fresh_db, run_migrate, monkeypatch):
    monkeypatch.setitem(pg, "password", "zle-haslo")
    result = run_migrate(fresh_db)
    assert result.returncode == 1
    assert "POSTGRES_PASSWORD" in result.stderr
