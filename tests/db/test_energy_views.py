"""Widoki pochodne energii (003): całka, pokrycie, przyrost licznika, kontrola dobowa (Europe/Warsaw)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from dbtools import METER, refresh_all, seed_devices, series

BASE = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(days=3)
MIN = timedelta(minutes=1)


def calc(conn, view="energy_1m_calc", columns="*"):
    refresh_all(conn)
    cursor = conn.execute(f"SELECT {columns} FROM {view} WHERE device_id = %s ORDER BY bucket", (METER,))
    names = [d.name for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def test_integral_and_coverage(admin):
    seed_devices(admin)
    series(admin, "active_power", BASE, 60, "100")                       # pełna minuta
    series(admin, "active_power", BASE + MIN, 56, "100")                 # 4 s luki
    series(admin, "meter_status", BASE + 2 * MIN, 60, "1")               # minuta bez próbek mocy
    rows = calc(admin)
    assert [r["bucket"] for r in rows] == [BASE, BASE + MIN, BASE + 2 * MIN]
    assert rows[0]["energy_integral_wh"] == pytest.approx(100 * 60 / 3600, abs=1e-12)
    assert rows[0]["coverage"] == 1.0
    assert rows[1]["energy_integral_wh"] == pytest.approx(100 * 56 / 3600, abs=1e-12)
    assert rows[1]["coverage"] == pytest.approx(56 / 60, abs=1e-12) and round(rows[1]["coverage"], 4) == 0.9333
    assert rows[2]["coverage"] == 0 and rows[2]["energy_integral_wh"] is None
    assert rows[0]["active_power_avg"] == 100


def test_no_interpolation_across_a_gap(admin):
    seed_devices(admin)
    series(admin, "active_power", BASE, 60, "100")
    series(admin, "active_power", BASE + 5 * MIN, 60, "100")
    rows = calc(admin)
    assert len(rows) == 2                                                # minut 1-4 nie ma, nikt ich nie wypełnia
    assert sum(r["energy_integral_wh"] for r in rows) == pytest.approx(2 * 100 * 60 / 3600, abs=1e-12)
    hourly = calc(admin, "energy_1h_calc")[0]
    assert hourly["energy_integral_wh"] == pytest.approx(2 * 100 * 60 / 3600, abs=1e-12)
    assert hourly["coverage"] == pytest.approx(120 / 3600)


def test_missing_meta_gives_null_not_a_default(admin):
    seed_devices(admin, poll_interval_s=None, resolution_wh=None)
    series(admin, "active_power", BASE, 60, "100")
    row = calc(admin)[0]
    assert row["energy_integral_wh"] is None and row["coverage"] is None
    assert row["active_power_avg"] == 100 and row["active_power_n"] == 60       # wartości niezależne od meta zostają
    assert row["poll_interval_s"] is None and row["resolution_wh"] is None


def test_counter_delta_reset_gap_and_first_bucket(admin):
    seed_devices(admin)
    series(admin, "energy_import_wh", BASE, 60, "1000")                                       # m0: pierwsze wiaderko
    series(admin, "energy_import_wh", BASE + 1 * MIN, 60, "1000 + CASE WHEN g >= 30 THEN 100 ELSE 0 END")   # m1: +100
    series(admin, "meter_status", BASE + 2 * MIN, 60, "1")                                    # m2: licznik w błędzie, brak energii
    series(admin, "energy_import_wh", BASE + 3 * MIN, 60, "1100")                             # m3: bez zmiany
    series(admin, "energy_import_wh", BASE + 4 * MIN, 60, "200")                              # m4: reset licznika
    series(admin, "energy_import_wh", BASE + 10 * MIN, 60, "300")                             # m10: po luce
    by = {r["bucket"]: r for r in calc(admin)}
    m = lambda i: by[BASE + i * MIN]                                                          # noqa: E731

    assert m(0)["energy_import_delta_wh"] == 0 and not m(0)["gap_before"]                     # last - first
    assert m(1)["energy_import_delta_wh"] == 100 and not m(1)["import_reset"]
    assert m(2)["energy_import_delta_wh"] is None                                             # brak odczytu energii
    assert m(3)["energy_import_delta_wh"] == 0                                                # nie zerowane przez m2
    assert m(3)["gap_before"] is True                                                         # przyrost obejmuje minutę bez odczytu
    assert m(4)["energy_import_delta_wh"] == 200 and m(4)["import_reset"] is True             # reset: przyrost = import_last
    assert m(4)["gap_before"] is False
    assert m(10)["energy_import_delta_wh"] == 100 and m(10)["gap_before"] is True


def test_export_counter_delta_is_independent_of_import(admin):
    seed_devices(admin)
    series(admin, "energy_export_wh", BASE, 60, "50")
    series(admin, "energy_export_wh", BASE + MIN, 60, "50 + CASE WHEN g >= 10 THEN 100 ELSE 0 END")
    rows = calc(admin)
    assert [r["energy_export_delta_wh"] for r in rows] == [0, 100]
    assert [r["energy_import_delta_wh"] for r in rows] == [None, None]


def test_bucket_complete_distinguishes_the_running_bucket(admin):
    seed_devices(admin)
    series(admin, "active_power", BASE, 60, "100")
    now = datetime.now(timezone.utc)
    series(admin, "active_power", now - timedelta(seconds=5), 5, "100")
    rows = calc(admin)
    assert rows[0]["bucket_complete"] is True
    assert rows[-1]["bucket_complete"] is False and rows[-1]["coverage"] < 1
    assert calc(admin, "energy_1h_calc")[-1]["bucket_complete"] in (True, False)


# --- kontrola dobowa -------------------------------------------------------------------------------------------------

def local_midnight(conn, day: date) -> datetime:
    return conn.execute("SELECT %s::date::timestamp AT TIME ZONE 'Europe/Warsaw'", (day,)).fetchone()[0]


def full_day(conn, day: date, power_w: float, counter_sql: str | None, hole: tuple[int, int] | None = None,
             power_seconds: int | None = None) -> None:
    """Doba lokalna `day` plus godzina przed nią (dla poprzedniego wiaderka licznika); 1 próbka mocy na sekundę."""
    start = local_midnight(conn, day) - timedelta(hours=1)
    end = local_midnight(conn, day + timedelta(days=1))
    total = int((end - start).total_seconds())
    series(conn, "active_power", start + timedelta(hours=1), power_seconds or total - 3600, str(power_w))
    if hole:
        conn.execute(
            "DELETE FROM measurements WHERE metric = 'active_power' AND time >= %s AND time < %s",
            (start + timedelta(hours=1, seconds=hole[0]), start + timedelta(hours=1, seconds=hole[1])))
    if counter_sql:
        series(conn, "energy_import_wh", start, total, counter_sql)


def one_day(conn, day: date) -> dict:
    refresh_all(conn)
    cursor = conn.execute("SELECT * FROM energy_daily_check WHERE device_id = %s AND day = %s", (METER, day))
    names = [d.name for d in cursor.description]
    rows = cursor.fetchall()
    assert len(rows) == 1
    return dict(zip(names, rows[0]))


COUNTER_100W = "1000000 + floor(g / 3600.0) * 100"        # 100 W = 100 Wh/h: krok licznika 100 Wh co godzinę


def test_daily_check_matching_day_with_95_percent_coverage(admin):
    seed_devices(admin)
    day = date(2026, 11, 10)
    full_day(admin, day, 100, COUNTER_100W, hole=(10 * 3600, 10 * 3600 + 4320))          # 5% doby bez próbek mocy
    row = one_day(admin, day)
    assert row["coverage"] == pytest.approx(0.95)
    assert row["integral_wh"] == pytest.approx(2280.0)
    assert row["counter_delta_wh"] == 2400
    assert row["integral_extrapolated_wh"] == pytest.approx(2400.0)
    assert row["diff_wh"] == pytest.approx(0.0, abs=1e-6)
    assert row["resolution_wh"] == 100
    assert row["within_resolution"] is True
    assert row["deviation_pct"] == pytest.approx(0.0, abs=1e-6)
    assert row["day_complete"] is True and row["gap_before_count"] == 0


def test_daily_check_flags_a_300_wh_mismatch(admin):
    seed_devices(admin)
    day = date(2026, 11, 10)
    full_day(admin, day, 100, COUNTER_100W + " + CASE WHEN g > 13 * 3600 THEN 300 ELSE 0 END")
    row = one_day(admin, day)
    assert row["counter_delta_wh"] == 2700
    assert row["diff_wh"] == pytest.approx(-300.0)
    assert row["within_resolution"] is False
    assert row["deviation_pct"] == pytest.approx(100 * -300 / 2700)


def test_daily_check_gives_no_percentage_for_a_small_counter_increment(admin):
    seed_devices(admin)
    day = date(2026, 11, 10)
    full_day(admin, day, 10, "1000000 + floor(g / 36000.0) * 100")                       # 10 W: 240 Wh na dobę
    row = one_day(admin, day)
    assert row["integral_wh"] == pytest.approx(240.0)
    assert row["counter_delta_wh"] < 5 * row["resolution_wh"]
    assert row["deviation_pct"] is None
    assert row["within_resolution"] is not None


def test_daily_check_refuses_to_extrapolate_below_half_coverage(admin):
    seed_devices(admin)
    day = date(2026, 11, 10)
    full_day(admin, day, 100, COUNTER_100W, power_seconds=int(0.4 * 86400))
    row = one_day(admin, day)
    assert row["coverage"] == pytest.approx(0.4)
    assert row["integral_extrapolated_wh"] is None and row["diff_wh"] is None
    assert row["within_resolution"] is None and row["deviation_pct"] is None


@pytest.mark.parametrize("day, hours", [(date(2026, 10, 25), 25), (date(2026, 3, 29), 23)])
def test_daily_check_handles_days_with_a_time_change(admin, day, hours):
    seed_devices(admin)
    admin.execute("SELECT remove_retention_policy('measurements')")        # 29.03 jest starsze niż 90 dni: zadanie retencji skasowałoby dane testu
    start, end = local_midnight(admin, day), local_midnight(admin, day + timedelta(days=1))
    assert (end - start) == timedelta(hours=hours)
    series(admin, "active_power", start, hours * 3600, "100")
    row = one_day(admin, day)
    assert row["coverage"] == pytest.approx(1.0)
    assert row["integral_wh"] == pytest.approx(100.0 * hours)


def test_current_day_is_not_complete(admin):
    seed_devices(admin)
    series(admin, "active_power", datetime.now(timezone.utc) - timedelta(seconds=100), 60, "100")
    today = admin.execute("SELECT (now() AT TIME ZONE 'Europe/Warsaw')::date").fetchone()[0]
    assert one_day(admin, today)["day_complete"] is False


def test_daily_check_without_sampling_interval_has_null_coverage(admin):
    seed_devices(admin, poll_interval_s=None)
    day = date(2026, 11, 10)
    full_day(admin, day, 100, COUNTER_100W)
    row = one_day(admin, day)
    assert row["coverage"] is None and row["integral_wh"] is None
    assert row["within_resolution"] is None and row["integral_extrapolated_wh"] is None
    assert row["counter_delta_wh"] == 2400                      # przyrost licznika nie zależy od okresu próbkowania
