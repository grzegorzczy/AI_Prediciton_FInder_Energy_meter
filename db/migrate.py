#!/usr/bin/env python3
"""Idempotent database bootstrap: roles, migrations, grants.

Runs at every `docker compose up` as the one-shot `migrate` container (decision D4, note U5).
Order, all under one advisory lock:

1. roles: create/refresh app_writer and app_reader (passwords from the environment),
   per-database privileges, default privileges for later objects;
2. migrations: db/migrations/NNN_name.sql, each recorded in schema_migrations with a checksum;
   an already applied file whose content changed is an error (history is not rewritten);
3. grants: re-apply SELECT for app_reader on everything that exists now.

Migration files run in one transaction. A file containing the line
``-- migrate: no-transaction`` runs outside a transaction and must be split into statements by
lines equal to ``-- migrate: next`` (needed e.g. for continuous aggregates in step k6).

Exit code 0 on success, 1 on any error. Secrets are never logged.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql

LOG = logging.getLogger("migrate")

LOCK_KEY = 4_270_001
NO_TX_MARKER = "-- migrate: no-transaction"
SPLIT_MARKER = "-- migrate: next"
NAME_RE = re.compile(r"^(\d{3,})_[a-z0-9_]+\.sql$")

ROLES = ("app_writer", "app_reader")


class MigrationError(Exception):
    pass


def getenv(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise MigrationError(f"missing required environment variable {name}")
    return value


def connect() -> psycopg.Connection:
    params = dict(
        host=getenv("DB_HOST"),
        port=int(getenv("DB_PORT", "5432")),
        dbname=getenv("POSTGRES_DB"),
        user=getenv("POSTGRES_USER"),
        password=getenv("POSTGRES_PASSWORD"),
        autocommit=True,
        connect_timeout=5,
    )
    deadline = time.monotonic() + float(getenv("DB_WAIT_S", "60"))
    delay = 1.0
    while True:
        try:
            return psycopg.connect(**params)
        except psycopg.OperationalError as exc:
            reason = str(exc).strip().splitlines()[-1] if str(exc).strip() else "unknown error"
            if "password authentication failed" in reason:
                raise MigrationError(
                    "superuser login failed: POSTGRES_PASSWORD in .env does not match the existing "
                    "database volume (the password is only applied when the volume is created; see "
                    "docs/ops/jumo-ipc-setup.md, section .env)"
                ) from None
            if time.monotonic() + delay > deadline:
                raise MigrationError(f"cannot connect to database: {reason}") from None
            LOG.warning("database not ready (%s); retry in %.0fs", reason, delay)
            time.sleep(delay)
            delay = min(delay * 2, 10.0)


def sync_roles(conn: psycopg.Connection, dbname: str, passwords: dict[str, str]) -> None:
    # A failed statement must not be echoed to the server log: it would contain a password.
    conn.execute("SET log_min_error_statement = 'panic'")
    owner = sql.Identifier(getenv("POSTGRES_USER"))
    db = sql.Identifier(dbname)

    for role in ROLES:
        conn.execute(
            sql.SQL(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {name}) "
                "THEN CREATE ROLE {ident} LOGIN; END IF; END $$"
            ).format(name=sql.Literal(role), ident=sql.Identifier(role))
        )
        conn.execute(
            sql.SQL(
                "ALTER ROLE {ident} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                "CONNECTION LIMIT 10 PASSWORD {pw}"
            ).format(ident=sql.Identifier(role), pw=sql.Literal(passwords[role]))
        )

    # app_reader (Grafana, chat): read only, bounded queries (decision K2-e).
    reader = sql.Identifier("app_reader")
    conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '10s'").format(reader))
    conn.execute(sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '30s'").format(reader))
    conn.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(reader))

    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(db))
    conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO app_writer, app_reader").format(db))
    conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    conn.execute("GRANT USAGE ON SCHEMA public TO app_writer, app_reader")
    conn.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA public GRANT SELECT ON TABLES TO app_reader"
        ).format(owner=owner)
    )
    LOG.info("roles synchronized: %s", ", ".join(ROLES))


def list_migrations(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".sql")
    seen: set[int] = set()
    for path in files:
        match = NAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"bad migration file name: {path.name} (expected NNN_name.sql)")
        version = int(match.group(1))
        if version in seen:
            raise MigrationError(f"duplicate migration number {version:03d}")
        seen.add(version)
    return files


def apply_migrations(conn: psycopg.Connection, directory: Path) -> tuple[int, int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied = skipped = 0
    for path in list_migrations(directory):
        version = int(NAME_RE.match(path.name).group(1))
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        row = conn.execute("SELECT checksum FROM schema_migrations WHERE version = %s", (version,)).fetchone()
        if row:
            if row[0] != checksum:
                raise MigrationError(
                    f"checksum mismatch for already applied migration {path.name}: "
                    "the file was modified after it was applied; add a new migration instead"
                )
            skipped += 1
            continue

        text = raw.decode("utf-8")
        record = ("INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                  (version, path.name, checksum))
        if NO_TX_MARKER in text:
            for statement in re.split(rf"^{re.escape(SPLIT_MARKER)}\s*$", text, flags=re.MULTILINE):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(*record)
        else:
            with conn.transaction():
                conn.execute(text)
                conn.execute(*record)
        LOG.info("applied %s", path.name)
        applied += 1
    return applied, skipped


def final_grants(conn: psycopg.Connection) -> None:
    conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_reader")


def run() -> int:
    dbname = getenv("POSTGRES_DB")
    passwords = {"app_writer": getenv("APP_WRITER_PASSWORD"), "app_reader": getenv("APP_READER_PASSWORD")}
    directory = Path(getenv("MIGRATIONS_DIR", "/migrations"))

    conn = connect()
    try:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        sync_roles(conn, dbname, passwords)
        applied, skipped = apply_migrations(conn, directory)
        final_grants(conn)
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    finally:
        conn.close()
    LOG.info("done: %d applied, %d already applied", applied, skipped)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run()
    except MigrationError as exc:
        LOG.error("%s", exc)
    except psycopg.Error as exc:
        # Never log the failing statement text: it may contain a password.
        LOG.error("database error: %s", str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
