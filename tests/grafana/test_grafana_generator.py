"""Generator dashboardów (G7-b): zgodność JSON w repo, kody statusów z dokumentu, zasada 8, opisy paneli."""
from __future__ import annotations

import re

from collector.status import ERROR_CODE_NAMES, LinkStatus, MeterStatus
from grafana_support import dashboards, load_generator, targets

FORBIDDEN = re.compile(r"przewidywani\w* awari|predykcj\w* awari|predict", re.IGNORECASE)


def test_json_in_repo_equals_generator_output():
    generator = load_generator()
    for name, text in generator.render().items():
        assert (generator.OUT / f"{name}.json").read_text(encoding="utf-8") == text, f"{name}.json różni się od generatora"


def test_five_dashboards_with_stable_uids_and_a_device_variable():
    dashes = dashboards()
    assert {d["uid"] for d in dashes.values()} == {"aip-przeglad", "aip-na-zywo", "aip-jakosc", "aip-energia", "aip-diagnostyka"}
    for dash in dashes.values():
        names = [v["name"] for v in dash["templating"]["list"]]
        assert names[0] == "device"
        assert dash["timezone"] == "Europe/Warsaw"
        assert dash["annotations"]["list"], "brak adnotacji okien testów i przerw"


def test_status_mappings_equal_the_documented_codes():
    generator = load_generator()
    assert set(generator.CODES["link"]) == {int(s) for s in LinkStatus}
    assert set(generator.CODES["meter"]) == {int(s) for s in MeterStatus}
    assert generator.CODES["errors"] == ERROR_CODE_NAMES
    states = {p["title"]: p for d in dashboards().values() for p in d["panels"] if p["type"] == "state-timeline"}
    link = states["Łącze z PLC (link_status)"]["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert {k: v["text"] for k, v in link.items() if k != "100"} == {str(k): v for k, v in generator.CODES["link"].items()}
    error = states["Kod błędu komunikacji PLC–licznik (meter_error_code)"]["fieldConfig"]["defaults"]["mappings"][0]["options"]
    for code, name in ERROR_CODE_NAMES.items():
        assert error[str(code)]["text"] == f"{code} {name}"


def test_no_failure_prediction_wording_and_every_panel_is_described():
    for name, dash in dashboards().items():
        assert not FORBIDDEN.search(dash["title"] + dash["description"]), name
        for panel in dash["panels"]:
            assert panel["description"].strip(), f"{name}: panel bez opisu: {panel['title']}"
            assert not FORBIDDEN.search(panel["title"] + panel["description"]), panel["title"]


def test_queries_use_only_allowed_sources_and_never_write():
    forbidden = re.compile(r"\b(insert|update|delete|drop|create|alter|truncate)\b", re.IGNORECASE)
    for name, dash in dashboards().items():
        for title, target in targets(dash):
            sql = target["rawSql"]
            assert not forbidden.search(sql), f"{name}/{title}: zapytanie zmieniające dane"
            assert target["datasource"]["uid"] == "aip-timescaledb"


def test_long_ranges_use_aggregates_not_raw_measurements():
    """Panele zakresów dłuższych niż doba nie czytają `measurements` bez ograniczenia zakresu (K6-U4, plan k7)."""
    for name, dash in dashboards().items():
        if name in ("jakosc", "energia"):
            for title, target in targets(dash):
                assert "FROM measurements" not in target["rawSql"], f"{name}/{title}"


# --- poprawki wyglądu K7-V1…V15 (k7b) ----------------------------------------------------------------------------------------

def _panels():
    return {(name, p["title"]): p for name, d in dashboards().items() for p in d["panels"]}


def test_every_row_of_every_dashboard_spans_the_full_grid_width():
    """K7-V14: bez pustych miejsc po prawej."""
    for name, dash in dashboards().items():
        rows: dict[int, int] = {}
        for panel in dash["panels"]:
            pos = panel["gridPos"]
            rows[pos["y"]] = rows.get(pos["y"], 0) + pos["w"]
        assert set(rows.values()) == {24}, f"{name}: wiersze o szerokości {rows}"


def test_heatmap_uses_one_value_scale_and_its_own_time_range():
    """K7-V1: wspólna skala 0–100% dla wszystkich komórek, ciągły schemat kolorów, własny zakres czasu."""
    panel = next(p for (n, t), p in _panels().items() if t.startswith("Profil: godzina"))
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["color"] == {"mode": "continuous-GrYlRd"} and defaults["min"] == 0 and defaults["max"] == 100
    assert defaults["custom"]["cellOptions"]["type"] == "color-background"
    assert panel["timeFrom"] == "28d" and "28" in panel["title"]


def test_daily_panels_have_their_own_range():
    """K7-V2: doby zawsze widoczne, niezależnie od zakresu pulpitu."""
    for (name, title), panel in _panels().items():
        if title.startswith(("Zużycie na dobę", "Kontrola całki mocy")):
            assert panel["timeFrom"] == "14d", title


def test_in_progress_buckets_are_marked_and_not_counted_as_gaps():
    """K7-V3, V5, V6: wiaderko w toku liczone względem upłyniętej części; osie od zera; słupki od początku wiaderka."""
    panels = _panels()
    seconds = panels[("diagnostyka", "Sekundy bez pomiaru mocy na godzinę")]
    sql = seconds["targets"][0]["rawSql"]
    assert "least(now()" in sql and "Godzina w toku" in sql
    for key in (("energia", "Zużycie na minutę"), ("energia", "Zużycie na godzinę")):
        panel = panels[key]
        assert panel["fieldConfig"]["defaults"]["min"] == 0
        overrides = {o["matcher"]["options"]: o for o in panel["fieldConfig"]["overrides"]}
        assert any("w toku" in name or "bieżącej" in name for name in overrides)
        assert overrides["Pokrycie"]["properties"][4] == {"id": "min", "value": 0} or {"id": "min", "value": 0} in overrides["Pokrycie"]["properties"]
    hours = panels[("energia", "Zużycie na godzinę")]
    assert hours["fieldConfig"]["defaults"]["custom"]["barAlignment"] == 1


def test_empty_error_code_panel_has_a_time_field_and_a_friendly_message():
    """K7-V4: wiersz-wartownik daje pole czasu; komunikat „Brak błędów w zakresie”."""
    panel = _panels()[("diagnostyka", "Kod błędu komunikacji PLC–licznik (meter_error_code)")]
    assert "UNION ALL SELECT $__timeFrom()::timestamptz, NULL" in panel["targets"][0]["rawSql"]
    assert panel["fieldConfig"]["defaults"]["noValue"] == "Brak błędów w zakresie"


def test_units_titles_and_formats_are_readable():
    """K7-V7 (jednostka var), V8 (krótkie tytuły kafelków), V9 (data bez godziny), V10, V11, V13, V15."""
    panels = _panels()
    assert "reactivevoltamp" not in json_text()
    assert panels[("na-zywo", "Q")]["fieldConfig"]["defaults"]["unit"] == "suffix: var"
    for (name, title), panel in panels.items():
        if panel["type"] == "stat" and panel["gridPos"]["w"] <= 6:
            assert len(title) <= 28, f"{name}/{title}: tytuł kafelka może się obcinać"
    table = panels[("przeglad", "Zużycie dziś i wczoraj")]
    assert "to_char(day" in table["targets"][0]["rawSql"]
    assert [c for c in ("Z pomiarów", "Pokrycie", "Ekstrapolacja", "Licznik") if c in table["targets"][0]["rawSql"]] == [
        "Z pomiarów", "Pokrycie", "Ekstrapolacja", "Licznik"]
    pf = panels[("na-zywo", "Współczynnik mocy PF")]["fieldConfig"]["defaults"]
    assert pf["min"] == 0 and pf["max"] == 1
    assert ("jakosc", "Współczynnik mocy (cos φ)") in panels and ("jakosc", "Stosunek mocy biernej do czynnej (Q/P)") in panels
    assert panels[("jakosc", "Odchyłka częstotliwości od znamionowej")]["fieldConfig"]["defaults"]["unit"] == "suffix: Hz"
    assert "date_trunc('minute', now())" in panels[("diagnostyka", "Wiersze na minutę w bazie")]["targets"][0]["rawSql"]


def test_line_panels_have_no_fill_so_bands_do_not_tint_the_chart():
    """K7-V11, V12: tła i wypełnienia usunięte; granice pasma jako czerwone przerywane linie."""
    for (name, title), panel in _panels().items():
        if panel["type"] == "timeseries" and panel["fieldConfig"]["defaults"]["custom"]["drawStyle"] == "line":
            assert panel["fieldConfig"]["defaults"]["custom"]["fillOpacity"] == 0, f"{name}/{title}"
    voltage = _panels()[("jakosc", "Napięcie (min, średnia, maks.)")]
    assert voltage["fieldConfig"]["overrides"][0]["properties"][1]["value"]["fixedColor"] == "red"


def json_text() -> str:
    import json

    return json.dumps(dashboards())
