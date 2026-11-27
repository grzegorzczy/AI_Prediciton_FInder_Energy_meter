"""Generator dashboardów (G7-b): zgodność JSON w repo, kody statusów z dokumentu, zasada 8, opisy paneli."""
from __future__ import annotations

import json
import re

from collector.status import ERROR_CODE_NAMES, LinkStatus, MeterStatus
from grafana_support import dashboards, load_generator, targets

FORBIDDEN = re.compile(r"przewidywani\w* awari|predykcj\w* awari|predict", re.IGNORECASE)


def test_json_in_repo_equals_generator_output():
    generator = load_generator()
    for name, text in generator.render().items():
        assert (generator.OUT / f"{name}.json").read_text(encoding="utf-8") == text, f"{name}.json różni się od generatora"


def test_seven_dashboards_with_stable_uids_and_device_variables():
    dashes = dashboards()
    assert {d["uid"] for d in dashes.values()} == {"aip-przeglad", "aip-na-zywo", "aip-jakosc", "aip-energia", "aip-diagnostyka",
                                                   "aip-flota", "aip-pompa"}
    for name, dash in dashes.items():
        names = [v["name"] for v in dash["templating"]["list"]]
        assert names[0] == {"flota": "stale_s", "pompa": "pump"}.get(name, "device"), name
        assert len(dash["links"]) == 7, name
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
    assert defaults["color"]["mode"] == "continuous-blues" and defaults["min"] == 0 and defaults["max"] == 100
    assert defaults["custom"]["cellOptions"]["type"] == "color-background"
    assert "28" in panel["title"]


def test_panels_with_their_own_range_do_not_depend_on_the_dashboard_range():
    """K7C-V1 (k7d): własny zakres liczony w SQL od „teraz”. Nadpisanie `timeFrom` Grafana ignoruje przy bezwzględnym zakresie pulpitu."""
    generator = load_generator()
    panels = _panels()
    assert set(generator.OWN_RANGE_PANELS) == {
        ("energia", "Zużycie na dobę (ostatnie 14d)"), ("energia", "Profil: godzina × dzień tygodnia (ostatnie 28d)"),
        ("energia", "Moc maks. profilu"), ("energia", "Kontrola całki mocy a licznik wzorcowy (doby, ostatnie 14d)"),
        ("energia", "Energia bierna na dobę: całka i licznik (ostatnie 14d)"), ("energia", "Moc bazowa (5. percentyl nocą, ostatnie 14 nocy)")}
    for key, marker in generator.OWN_RANGE_PANELS.items():
        panel = panels[key]
        for target in panel["targets"]:
            sql = target["rawSql"]
            assert generator.OWN_RANGE_MARKER[marker] in sql, key
            assert "$__timeFilter" not in sql and "$__timeFrom" not in sql and "$__timeTo" not in sql, f"{key}: zależy od zakresu pulpitu"
        assert "timeFrom" not in panel, f"{key}: nadpisanie timeFrom jest zawodne i zbędne"
        assert "niezależnie od zakresu pulpitu" in panel["description"], key
    assert panels[("energia", "Zużycie na dobę (ostatnie 14d)")]["type"] == "barchart"      # oś kategorii, nie czasu


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
    assert "UNION ALL SELECT $__timeFrom()::timestamptz, 0" in panel["targets"][0]["rawSql"]
    assert panel["fieldConfig"]["defaults"]["noValue"] == "Brak błędów w zakresie"


def test_units_titles_and_formats_are_readable():
    """K7-V7 (jednostka var), V8 (krótkie tytuły kafelków), V9 (data bez godziny), V10, V11, V13, V15."""
    panels = _panels()
    assert "reactivevoltamp" not in json_text()
    assert panels[("na-zywo", "Moc bierna Q")]["fieldConfig"]["defaults"]["unit"] == "suffix: var"
    for (name, title), panel in panels.items():
        if panel["type"] == "stat" and panel["gridPos"]["w"] <= 6:
            assert len(title) <= 28, f"{name}/{title}: tytuł kafelka może się obcinać"
    table = panels[("przeglad", "Zużycie dziś i wczoraj")]
    assert "to_char(day" in table["targets"][0]["rawSql"]
    assert [c for c in ("Z pomiarów", "Pokrycie", "Ekstrapolacja", "Licznik") if c in table["targets"][0]["rawSql"]] == [
        "Z pomiarów", "Pokrycie", "Ekstrapolacja", "Licznik"]
    pf = panels[("na-zywo", "Współczynnik mocy PF")]["fieldConfig"]["defaults"]
    assert pf["min"] == 0 and pf["max"] == 1
    assert ("jakosc", "Współczynnik mocy PF") in panels and ("jakosc", "Stosunek mocy biernej do czynnej (Q/P)") in panels
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


# --- k7c: W-1…W-9 ---------------------------------------------------------------------------------------------------------

def test_heatmap_is_single_hue_and_missing_cells_are_transparent():
    """W-1: skala sekwencyjna (bez zieleni i czerwieni), brak danych = przezroczysta komórka bez liczby."""
    panel = next(p for (n, t), p in _panels().items() if t.startswith("Profil: godzina"))
    defaults = panel["fieldConfig"]["defaults"]
    assert defaults["color"]["mode"] == "continuous-blues"
    special = defaults["mappings"][0]
    assert special["type"] == "special" and special["options"]["match"] == "null+nan"
    assert special["options"]["result"]["text"] == "" and special["options"]["result"]["color"] == "transparent"


def test_error_code_panel_shows_codes_only_during_errors_with_distinct_colours():
    """W-2: poza błędem „Brak błędu”, trzy kody w trzech kolorach."""
    panel = _panels()[("diagnostyka", "Kod błędu komunikacji PLC–licznik (meter_error_code)")]
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options["0"]["text"] == "Brak błędu" and options["0"]["color"] == "green"
    colours = {options[c]["color"] for c in ("161", "162", "163")}
    assert len(colours) == 3
    sql = panel["targets"][0]["rawSql"]
    assert "interval '1 second', 0" in sql and "$__timeFrom()::timestamptz, 0" in sql


def test_incomplete_minute_is_not_drawn_in_the_energy_line_and_coverage_series_are_named_alike():
    """W-3, W-4: jedna nazwa i definicja pokrycia upłynionej części dla minuty, godziny i doby."""
    generator = load_generator()
    for key in (("energia", "Zużycie na minutę"), ("energia", "Zużycie na godzinę")):
        panel = _panels()[key]
        assert generator.PART in panel["targets"][0]["rawSql"] and generator.PART in panel["description"], key
    daily = _panels()[("energia", "Zużycie na dobę (ostatnie 14d)")]        # doba: pokrycie w etykiecie słupka
    assert "w toku" in daily["targets"][0]["rawSql"] and generator.PART.lower() in daily["description"]
    minute = _panels()[("energia", "Zużycie na minutę")]
    assert "THEN active_power_sum" in minute["targets"][0]["rawSql"]          # energia tylko dla pełnych minut
    assert minute["fieldConfig"]["defaults"]["unit"] == "suffix: Wh"           # bez mieszania mWh i Wh
    assert "Pokrycie doby" in _panels()[("przeglad", "Zużycie dziś i wczoraj")]["targets"][0]["rawSql"]


def test_k7c_formatting_fixes():
    """W-5 (decimals 2), W-6 (słupki), W-7 (krótkie nagłówki), W-8 (wysokość), W-9 (kolor i zapas osi pasm)."""
    panels = _panels()
    for key in (("energia", "Moc: bieżący zakres a poprzednia doba"), ("energia", "Moc: bieżący zakres a poprzedni tydzień"),
                ("energia", "Moc bazowa (5. percentyl nocą, ostatnie 14 nocy)")):
        assert panels[key]["fieldConfig"]["defaults"]["decimals"] == 2, key
    assert panels[("energia", "Moc bazowa (5. percentyl nocą, ostatnie 14 nocy)")]["type"] == "barchart"             # K8-V6: oś kategorii (nocy), nie czasu pulpitu
    control = next(p for (n, t), p in panels.items() if t.startswith("Kontrola całki mocy"))
    for header in ("Licznik [Wh]", "Ekstrap. [Wh]", "W rozdz.", "Rozdz. [Wh]", "Luki"):
        assert header in control["targets"][0]["rawSql"]
    assert panels[("na-zywo", "Wartości w oknie")]["gridPos"]["h"] >= 14
    assert panels[("jakosc", "Poza pasmem U [min]")] and panels[("energia", "Moc maks. profilu")]["gridPos"]["w"] >= 6
    for key, band in ((("jakosc", "Napięcie (min, średnia, maks.)"), "granica pasma"), (("jakosc", "Odchyłka częstotliwości od znamionowej"), "granica")):
        panel = panels[key]
        overrides = {o["matcher"]["options"]: {p["id"]: p["value"] for p in o["properties"]} for o in panel["fieldConfig"]["overrides"]}
        band_props = next(v for k, v in overrides.items() if k.startswith(".*") and band in k)
        assert band_props["color"]["fixedColor"] == "red" and band_props["custom.lineWidth"] == 2
        hidden = overrides["Zakres osi.*"]
        assert hidden["custom.hideFrom"] == {"legend": True, "tooltip": True, "viz": False} and hidden["custom.lineWidth"] == 0
        assert "Zakres osi (góra)" in panel["targets"][0]["rawSql"] and "Zakres osi (dół)" in panel["targets"][0]["rawSql"]


# --- E2-PLC2, krok 2: panele mapy v2 ---------------------------------------------------------------------------------------

V2_PANELS = [
    ("na-zywo", "THD napięcia"), ("na-zywo", "THD prądu"), ("na-zywo", "Kąt U–I"), ("na-zywo", "Temperatura licznika"),
    ("na-zywo", "THD napięcia (THD U)"), ("na-zywo", "THD prądu (THD I)"),
    ("jakosc", "THD napięcia (THD U)"), ("jakosc", "THD prądu (THD I)"), ("jakosc", "Kąt U–I"),
    ("diagnostyka", "Temperatura licznika"), ("diagnostyka", "Temperatura licznika [°C]"),
    ("diagnostyka", "Czas pracy licznika"), ("diagnostyka", "Czas pracy licznika [dni]"),
]


def test_v2_panels_exist_and_show_no_data_before_v2_instead_of_zero():
    """Brak wartości przed mapą v2 = brak danych: zapytania bez COALESCE i filtr po liczności, komunikat dla pustych paneli."""
    panels = _panels()
    for key in V2_PANELS:
        panel = panels[key]
        assert panel["fieldConfig"]["defaults"].get("noValue") == "Brak danych (mapa v1)", key
        for target in panel["targets"]:
            assert "COALESCE" not in target["rawSql"].upper(), key
    for key in (("jakosc", "THD napięcia (THD U)"), ("jakosc", "THD prądu (THD I)"), ("jakosc", "Kąt U–I"), ("diagnostyka", "Temperatura licznika [°C]")):
        assert "_n > 0" in panels[key]["targets"][0]["rawSql"], key


def test_pf_panel_has_the_cos_phi_series_and_explains_the_difference():
    panel = _panels()[("jakosc", "Współczynnik mocy PF")]
    assert "phase_cos_sum" in panel["targets"][1]["rawSql"] and 'AS "cos φ"' in panel["targets"][1]["rawSql"]
    assert "PF = cos φ / √(1 + THD_I²)" in panel["description"] and "0,37" in panel["description"] and "0,64" in panel["description"]


def test_angle_description_states_only_what_was_measured():
    """U-1 z review: bez ogólnego „ujemny = pojemnościowy” jako cechy licznika."""
    for key in (("jakosc", "Kąt U–I"), ("na-zywo", "Kąt U–I")):
        description = _panels()[key]["description"]
        assert "Q < 0" in description and "25.11.2026" in description and "nie jest potwierdzona" in description
        assert "ujemny = pojemnościowy" not in description


def test_thd_current_has_no_thresholds_and_warns_about_small_current():
    panel = _panels()[("jakosc", "THD prądu (THD I)")]
    assert "niepewna" in panel["description"] and "thresholds" not in panel["fieldConfig"]["defaults"]
    assert "thresholds" not in _panels()[("diagnostyka", "Temperatura licznika")]["fieldConfig"]["defaults"]


def test_reactive_energy_panels_describe_the_resolution_and_use_the_view():
    panels = _panels()
    hourly = panels[("energia", "Energia bierna z mocy (całka Q, godziny)")]
    daily = panels[("energia", "Energia bierna na dobę: całka i licznik (ostatnie 14d)")]
    # panele czytają agregat godzinny wprost (widok reactive_1h_calc zostaje dla analityki): zapytania bez przeglądania całej historii
    assert "energy_ext_1h" in hourly["targets"][0]["rawSql"] and "energy_ext_1h" in daily["targets"][0]["rawSql"]
    assert "reactive_1h_calc" not in hourly["targets"][0]["rawSql"] and "reactive_1h_calc" not in daily["targets"][0]["rawSql"]
    assert "interval '17 days'" in daily["targets"][0]["rawSql"]                    # zapas 3 dni na poprzednie wiaderko licznika
    assert "100 varh" in daily["description"] and "11 godzin" in daily["description"] and "Q < 0" in daily["description"]
    assert daily["type"] == "barchart"


def test_rows_per_minute_description_uses_the_v2_model():
    description = _panels()[("diagnostyka", "Wiersze na minutę w bazie")]["description"]
    assert "13 wierszy na sekundę przy mapie v1" in description and "20 przy mapie v2" in description and "1 200 na minutę" in description


# --- k8c: K8-V1 (oś stanów po luce), K8-V2 (pełne nazwy kafelków), K8-V3 (tabela bez przewijania) ------------------------------

LIVE_TILE_TITLES = ["Napięcie U", "Prąd I", "Moc czynna P", "Moc bierna Q", "Moc pozorna S", "Współczynnik mocy PF", "Częstotliwość f",
                    "THD napięcia", "THD prądu", "Kąt U–I", "Temperatura licznika"]


def test_live_tiles_have_full_names_and_fit_their_width():
    """K8-V2: tytuły kafelków to pełne nazwy z symbolem; długość mieści się w najwęższym kafelku (3 z 24 kolumn)."""
    dash = dashboards()["na-zywo"]
    tiles = [p for p in dash["panels"] if p["type"] == "stat"]
    assert [p["title"] for p in tiles] == LIVE_TILE_TITLES
    for tile in tiles:
        width_cols = tile["gridPos"]["w"]
        assert len(tile["title"]) <= 4 + width_cols * 6, f"{tile['title']}: za długi dla {width_cols} kolumn"


def test_live_values_table_height_fits_all_rows_without_scrolling():
    """K8-V3: wysokość panelu dobrana do liczby wierszy (nagłówek + wiersze po 36 px + tytuł i marginesy)."""
    import re

    panel = _panels()[("na-zywo", "Wartości w oknie")]
    sql = panel["targets"][0]["rawSql"]
    metrics = re.search(r"metric IN \(([^)]*)\)", sql).group(1).split(",")
    needed_px = (len(metrics) + 1) * 36 + 56
    height_px = panel["gridPos"]["h"] * 30 + (panel["gridPos"]["h"] - 1) * 8
    assert len(metrics) == 11 and height_px >= needed_px, (len(metrics), height_px, needed_px)


def test_state_timeline_query_returns_to_the_state_after_a_gap():
    """K8-V1: wiersz stanu także dla pierwszego wiersza po luce, gdy wartość się nie zmieniła (0 -> 0)."""
    for title in ("Łącze z PLC (link_status)", "Stan licznika (meter_status)"):
        sql = _panels()[("diagnostyka", title)]["targets"][0]["rawSql"]
        assert "time - prev_time > make_interval(secs => $stale_s)" in sql and "prev IS DISTINCT FROM value" in sql, title


# --- k8c: K8-V5 (etykiety osi energii biernej), K8-V6 (moc bazowa z własnym zakresem), K8-V7 (profil bez przewijania) ------------

def test_reactive_daily_axis_labels_are_text_and_the_meter_series_is_explained():
    """K8-V5: etykieta doby nie może wyglądać jak liczba („23.11” -> „23.1 varh”); opis wyjaśnia pustą serię licznika."""
    panel = _panels()[("energia", "Energia bierna na dobę: całka i licznik (ostatnie 14d)")]
    sql = panel["targets"][0]["rawSql"]
    assert "|| ' ' || CASE extract(isodow FROM day)" in sql and "to_char(day, 'DD.MM')" in sql
    assert "10:43 UTC" in panel["description"] and "n4" in panel["description"] and "pusta" in panel["description"]
    assert panel["fieldConfig"]["defaults"]["unit"] == "suffix: varh"                  # jednostka na osi wartości, nie kategorii


def test_base_power_is_a_barchart_over_the_last_nights_independent_of_the_dashboard_range():
    """K8-V6: tytuł z zakresem, SQL od „teraz”, etykiety tekstowe (dzień tygodnia)."""
    panel = _panels()[("energia", "Moc bazowa (5. percentyl nocą, ostatnie 14 nocy)")]
    sql = panel["targets"][0]["rawSql"]
    assert panel["type"] == "barchart" and "ostatnie 14 nocy" in panel["title"]
    assert "$__timeFilter" not in sql and "extract(hour FROM bucket AT TIME ZONE 'Europe/Warsaw') < 5" in sql
    assert "niezależnie od zakresu pulpitu" in panel["description"]


def test_profile_table_fits_all_seven_days_without_horizontal_scrolling():
    """K8-V7: wąskie kolumny (8 kolumn: godzina + 7 dni): minWidth <= 60 px, łącznie <= 480 px, mieści się w panelu 18 z 24 kolumn."""
    panel = next(p for (n, t), p in _panels().items() if t.startswith("Profil: godzina"))
    custom = panel["fieldConfig"]["defaults"]["custom"]
    assert custom["minWidth"] <= 60 and custom["minWidth"] * 8 <= 480
    sql = panel["targets"][0]["rawSql"]
    assert all(f'AS "{name}"' in sql for name in ("Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"))


# --- E3-k6: Flota i Pompa ------------------------------------------------------------------------------------------------------

# Odcisk paneli, zmiennych (bez $device) i adnotacji dashboardów etapu 2 przed k6 (8228332): k6 zmienia w nich tylko etykietę
# listy $device i linki nawigacji (K6-U2), więc zapytania i wyniki dla Findera i PLC są bez zmian.
STAGE2_FINGERPRINTS = {"diagnostyka": "59a7368a9320a257", "energia": "6ac7c100119b5267", "jakosc": "da5fcdfc957c9cf5",
                       "na-zywo": "61940a61fe0b3388", "przeglad": "6f944b96e088e60e"}


def test_stage2_dashboards_change_only_the_device_label_and_links():
    import hashlib
    import json

    generator = load_generator()
    for name, expected in STAGE2_FINGERPRINTS.items():
        dash = dashboards()[name]
        rest = [v for v in dash["templating"]["list"] if v["name"] != "device"]
        digest = hashlib.sha256(json.dumps([dash["panels"], rest, dash["annotations"]], sort_keys=True, ensure_ascii=False)
                                .encode()).hexdigest()[:16]
        assert digest == expected, f"{name}: zmieniły się panele etapu 2"
        device = dash["templating"]["list"][0]
        assert device["query"].startswith("SELECT device_id AS __value, " + generator.SIM_LABEL + " AS __text"), name


def test_simulation_mark_comes_from_the_source_column_not_from_device_names():
    """S10, zasada 3: dopisek SYMULACJA tylko z devices.source; generator nie zna żadnych identyfikatorów ani nazw urządzeń."""
    generator = load_generator()
    text = (generator.ROOT / "generate.py").read_text(encoding="utf-8")
    for word in ("sim_", "finder", "Pasteryzator", "P-101", "Pompa P"):
        assert word not in text, word
    assert "source = 'sim'" in generator.SIM_LABEL
    for name in ("flota", "pompa"):
        dash = dashboards()[name]
        assert dash["panels"][0]["type"] == "text" and generator.SIM_MARK in dash["panels"][0]["options"]["content"]
    fleet = dashboards()["flota"]
    for title, target in targets(fleet):
        if "metric" in target["rawSql"] or "Urządzenie" in target["rawSql"]:
            assert "d.source = 'sim'" in target["rawSql"], title


def test_pump_panels_use_the_minute_aggregate_and_running_minutes_for_vibration():
    generator = load_generator()
    pump = dashboards()["pompa"]
    for title, target in targets(pump):
        sql = target["rawSql"]
        assert "FROM pump_1m_calc" in sql and "measurements" not in sql, title
        assert "'$pump'" in sql, title
        if "vibration" in sql:
            assert "running" in sql, f"{title}: drgania tylko z minut pracy (K4-D2)"
    trend = next(p for p in pump["panels"] if p["title"].startswith("Trend drgań"))
    sql = trend["targets"][0]["rawSql"]
    assert generator.TREND_MARKER in sql and "$__timeFilter" not in sql and "niezależnie od zakresu pulpitu" in trend["description"]
    for panel in pump["panels"]:
        assert not re.search(r"prognoz|dni do|threshold", json.dumps(panel["fieldConfig"]) + panel["title"], re.I) or panel["type"] == "text"


def test_fleet_long_ranges_read_aggregates():
    for title, target in targets(dashboards()["flota"]):
        sql = target["rawSql"]
        if "FROM measurements" in sql:
            assert "interval '1 hour'" in sql and "$__timeFilter" not in sql, f"{title}: surowe dane tylko z ostatniej godziny"
