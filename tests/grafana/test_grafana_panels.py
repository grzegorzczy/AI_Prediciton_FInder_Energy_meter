"""Harness paneli (G7-e): każdy cel każdego panelu każdego dashboardu przez API Grafany na bazie testowej."""
from __future__ import annotations

import time

import pytest

from grafana_support import RANGES, dashboards, ds_query, expand_vars, targets

M1, M2 = "finder_7m24_1", "finder_7m24_2"
DASHES = dashboards()

# Panele, które z założenia są puste dla danego zakresu (ograniczenie zakresu zapisane w SQL i w opisie panelu).
EXPECT_EMPTY = {
    ("Wiersze na minutę w bazie", "7d"), ("Wiersze na minutę w bazie", "30d"),
    ("Zużycie na minutę", "30d"),
    ("Łącze z PLC (link_status)", "30d"), ("Stan licznika (meter_status)", "30d"),
    ("Kod błędu komunikacji PLC–licznik (meter_error_code)", "30d"),
}
# Zakresy, w których z definicji danych może nie być odpowiednich próbek.
MAY_BE_EMPTY = {
    ("Moc bazowa (5. percentyl nocą)", "15m"), ("Moc bazowa (5. percentyl nocą)", "6h"),
    ("Sekundy bez pomiaru mocy na godzinę", "15m"),
    ("Zużycie na godzinę", "15m"), ("Zużycie na minutę", "15m"),
    ("Kod błędu komunikacji PLC–licznik (meter_error_code)", "7d"),
}
MAX_QUERY_S = 3.0


def run(dash, range_name, device):
    end = time.time()
    start = end - RANGES[range_name]
    out = []
    for title, target in targets(dash):
        sql = expand_vars(target["rawSql"], device)
        out.append((title, target["refId"], sql, ds_query(sql, target["format"], start, end, target["refId"])))
    return out


def rows_by_panel(dash, range_name, device):
    by_panel: dict[str, int] = {}
    for title, _, _, result in run(dash, range_name, device):
        by_panel[title] = by_panel.get(title, 0) + result["rows"]
    return by_panel


@pytest.mark.parametrize("range_name", list(RANGES))
@pytest.mark.parametrize("name", sorted(DASHES))
def test_every_panel_query_runs_without_error_for_both_meters(grafana_data, name, range_name):
    for device in (M1, M2):
        for title, ref, sql, result in run(DASHES[name], range_name, device):
            assert not result["error"], f"{name}/{title}[{ref}] {device} {range_name}: {result['error']}\n{sql}"
            assert result["elapsed"] < MAX_QUERY_S, f"{name}/{title} {device} {range_name}: {result['elapsed']:.1f} s"


@pytest.mark.parametrize("range_name", ["6h", "24h", "7d", "30d"])
@pytest.mark.parametrize("name", sorted(DASHES))
def test_every_panel_returns_data_for_the_main_meter(grafana_data, name, range_name):
    for title, rows in rows_by_panel(DASHES[name], range_name, M1).items():
        if (title, range_name) in EXPECT_EMPTY:
            assert rows == 0, f"{name}/{title} {range_name}: panel ograniczony zakresem powinien być pusty, a ma {rows} wierszy"
        elif (title, range_name) not in MAY_BE_EMPTY:
            assert rows > 0, f"{name}/{title} {range_name}: brak danych"


def test_live_panels_return_data_for_a_short_range(grafana_data):
    for name in ("przeglad", "na-zywo"):
        for title, rows in rows_by_panel(DASHES[name], "15m", M1).items():
            assert rows > 0 or (title, "15m") in MAY_BE_EMPTY, f"{name}/{title}: brak danych w ostatnich 15 minutach"


def test_device_variable_separates_the_meters(grafana_data):
    power = next(t for title, t in targets(DASHES["na-zywo"]) if title == "Moc czynna P: teraz")
    now = time.time()
    first = ds_query(expand_vars(power["rawSql"], M1), "time_series", now - 900, now)
    second = ds_query(expand_vars(power["rawSql"], M2), "time_series", now - 900, now)
    values_1 = [v for v in first["frames"][0]["data"]["values"][1] if v is not None]
    values_2 = [v for v in second["frames"][0]["data"]["values"][1] if v is not None]
    assert values_2 and all(abs(v - 500) < 1e-6 for v in values_2), "licznik 2 ma stałą moc 500 W"
    assert values_1 and all(v < 200 for v in values_1), "licznik 1 nie może widzieć mocy licznika 2"


def test_overview_age_is_fresh_and_power_is_present(grafana_data):
    now = time.time()
    by_title = {title: target for title, target in targets(DASHES["przeglad"])}
    age = ds_query(expand_vars(by_title["Wiek ostatniego odczytu"]["rawSql"], M1), "table", now - 60, now)
    expected = time.time() - grafana_data["now"].timestamp()          # dane syntetyczne kończą się w chwili ich utworzenia
    value = age["frames"][0]["data"]["values"][1][0]
    assert 0 <= value <= expected + 5          # kolejne instrukcje ładowania mają własne now(), więc koniec danych bywa nowszy
    power = ds_query(expand_vars(by_title["Moc czynna teraz"]["rawSql"], M1), "time_series", now - 600, now)
    assert power["rows"] > 0
