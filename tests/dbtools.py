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


# --- rok danych syntetycznych do pomiarów wydajności (K6-U4, k7) -------------------------------------------------------

PERF_METRICS = {
    # metryka: (wyrażenie SQL zależne od g = numer minuty od początku, jednostka)
    "active_power": ("100 + 60 * sin(g / 1440.0 * 6.2831853) + 10 * random()", "W"),
    "reactive_power": ("20 + 10 * sin(g / 1440.0 * 6.2831853) + 3 * random()", "var"),
    "apparent_power": ("105 + 60 * sin(g / 1440.0 * 6.2831853) + 10 * random()", "VA"),
    "voltage": ("230 + 6 * sin(g / 700.0) + 2 * random()", "V"),
    "current": ("0.45 + 0.25 * sin(g / 1440.0 * 6.2831853) + 0.05 * random()", "A"),
    "power_factor": ("0.9 + 0.05 * random()", ""),
    "frequency": ("50 + 0.1 * (random() - 0.5)", "Hz"),
    "energy_import_wh": ("CASE WHEN g < 300000 THEN 1000000 + floor(g * 1.6667 / 100) * 100 "
                         "ELSE floor((g - 300000) * 1.6667 / 100) * 100 END", "Wh"),     # jeden reset licznika
    "meter_status": ("CASE WHEN random() < 0.003 THEN 1 ELSE 0 END", ""),
}


def build_year(conn, days: int = 365, device: str = METER) -> dict:
    """Jeden wiersz na minutę na metrykę przez `days` dób (do `now()`), ok. 2% losowych luk i jedna długa luka.
    Zwraca opis zbioru (liczba wierszy). Okres próbkowania w meta = 60 s, więc `coverage` jest sensowne."""
    minutes = days * 1440
    conn.execute("UPDATE devices SET meta = meta || '{\"poll_interval_s\": 60}'::jsonb WHERE device_id = %s", (device,))
    start = conn.execute("SELECT date_trunc('minute', now()) - make_interval(mins => %s)", (minutes,)).fetchone()[0]
    for metric, (expr, unit) in PERF_METRICS.items():
        conn.execute(
            "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
            f"SELECT %s::timestamptz + g * INTERVAL '1 minute', %s, %s, ({expr})::float8, %s, 'real' "
            "FROM generate_series(0, %s - 1) AS g "
            "WHERE random() > 0.02 AND NOT (g BETWEEN 200000 AND 204000)",
            (start, device, metric, unit, minutes),
        )
    rows = conn.execute("SELECT count(*) FROM measurements").fetchone()[0]
    return {"minutes": minutes, "rows": rows, "start": start}
