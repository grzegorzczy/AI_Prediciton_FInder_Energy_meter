"""Harness paneli (G7-e): każdy cel każdego panelu każdego dashboardu przez API Grafany na bazie testowej."""
from __future__ import annotations

import time

import pytest

from grafana_support import RANGES, dashboards, ds_query, effective_seconds, expand_vars, load_generator, panel_targets, targets

M1, M2 = "finder_7m24_1", "finder_7m24_2"
DASHES = dashboards()

# Panele, które z założenia są puste dla danego zakresu (ograniczenie zakresu zapisane w SQL i w opisie panelu).
EXPECT_EMPTY = {
    ("Wiersze na minutę w bazie", "7d"), ("Wiersze na minutę w bazie", "30d"),
    ("Zużycie na minutę", "30d"),
}
# Osie stanów mają wiersz-wartownik (pole czasu przy pustym wyniku, K7-V4): przy ograniczeniu zakresu zostaje tylko on.
SENTINEL_ONLY = {
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
    for panel, target in panel_targets(dash):
        # panel z własnym zakresem czasu (timeFrom) używa go zamiast zakresu pulpitu
        panel_start = end - effective_seconds(panel, RANGES[range_name])
        sql = expand_vars(target["rawSql"], device)
        out.append((panel["title"], target["refId"], sql, ds_query(sql, target["format"], panel_start, end, target["refId"])))
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
        if (title, range_name) in SENTINEL_ONLY:
            assert rows <= 1, f"{name}/{title} {range_name}: ograniczony zakres powinien dać tylko wiersz-wartownik, a jest {rows}"
        elif (title, range_name) in EXPECT_EMPTY:
            assert rows == 0, f"{name}/{title} {range_name}: panel ograniczony zakresem powinien być pusty, a ma {rows} wierszy"
        elif (title, range_name) not in MAY_BE_EMPTY:
            assert rows > 0, f"{name}/{title} {range_name}: brak danych"


def test_live_panels_return_data_for_a_short_range(grafana_data):
    for name in ("przeglad", "na-zywo"):
        for title, rows in rows_by_panel(DASHES[name], "15m", M1).items():
            assert rows > 0 or (title, "15m") in MAY_BE_EMPTY, f"{name}/{title}: brak danych w ostatnich 15 minutach"


def test_device_variable_separates_the_meters(grafana_data):
    power = next(t for title, t in targets(DASHES["na-zywo"]) if title == "Moc czynna P")
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


def test_error_code_timeline_returns_to_no_error_after_each_episode(grafana_data):
    """k7c W-2: po każdym epizodzie wiersz „0” (Brak błędu), żeby kod nie ciągnął się do końca zakresu."""
    panel = next(p for p in DASHES["diagnostyka"]["panels"] if p["title"].startswith("Kod błędu"))
    target = panel["targets"][0]
    now = time.time()
    result = ds_query(expand_vars(target["rawSql"], M1), target["format"], now - 6 * 3600, now, target["refId"])
    assert not result["error"], result["error"]
    values = result["frames"][0]["data"]["values"][1]
    assert set(values) == {0.0, 162.0}
    assert values[0] == 0.0 and values[-1] == 0.0          # zaczyna i kończy się „brakiem błędu”
    assert values.count(162.0) > 20 and values.count(0.0) > 20


def test_error_code_timeline_returns_to_no_error_after_each_episode(grafana_data):
    """k7c W-2: po każdym epizodzie wiersz „0” (Brak błędu), żeby kod nie ciągnął się do końca zakresu."""
    panel = next(p for p in DASHES["diagnostyka"]["panels"] if p["title"].startswith("Kod błędu"))
    target = panel["targets"][0]
    now = time.time()
    result = ds_query(expand_vars(target["rawSql"], M1), target["format"], now - 6 * 3600, now, target["refId"])
    assert not result["error"], result["error"]
    values = result["frames"][0]["data"]["values"][1]
    assert set(values) == {0.0, 162.0}
    assert values[0] == 0.0 and values[-1] == 0.0          # zaczyna i kończy się „brakiem błędu”
    assert values.count(162.0) > 20 and values.count(0.0) > 20


def normalize(values):
    """Wartości do porównania: liczby do 9 cyfr znaczących (szum sumowania), a procent doby „w toku” zależy od zegara i jest pomijany."""
    import re

    out = []
    for v in values:
        if isinstance(v, float):
            v = float(f"{v:.9g}")
        elif isinstance(v, str):
            v = re.sub(r"\(w toku, \d+%\)", "(w toku)", v)
        out.append(v)
    return out


def test_own_range_panels_return_the_same_data_for_any_dashboard_range(grafana_data):
    """k7d: panele z własnym zakresem (14 i 28 dni) dają ten sam wynik dla zakresu względnego i bezwzględnego z innej doby."""
    from grafana_support import load_generator

    generator = load_generator()
    now = time.time()
    ranges = [(now - 3 * 3600, now), (now - 30 * 86400, now - 29 * 86400), (now - 600, now)]       # względny i dwa bezwzględne
    for (name, title), _ in generator.OWN_RANGE_PANELS.items():
        panel = next(p for p in DASHES[name]["panels"] if p["title"] == title)
        target = panel["targets"][0]
        results = []
        for start, end in ranges:
            result = ds_query(expand_vars(target["rawSql"], M1), target["format"], start, end, target["refId"])
            assert not result["error"], f"{title}: {result['error']}"
            # kolumn czasu (np. `now()` w kafelkach) nie porównujemy: różnią się o milisekundy między wywołaniami
            results.append([[normalize(v) for field, v in zip(f["schema"]["fields"], f["data"]["values"]) if field.get("type") != "time"]
                            for f in result["frames"]])
        assert results[0] == results[1] == results[2], f"{title}: wynik zależy od zakresu pulpitu"
        assert results[0] and results[0][0][0], f"{title}: brak danych"


V2_PANEL_TITLES = {"THD napięcia", "THD prądu", "Kąt U–I", "THD napięcia (THD U)", "THD prądu (THD I)", "Temperatura licznika",
                   "Temperatura licznika [°C]", "Czas pracy licznika", "Czas pracy licznika [dni]"}


def test_v2_panels_return_data_for_the_meter_with_v2_and_no_rows_for_the_meter_without(grafana_data):
    """E2-PLC2: licznik 1 ma dane v2 (ostatnie 2 doby), licznik 2 ich nie ma: panele mają zwrócić brak wierszy, a nie zera."""
    for name in ("na-zywo", "jakosc", "diagnostyka"):
        with_v2 = rows_by_panel(DASHES[name], "6h", M1)
        without_v2 = rows_by_panel(DASHES[name], "6h", M2)
        for title in V2_PANEL_TITLES & set(with_v2):
            assert with_v2[title] > 0, f"{name}/{title}: licznik z danymi v2 bez wierszy"
            if title in NULL_ROW_TILES:                       # kafelki z podzapytaniem zwracają jeden wiersz z NULL (patrz test niżej)
                continue
            assert without_v2[title] == 0, f"{name}/{title}: licznik bez v2 ma {without_v2[title]} wierszy (powinien być brak danych)"


NULL_ROW_TILES = {"Temperatura licznika", "Czas pracy licznika"}


def test_v2_tiles_without_data_return_null_not_zero(grafana_data):
    """Kafelki temperatury i czasu pracy: licznik bez v2 daje NULL (panel pokaże „Brak danych (mapa v1)”), nigdy 0."""
    now = time.time()
    for title in NULL_ROW_TILES:
        panel = next(p for p in DASHES["diagnostyka"]["panels"] if p["title"] == title)
        target = panel["targets"][0]
        without = ds_query(expand_vars(target["rawSql"], M2), target["format"], now - 6 * 3600, now)
        with_v2 = ds_query(expand_vars(target["rawSql"], M1), target["format"], now - 6 * 3600, now)
        assert without["frames"][0]["data"]["values"][1] == [None], title
        assert with_v2["frames"][0]["data"]["values"][1][0] not in (None, 0), title


def test_thd_values_are_the_stored_ones_not_zero_filled(grafana_data):
    """Wartości paneli THD i kąta pochodzą z danych (a nie z wypełnienia zerami): THD I ok. 140%, kąt ok. -50,5°."""
    panel = next(p for p in DASHES["jakosc"]["panels"] if p["title"] == "THD prądu (THD I)")
    now = time.time()
    result = ds_query(expand_vars(panel["targets"][0]["rawSql"], M1), "time_series", now - 6 * 3600, now)
    averages = [v for v in result["frames"][0]["data"]["values"][2] if v is not None]
    assert averages and all(130 < v < 150 for v in averages)
    angle = next(p for p in DASHES["jakosc"]["panels"] if p["title"] == "Kąt U–I")
    result = ds_query(expand_vars(angle["targets"][0]["rawSql"], M1), "time_series", now - 6 * 3600, now)
    assert all(-52 < v < -49 for v in result["frames"][0]["data"]["values"][2] if v is not None)


def test_pf_panel_cos_phi_series_matches_the_stored_angle(grafana_data):
    import math

    panel = next(p for p in DASHES["jakosc"]["panels"] if p["title"] == "Współczynnik mocy PF")
    target = panel["targets"][1]
    now = time.time()
    result = ds_query(expand_vars(target["rawSql"], M1), "time_series", now - 6 * 3600, now, target["refId"])
    values = [v for v in result["frames"][0]["data"]["values"][1] if v is not None]
    assert values and all(abs(v - math.cos(math.radians(-50.5))) < 0.03 for v in values)


@pytest.mark.parametrize("title,metric_device", [("Łącze z PLC (link_status)", None), ("Stan licznika (meter_status)", None)])
def test_state_timeline_resumes_after_a_gap_without_a_change_of_state(grafana_data, title, metric_device):
    """K8-V1: w danych testowych jest 10-minutowa luka sprzed 3 godzin ze stanem 0 przed i po niej: po „Brak danych” (100)
    musi być wiersz stanu, bo inaczej oś zostaje w „Brak danych” do końca zakresu."""
    no_data = load_generator().NO_DATA_CODE
    panel = next(p for p in DASHES["diagnostyka"]["panels"] if p["title"] == title)
    target = panel["targets"][0]
    now = time.time()
    result = ds_query(expand_vars(target["rawSql"], M1), target["format"], now - 6 * 3600, now, target["refId"])
    assert not result["error"], result["error"]
    values = [v for v in result["frames"][0]["data"]["values"][1] if v is not None]
    assert no_data in values, "luka sprzed 3 godzin powinna dać stan „Brak danych”"
    for position, value in enumerate(values):
        if value == no_data:
            assert position + 1 < len(values) and values[position + 1] != no_data, f"{title}: po „Brak danych” nie wraca stan"
    assert values[-1] != no_data, f"{title}: oś kończy się w „Brak danych” mimo płynących danych"
