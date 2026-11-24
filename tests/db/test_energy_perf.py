"""Pomiar K6-U4 (k7): widoki *_calc na roku danych syntetycznych. Uruchamiany tylko przez tests/run-perf.sh (AIP_PERF=1).

Próg zakresu k7: typowe zapytania Grafany (24 h z energy_1m_calc, 30 dni z energy_1h_calc, energy_daily_check) < 1 s.
Zbiór danych: dbtools.build_year (jeden wiersz na minutę na metrykę, bez interpolacji; opis ograniczeń w docs/handoff/e2-k7-report.md).
"""
from __future__ import annotations

import os
import statistics
import time

import pytest

from dbtools import METER, admin_connect, build_year, refresh_all, seed_devices

pytestmark = [
    pytest.mark.perf,
    pytest.mark.skipif(os.environ.get("AIP_PERF") != "1", reason="pomiar wydajności: tests/run-perf.sh"),
]

LIMIT_S = 1.0
DAYS = int(os.environ.get("AIP_PERF_DAYS", "365"))

BOUNDED_DELTA = """
WITH prev AS (
    SELECT bucket, import_last FROM energy_1m
    WHERE device_id = %(d)s AND bucket < now() - interval '{span}' AND bucket >= now() - interval '{span}' - interval '3 days'
      AND import_last IS NOT NULL ORDER BY bucket DESC LIMIT 1),
r AS (
    SELECT bucket, import_first, import_last, active_power_n, active_power_sum FROM energy_1m
    WHERE device_id = %(d)s AND bucket >= now() - interval '{span}'),
u AS (
    SELECT bucket, import_first, import_last, active_power_n, active_power_sum, false AS pre FROM r
    UNION ALL SELECT bucket, import_last, import_last, NULL, NULL, true FROM prev),
w AS (SELECT u.*, lag(import_last) OVER (ORDER BY bucket) AS prev_import_last FROM u WHERE import_last IS NOT NULL)
SELECT bucket, active_power_sum / 60.0 / 60.0 AS energy_integral_wh, least(1.0, active_power_n * 60.0 / 60.0) AS coverage,
       CASE WHEN prev_import_last IS NULL THEN import_last - import_first WHEN import_last < prev_import_last THEN import_last
            ELSE import_last - prev_import_last END AS energy_import_delta_wh
FROM w WHERE NOT pre ORDER BY bucket
"""

# Zapytania, których czas MUSI mieścić się w progu. Przyrost minutowy panele liczą LAG w zapytaniu z zapasem 3 dni (wynik K6-U4).
QUERIES = {
    "minuty 24 h, LAG w zapytaniu z zapasem": BOUNDED_DELTA.format(span="24 hours"),
    "minuty 7 dni, LAG w zapytaniu z zapasem": BOUNDED_DELTA.format(span="7 days"),
    "energy_1m 24 h (całka bez przyrostu)": (
        "SELECT bucket, active_power_sum / 60.0 / 60.0 AS energy_integral_wh, active_power_n FROM energy_1m "
        "WHERE device_id = %(d)s AND bucket >= now() - interval '24 hours' ORDER BY bucket"),
    "energy_1h_calc 30 dni": (
        "SELECT bucket, energy_integral_wh, coverage, energy_import_delta_wh FROM energy_1h_calc "
        "WHERE device_id = %(d)s AND bucket >= now() - interval '30 days' ORDER BY bucket"),
    "energy_1h_calc rok": (
        "SELECT bucket, energy_integral_wh, coverage, energy_import_delta_wh FROM energy_1h_calc "
        "WHERE device_id = %(d)s ORDER BY bucket"),
    "energy_daily_check rok": "SELECT * FROM energy_daily_check WHERE device_id = %(d)s ORDER BY day",
    "energy_daily_check 30 dni": (
        "SELECT * FROM energy_daily_check WHERE device_id = %(d)s AND day >= current_date - 30 ORDER BY day"),
}

# Tylko informacyjnie (bez progu): widok minutowy liczy LAG nad całym agregatem, więc filtr po bucket go nie skraca.
# Na roku danych ok. 17 s (a app_reader ma statement_timeout 10 s), dlatego panele go nie używają.
INFORMATIONAL = {
    "energy_1m_calc 24 h (widok, bez progu)": (
        "SELECT bucket, energy_integral_wh, coverage, energy_import_delta_wh FROM energy_1m_calc "
        "WHERE device_id = %(d)s AND bucket >= now() - interval '24 hours' ORDER BY bucket"),
}


@pytest.fixture(scope="module")
def year(pg, request):
    """Jedna baza z rokiem danych dla całego modułu (migracje, dane, odświeżenie agregatów)."""
    import subprocess
    import sys
    import uuid

    from psycopg import sql

    from dbtools import MIGRATE, MIGRATIONS

    name = "perf_" + uuid.uuid4().hex[:8]
    env_pw = os.environ["POSTGRES_PASSWORD"]
    with admin_connect(pg) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    env = {**os.environ, "DB_HOST": pg["host"], "DB_PORT": str(pg["port"]), "POSTGRES_DB": name,
           "POSTGRES_USER": pg["user"], "POSTGRES_PASSWORD": env_pw, "APP_WRITER_PASSWORD": "perf-writer",
           "APP_READER_PASSWORD": "perf-reader", "MIGRATIONS_DIR": str(MIGRATIONS), "DB_WAIT_S": "5"}
    assert subprocess.run([sys.executable, str(MIGRATE)], env=env, capture_output=True, text=True).returncode == 0
    conn = admin_connect(pg, name)
    seed_devices(conn, poll_interval_s=60.0)
    t0 = time.perf_counter()
    info = build_year(conn, DAYS)
    info["load_s"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    refresh_all(conn)
    info["refresh_s"] = time.perf_counter() - t0
    info["db"] = name
    info["m_rows"] = conn.execute("SELECT count(*) FROM energy_1m").fetchone()[0]
    info["h_rows"] = conn.execute("SELECT count(*) FROM energy_1h").fetchone()[0]
    info["size"] = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    conn.execute("ANALYZE")
    print(f"\n[perf] zbiór: {info['rows']} wierszy surowych, {info['m_rows']} wiaderek energy_1m, {info['h_rows']} energy_1h, "
          f"baza {info['size']}; ładowanie {info['load_s']:.0f} s, pierwsze odświeżenie agregatów {info['refresh_s']:.0f} s")
    yield conn, info
    conn.close()
    if os.environ.get("AIP_PERF_KEEP"):
        print(f"[perf] baza {name} zostaje (AIP_PERF_KEEP)")
        return
    with admin_connect(pg) as c:
        c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def timed(conn, query, runs=3):
    times = []
    rows = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        rows = len(conn.execute(query, {"d": METER}).fetchall())
        times.append(time.perf_counter() - t0)
    return times[0], statistics.median(times), rows


def test_calc_views_on_a_year_of_data_stay_under_a_second(year):
    conn, info = year
    assert info["m_rows"] >= DAYS * 1440 * 0.9, "agregat minutowy powinien mieć wiaderko na prawie każdą minutę"
    results = {}
    for name, query in QUERIES.items():
        cold, median, rows = timed(conn, query)
        results[name] = (cold, median, rows)
        print(f"[perf] {name}: {rows} wierszy, pierwszy przebieg {cold * 1000:.0f} ms, mediana {median * 1000:.0f} ms")
    if os.environ.get("AIP_PERF_INFO"):
        for name, query in INFORMATIONAL.items():
            cold, median, rows = timed(conn, query, runs=1)
            print(f"[perf] {name}: {rows} wierszy, {cold * 1000:.0f} ms")
    slow = {n: r[1] for n, r in results.items() if r[1] >= LIMIT_S}
    assert not slow, f"zapytania >= {LIMIT_S} s (mediana): {slow}"
