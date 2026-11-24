"""Wspólne fixtury: baza testowa (świeża dla każdego testu), uruchamianie migrate.py, hasła ról."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import uuid

import pytest
from psycopg import sql

from dbtools import MIGRATE, MIGRATIONS, admin_connect, role_connect


@pytest.fixture(scope="session")
def pg() -> dict:
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": "postgres",
        "password": os.environ["POSTGRES_PASSWORD"],
    }


@pytest.fixture(scope="session")
def role_passwords() -> dict:
    # Hasło app_reader jest wspólne dla całego klastra testowego: korzysta z niego też Grafana (provisioning z env),
    # więc każdy przebieg migrate musi ustawiać to samo hasło (run-tests.sh ustawia TEST_APP_READER_PASSWORD).
    return {"app_writer": secrets.token_hex(16),
            "app_reader": os.environ.get("TEST_APP_READER_PASSWORD") or secrets.token_hex(16)}


@pytest.fixture
def fresh_db(pg):
    """Pusta baza na czas jednego testu (rozszerzenie timescaledb jest w template1 obrazu)."""
    name = "t_" + uuid.uuid4().hex[:12]
    with admin_connect(pg) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield name
    with admin_connect(pg) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def run_migrate(pg, role_passwords):
    def _run(dbname, migrations_dir=None, writer_password=None, reader_password=None):
        env = {
            **os.environ,
            "DB_HOST": pg["host"],
            "DB_PORT": str(pg["port"]),
            "POSTGRES_DB": dbname,
            "POSTGRES_USER": pg["user"],
            "POSTGRES_PASSWORD": pg["password"],
            "APP_WRITER_PASSWORD": writer_password or role_passwords["app_writer"],
            "APP_READER_PASSWORD": reader_password or role_passwords["app_reader"],
            "MIGRATIONS_DIR": str(migrations_dir or MIGRATIONS),
            "DB_WAIT_S": "5",
        }
        return subprocess.run(
            [sys.executable, str(MIGRATE)], env=env, capture_output=True, text=True, timeout=120
        )

    return _run


@pytest.fixture
def migrated_db(fresh_db, run_migrate):
    result = run_migrate(fresh_db)
    assert result.returncode == 0, result.stderr
    return fresh_db


@pytest.fixture
def admin(pg, migrated_db):
    with admin_connect(pg, migrated_db) as conn:
        yield conn


@pytest.fixture
def writer(pg, migrated_db, role_passwords):
    with role_connect(pg, migrated_db, "app_writer", role_passwords["app_writer"]) as conn:
        yield conn


@pytest.fixture
def reader(pg, migrated_db, role_passwords):
    with role_connect(pg, migrated_db, "app_reader", role_passwords["app_reader"]) as conn:
        yield conn
