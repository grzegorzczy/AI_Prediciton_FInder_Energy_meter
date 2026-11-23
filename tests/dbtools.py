"""Wspólne helpery testów bazy. Osobny moduł (a nie import z conftest): w repo jest kilka plików conftest.py,
a import po nazwie `conftest` mógłby trafić na niewłaściwy."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg

REPO = Path(os.environ.get("REPO_DIR", Path(__file__).resolve().parents[1]))
MIGRATE = REPO / "db" / "migrate.py"
MIGRATIONS = REPO / "db" / "migrations"


def admin_connect(pg: dict, dbname: str = "postgres") -> psycopg.Connection:
    return psycopg.connect(dbname=dbname, autocommit=True, connect_timeout=5, **pg)


def role_connect(pg: dict, dbname: str, role: str, password: str) -> psycopg.Connection:
    return psycopg.connect(
        host=pg["host"], port=pg["port"], dbname=dbname, user=role, password=password,
        autocommit=True, connect_timeout=5,
    )
