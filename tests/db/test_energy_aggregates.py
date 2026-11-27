"""Agregaty ciągłe energy_1m i energy_1h (002): zgodność z surowymi danymi, hierarchia, czas rzeczywisty, kompresja, retencja."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from dbtools import METER, refresh_all, seed_devices, series

BASE = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=3)

COLUMNS = (
    "active_power_n active_power_sum active_power_min active_power_max voltage_n voltage_sum voltage_min voltage_max "
    "current_n current_sum reactive_power_n reactive_power_sum apparent_power_n apparent_power_sum "
    "power_factor_n power_factor_sum frequency_n frequency_sum "
    "import_first import_last import_min import_max export_first export_last export_min export_max "
    "meter_error_seconds meter_status_n"
).split()

RAW_SQL = """
SELECT time_bucket(%(width)s::interval, time) AS bucket,
       count(value) FILTER (WHERE metric = 'active_power') AS active_power_n,
       sum(value) FILTER (WHERE metric = 'active_power') AS active_power_sum,
       min(value) FILTER (WHERE metric = 'active_power') AS active_power_min,
       max(value) FILTER (WHERE metric = 'active_power') AS active_power_max,
       count(value) FILTER (WHERE metric = 'voltage') AS voltage_n,
       sum(value) FILTER (WHERE metric = 'voltage') AS voltage_sum,
       min(value) FILTER (WHERE metric = 'voltage') AS voltage_min,
       max(value) FILTER (WHERE metric = 'voltage') AS voltage_max,
       count(value) FILTER (WHERE metric = 'current') AS current_n,
       sum(value) FILTER (WHERE metric = 'current') AS current_sum,
       count(value) FILTER (WHERE metric = 'reactive_power') AS reactive_power_n,
       sum(value) FILTER (WHERE metric = 'reactive_power') AS reactive_power_sum,
       count(value) FILTER (WHERE metric = 'apparent_power') AS apparent_power_n,
       sum(value) FILTER (WHERE metric = 'apparent_power') AS apparent_power_sum,
       count(value) FILTER (WHERE metric = 'power_factor') AS power_factor_n,
       sum(value) FILTER (WHERE metric = 'power_factor') AS power_factor_sum,
       count(value) FILTER (WHERE metric = 'frequency') AS frequency_n,
       sum(value) FILTER (WHERE metric = 'frequency') AS frequency_sum,
       (array_agg(value ORDER BY time) FILTER (WHERE metric = 'energy_import_wh'))[1] AS import_first,
       (array_agg(value ORDER BY time DESC) FILTER (WHERE metric = 'energy_import_wh'))[1] AS import_last,
       min(value) FILTER (WHERE metric = 'energy_import_wh') AS import_min,
       max(value) FILTER (WHERE metric = 'energy_import_wh') AS import_max,
       (array_agg(value ORDER BY time) FILTER (WHERE metric = 'energy_export_wh'))[1] AS export_first,
       (array_agg(value ORDER BY time DESC) FILTER (WHERE metric = 'energy_export_wh'))[1] AS export_last,
       min(value) FILTER (WHERE metric = 'energy_export_wh') AS export_min,
       max(value) FILTER (WHERE metric = 'energy_export_wh') AS export_max,
       count(value) FILTER (WHERE metric = 'meter_status' AND value <> 0) AS meter_error_seconds,
       count(value) FILTER (WHERE metric = 'meter_status') AS meter_status_n
FROM measurements
WHERE device_id = %(device)s
  AND metric IN ('active_power','voltage','current','reactive_power','apparent_power','power_factor','frequency',
                 'energy_import_wh','energy_export_wh','meter_status')
GROUP BY 1 ORDER BY 1
"""


def fill_random(conn, seconds: int = 3 * 3600, seed: int = 7) -> None:
    """Losowe dane z lukami (ok. 8% sekund bez próbki; co kilkaset sekund dłuższa luka), licznik rośnie i raz się zeruje."""
    rng = random.Random(seed)
    import_wh, export_wh = 1_000_000.0, 50_000.0
    rows = []
    for i in range(seconds):
        if 500 < i % 900 < 560 or rng.random() < 0.08:
            continue
        t = BASE + timedelta(seconds=i)
        if i == seconds // 2:
            import_wh = 0.0                                          # reset licznika
        elif rng.random() < 0.01:
            import_wh += 100.0
        if rng.random() < 0.005:
            export_wh += 100.0
        status = 0.0 if rng.random() < 0.9 else 1.0
        rows += [(t, "active_power", rng.uniform(0, 3000)), (t, "voltage", rng.uniform(225, 245)),
                 (t, "current", rng.uniform(0, 10)), (t, "meter_status", status),
                 (t, "energy_import_wh", import_wh), (t, "energy_export_wh", export_wh)]
        if status == 0.0:
            rows += [(t, "reactive_power", rng.uniform(-500, 500)), (t, "apparent_power", rng.uniform(0, 3000)),
                     (t, "power_factor", rng.uniform(0, 1)), (t, "frequency", rng.uniform(49.9, 50.1))]
    with conn.cursor() as cur:
        with cur.copy("COPY measurements (time, device_id, metric, value, unit, source) FROM STDIN") as copy:
            for t, metric, value in rows:
                copy.write_row((t, METER, metric, value, "", "real"))


def same(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) or isinstance(b, float):
        return a == pytest.approx(b, rel=1e-9, abs=1e-9)
    return a == b


def compare_with_raw(conn, view: str, width: str) -> int:
    cursor = conn.execute(RAW_SQL, {"width": width, "device": METER})
    names = [d.name for d in cursor.description]
    raw = cursor.fetchall()
    agg = conn.execute(f"SELECT {', '.join(names)} FROM {view} WHERE device_id = %s ORDER BY bucket", (METER,)).fetchall()
    assert len(agg) == len(raw), f"{view}: {len(agg)} wiaderek, z surowych danych {len(raw)}"
    for got, want in zip(agg, raw):
        for name, g, w in zip(names, got, want):
            assert same(g, w), f"{view} {got[0]} {name}: {g} != {w}"
    return len(raw)


@pytest.fixture
def data(admin):
    seed_devices(admin)
    fill_random(admin)
    refresh_all(admin)
    return admin


def test_energy_1m_equals_recomputation_from_raw_data(data):
    assert compare_with_raw(data, "energy_1m", "1 minute") >= 170


def test_energy_1h_equals_recomputation_from_raw_data(data):
    """Agregat godzinny złożony z minutowych równa się liczonemu wprost z surowych danych (właściwość hierarchii)."""
    assert compare_with_raw(data, "energy_1h", "1 hour") >= 3


def test_plc_link_status_creates_no_rows(admin):
    seed_devices(admin)
    series(admin, "link_status", BASE, 600, "0", device="plc-01")
    series(admin, "voltage", BASE, 600, "230", unit="V")
    refresh_all(admin)
    assert admin.execute("SELECT count(*) FROM energy_1m WHERE device_id = 'plc-01'").fetchone()[0] == 0
    assert admin.execute("SELECT count(*) FROM energy_1h WHERE device_id = 'plc-01'").fetchone()[0] == 0
    assert admin.execute("SELECT count(*) FROM energy_1m WHERE device_id = %s", (METER,)).fetchone()[0] == 10


def test_meter_status_counts_error_seconds(admin):
    seed_devices(admin)
    series(admin, "meter_status", BASE, 60, "CASE WHEN g < 5 THEN 1 ELSE 0 END")
    refresh_all(admin)
    row = admin.execute("SELECT meter_error_seconds, meter_status_n FROM energy_1m").fetchone()
    assert row == (5, 60)


def test_real_time_mode_shows_the_newest_unmaterialized_bucket(admin):
    seed_devices(admin)
    series(admin, "active_power", BASE, 120, "100")
    admin.execute("CALL refresh_continuous_aggregate('energy_1m', NULL, %s)", (BASE + timedelta(minutes=2),))
    series(admin, "active_power", BASE + timedelta(minutes=2), 30, "200")              # po znaczniku materializacji
    rows = admin.execute("SELECT bucket, active_power_n, active_power_sum FROM energy_1m ORDER BY bucket").fetchall()
    assert [(r[1], r[2]) for r in rows] == [(60, 6000.0), (60, 6000.0), (30, 6000.0)]
    assert rows[-1][0] == BASE + timedelta(minutes=2)
    flags = admin.execute(
        "SELECT view_name, materialized_only FROM timescaledb_information.continuous_aggregates ORDER BY 1").fetchall()
    assert flags == [("energy_1h", False), ("energy_1m", False), ("energy_ext_1h", False), ("energy_ext_1m", False),
                     ("pump_1m", False)]                               # pump_1m: migracja 012 (E3-k4)


def test_late_data_is_corrected_by_the_next_refresh(admin):
    seed_devices(admin)
    series(admin, "active_power", BASE, 60, "100")
    refresh_all(admin)
    admin.execute("INSERT INTO measurements VALUES (%s, %s, 'active_power', 500, 'W', 'real')",
                  (BASE + timedelta(seconds=59, milliseconds=500), METER))              # spóźniona próbka w starym wiaderku
    assert admin.execute("SELECT active_power_n FROM energy_1m").fetchone()[0] == 60    # jeszcze niewidoczna
    refresh_all(admin)
    assert admin.execute("SELECT active_power_n, active_power_sum FROM energy_1m").fetchone() == (61, 6500.0)
    assert admin.execute("SELECT active_power_n FROM energy_1h").fetchone()[0] == 61


def test_compressed_raw_chunk_gives_the_same_aggregates(admin):
    """Pierwsze zmaterializowanie z już skompresowanych surowych kawałków daje wynik równy przeliczeniu z surowych danych."""
    seed_devices(admin)
    fill_random(admin, seconds=3600)
    compressed = admin.execute(
        "SELECT count(compress_chunk(c, if_not_compressed => true)) FROM show_chunks('measurements') c").fetchone()[0]
    assert compressed >= 1
    refresh_all(admin)
    assert compare_with_raw(admin, "energy_1m", "1 minute") >= 55
    assert compare_with_raw(admin, "energy_1h", "1 hour") >= 1


def test_retention_of_raw_data_keeps_materialized_buckets_inside_the_policy_window(admin):
    """Okno polityki (7 dni) jest krótsze niż retencja surowych danych (90 dni): drop_chunks nie kasuje wiaderek."""
    seed_devices(admin)
    old = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=100)
    series(admin, "active_power", old, 600, "100")
    admin.execute("CALL refresh_continuous_aggregate('energy_1m', NULL, NULL)")
    assert admin.execute("SELECT count(*) FROM energy_1m").fetchone()[0] == 10
    dropped = admin.execute("SELECT count(*) FROM drop_chunks('measurements', older_than => INTERVAL '90 days')").fetchone()[0]
    assert dropped >= 1
    assert admin.execute("SELECT count(*) FROM measurements").fetchone()[0] == 0
    # odświeżenie w oknie polityki (ostatnie 7 dni) nie dotyka starych wiaderek
    admin.execute("CALL refresh_continuous_aggregate('energy_1m', now() - INTERVAL '7 days', now() - INTERVAL '1 minute')")
    assert admin.execute("SELECT count(*), sum(active_power_n) FROM energy_1m").fetchone() == (10, 600)
