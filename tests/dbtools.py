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


# --- helpery agregatów energii (k6) ---------------------------------------------------------------------------------

METER = "finder_7m24_1"


def seed_devices(conn, poll_interval_s: float | None = 1.0, resolution_wh: float | None = 100.0) -> None:
    """plc-01 i licznik; meta licznika jak po synchronizacji ingestu (brak wartości = brak klucza)."""
    meta = {}
    if poll_interval_s is not None:
        meta["poll_interval_s"] = poll_interval_s
    if resolution_wh is not None:
        meta["energy_resolution_wh"] = resolution_wh
    import json

    conn.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
        "('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real', '{}'), "
        "(%s, 'Licznik', 'zaklad1', 'linia1', 'energy_meter', 'real', %s)",
        (METER, json.dumps(meta)),
    )


def series(conn, metric: str, start, seconds: int, value_sql: str = "0", device: str = METER, unit: str = "") -> None:
    """Jeden wiersz na sekundę przez `seconds` sekund od `start`; `value_sql` może używać `g` (numer sekundy od 0)."""
    conn.execute(
        "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
        f"SELECT %s::timestamptz + g * INTERVAL '1 second', %s, %s, ({value_sql})::float8, %s, 'real' "
        "FROM generate_series(0, %s - 1) AS g",
        (start, device, metric, unit, seconds),
    )


def refresh_all(conn) -> None:
    """Pełne odświeżenie obu agregatów (poza transakcją: conn musi mieć autocommit)."""
    conn.execute("CALL refresh_continuous_aggregate('energy_1m', NULL, NULL)")
    conn.execute("CALL refresh_continuous_aggregate('energy_1h', NULL, NULL)")
