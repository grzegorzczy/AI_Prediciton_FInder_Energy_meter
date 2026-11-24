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


# --- dane do testów paneli Grafany (k7) ---------------------------------------------------------------------------------

def _gen(conn, device, metric, unit, start_sql, end_sql, step_s, value_sql, where_sql="TRUE"):
    """Wiersze co `step_s` od start do end (wyrażenia SQL); `value_sql` i `where_sql` mogą używać `e` (epoch sekund)."""
    conn.execute(
        "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
        f"SELECT t, %s, %s, ({value_sql})::float8, %s, 'real' FROM "
        f"(SELECT t, extract(epoch FROM t) AS e FROM generate_series({start_sql}, {end_sql}, make_interval(secs => %s)) AS t) s "
        f"WHERE {where_sql}",
        (device, metric, unit, step_s),
    )


def build_panel_data(conn) -> dict:
    """Dane dla testów paneli: plc-01 i dwa liczniki. Licznik 1: 30 dni co minutę + ostatnie 6 h co sekundę (z epizodami
    błędu co 64 s: 4 s bez pomiarów, status 1 i kod 162, jak w k5), luka 10 min i 2 minuty `link_status` = 1.
    Licznik 2: ostatnie 2 doby co minutę, moc stała 500 W (odróżnia go od licznika 1)."""
    import json

    meta = json.dumps({"poll_interval_s": 1.0, "energy_resolution_wh": 100.0})
    conn.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
        "('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real', '{}'), "
        "('finder_7m24_1', 'Licznik 1', 'zaklad1', 'linia1', 'energy_meter', 'real', %s), "
        "('finder_7m24_2', 'Licznik 2', 'zaklad1', 'linia1', 'energy_meter', 'real', %s)", (meta, meta))
    now = conn.execute("SELECT date_trunc('second', now())").fetchone()[0]
    dense_start = now.timestamp() - 6 * 3600
    old = "(%s)::timestamptz" % "now() - interval '30 days'"
    dense = "(now() - interval '6 hours')"
    metrics = {
        "active_power": ("100 + 50 * sin(e / 3600.0)", "W"), "reactive_power": ("20 + 5 * sin(e / 1800.0)", "var"),
        "apparent_power": ("105 + 50 * sin(e / 3600.0)", "VA"), "voltage": ("230 + 4 * sin(e / 5400.0)", "V"),
        "current": ("0.45 + 0.2 * sin(e / 3600.0)", "A"), "power_factor": ("0.95", ""), "frequency": ("50 + 0.05 * sin(e / 600.0)", "Hz"),
        "energy_import_wh": ("1000000 + floor(e / 36.0 / 100) * 100", "Wh"), "energy_export_wh": ("5000", "Wh"),
    }
    for metric, (expr, unit) in metrics.items():
        _gen(conn, "finder_7m24_1", metric, unit, old, dense + " - interval '1 second'", 60, expr)
        _gen(conn, "finder_7m24_1", metric, unit, dense, "date_trunc('second', now())", 1, expr,
             "mod(floor(e)::bigint, 64) >= 4 AND NOT (e BETWEEN extract(epoch FROM now() - interval '3 hours') "
             "AND extract(epoch FROM now() - interval '3 hours') + 600)")
    _gen(conn, "finder_7m24_1", "meter_status", "", old, dense + " - interval '1 second'", 60, "0")
    _gen(conn, "finder_7m24_1", "meter_status", "", dense, "date_trunc('second', now())", 1,
         "CASE WHEN mod(floor(e)::bigint, 64) < 4 THEN 1 ELSE 0 END",
         "NOT (e BETWEEN extract(epoch FROM now() - interval '3 hours') AND extract(epoch FROM now() - interval '3 hours') + 600)")
    _gen(conn, "finder_7m24_1", "meter_error_code", "", dense, "date_trunc('second', now())", 1, "162",
         "mod(floor(e)::bigint, 64) < 4 AND NOT (e BETWEEN extract(epoch FROM now() - interval '3 hours') "
         "AND extract(epoch FROM now() - interval '3 hours') + 600)")
    _gen(conn, "finder_7m24_1", "meter_error_count", "", dense, "date_trunc('second', now())", 1, "floor(e / 64.0)")
    _gen(conn, "finder_7m24_1", "meter_data_age_ms", "ms", dense, "date_trunc('second', now())", 1, "CASE WHEN mod(floor(e)::bigint, 64) < 4 THEN 3000 ELSE 800 END")
    _gen(conn, "plc-01", "link_status", "", old, dense + " - interval '1 second'", 60, "0")
    _gen(conn, "plc-01", "link_status", "", dense, "date_trunc('second', now())", 1,
         "CASE WHEN e BETWEEN extract(epoch FROM now() - interval '2 hours') AND extract(epoch FROM now() - interval '2 hours') + 120 THEN 1 ELSE 0 END",
         "NOT (e BETWEEN extract(epoch FROM now() - interval '3 hours') AND extract(epoch FROM now() - interval '3 hours') + 600)")
    for metric, (expr, unit) in {"active_power": ("500", "W"), "voltage": ("231", "V"), "current": ("2.2", "A"),
                                 "reactive_power": ("30", "var"), "apparent_power": ("510", "VA"), "power_factor": ("0.98", ""),
                                 "frequency": ("50", "Hz"), "energy_import_wh": ("2000000 + floor(e / 7.2 / 100) * 100", "Wh"),
                                 "meter_status": ("0", "")}.items():
        _gen(conn, "finder_7m24_2", metric, unit, "now() - interval '2 days'", "date_trunc('second', now())", 60, expr)
    refresh_all(conn)
    return {"now": now, "dense_start": dense_start}
