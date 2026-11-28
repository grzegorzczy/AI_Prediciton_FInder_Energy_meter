#!/usr/bin/env python3
"""Generuje grafana/dashboards/*.json (G7-b). Źródło prawdy: ten plik + docs/status-codes.md (kody i komunikaty).

Użycie:  python grafana/generate.py            zapisuje pliki
         python grafana/generate.py --check    kończy kodem 1, gdy pliki w repo różnią się od wyniku generatora

Zasady (docs/handoff/e2-k7-plan.md): źródło danych wyłącznie app_reader; długie zakresy z energy_1m / energy_1h;
progi jakości jako zmienne dashboardu; brak "przewidywania awarii" w nazwach (zasada 8); wykresy nie łączą punktów
przez luki dłuższe niż próg (spanNulls jako próg w ms); brak danych nie jest zerem.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OUT = ROOT / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "aip-timescaledb"}
FOLDER_TAG = "AI Predykcja"

# --- wspólne stałe (jedno miejsce) ------------------------------------------------------------------------------------
DEFAULTS = {"u_nom": "230", "u_band_pct": "10", "f_nom": "50", "f_band_hz": "0.2", "stale_s": "10"}
TZ = "Europe/Warsaw"
LOCAL_MIDNIGHT = f"(date_trunc('day', now() AT TIME ZONE '{TZ}') AT TIME ZONE '{TZ}')"
PLC = "(SELECT device_id FROM devices WHERE kind = 'plc' ORDER BY device_id LIMIT 1)"
DEV = "device_id = '$device'"
POLL = "(SELECT (meta ->> 'poll_interval_s')::float8 FROM devices WHERE device_id = '$device')"
STALE = "make_interval(secs => $stale_s)"
SPAN_GUARD_7D = "($__timeTo()::timestamptz - $__timeFrom()::timestamptz) <= interval '7 days'"
NO_DATA_CODE = 100          # sztuczny stan "brak danych" (luka w danych lub dane starsze niż $stale_s)
NO_METER_CODE = 101         # PLC działa, ale licznik nie ma świeżego statusu

# Etykieta urządzenia z dopiskiem SYMULACJA wyliczanym z devices.source (S10): żadnych nazw urządzeń w generatorze (zasada 3).
SIM_MARK = "SYMULACJA"
SIM_LABEL = f"name || CASE WHEN source = 'sim' THEN ' ({SIM_MARK})' ELSE '' END"
SIM_BANNER = (f"**„{SIM_MARK}” = dane z symulatora**, nie pomiar z maszyny (`source = sim`). "
              "Urządzenia bez dopisku to pomiary prawdziwe.")          # 1 linia bez przewijania (K6R-V4)

ANNOTATION_SQL = (
    'SELECT start_time AS time, end_time AS "timeEnd", kind AS tags, description AS text FROM data_windows '
    "WHERE start_time <= $__timeTo() AND end_time >= $__timeFrom() ORDER BY start_time"
)


# --- kody statusów z docs/status-codes.md ---------------------------------------------------------------------------------

def _table_rows(text: str, marker: str) -> list[list[str]]:
    start = text.index(marker)
    end = text.find("\n## ", start + 1)
    block = text[start:end if end != -1 else None]
    rows = []
    for line in block.splitlines():
        if line.startswith("|") and not set(line.replace("|", "").strip()) <= set("- "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0].isdigit():
                rows.append(cells)
    return rows


def load_status_codes() -> dict:
    text = (REPO / "docs" / "status-codes.md").read_text(encoding="utf-8")
    link = {int(r[0]): r[3] for r in _table_rows(text, "## `link_status`")}
    meter = {int(r[0]): r[3] for r in _table_rows(text, "## `meter_status`")}
    errors = {int(r[0]): r[2].strip("`") for r in _table_rows(text, "## `meter_error_code`")}
    return {"link": link, "meter": meter, "errors": errors}


CODES = load_status_codes()
COLORS = {0: "green", 1: "red", 2: "orange", 3: "purple", 10: "purple"}


def mapping(codes: dict[int, str], extra: dict[int, tuple[str, str]] | None = None) -> list[dict]:
    options = {}
    for i, (code, text) in enumerate(sorted(codes.items())):
        options[str(code)] = {"text": text, "color": COLORS.get(code, "blue"), "index": i}
    for j, (code, (text, color)) in enumerate(sorted((extra or {}).items())):
        options[str(code)] = {"text": text, "color": color, "index": len(codes) + j}
    return [{"type": "value", "options": options}]


LINK_MAP = mapping(CODES["link"], {NO_DATA_CODE: ("Brak danych", "text")})
METER_MAP = mapping(CODES["meter"], {NO_DATA_CODE: ("Brak danych", "text")})
TILE_MAP = mapping({**CODES["meter"], NO_DATA_CODE: "Brak danych z PLC", NO_METER_CODE: "Brak danych z licznika"},
                   None)
TILE_MAP[0]["options"][str(NO_DATA_CODE)]["color"] = "red"
TILE_MAP[0]["options"][str(NO_METER_CODE)]["color"] = "orange"
ERROR_COLORS = {161: "orange", 162: "red", 163: "purple"}          # każdy kod inny kolor (K7c W-2)
ERROR_MAP = mapping({c: f"{c} {n}" for c, n in CODES["errors"].items()}, {0: ("Brak błędu", "green")})
for _code, _color in ERROR_COLORS.items():
    ERROR_MAP[0]["options"][str(_code)]["color"] = _color


# --- budowanie paneli -------------------------------------------------------------------------------------------------------

class Dash:
    def __init__(self, uid: str, title: str, description: str, refresh: str = "", time_from: str = "now-24h"):
        self.uid, self.title, self.description = uid, title, description
        self.refresh, self.time_from = refresh, time_from
        self.panels: list[dict] = []
        self.variables: list[dict] = []
        self.links: list[dict] = []
        self._id = 0
        self._row_y = 0
        self._row_x = 0
        self._row_h = 0

    def add(self, panel: dict, w: int, h: int, new_row: bool = False) -> dict:
        if new_row or self._row_x + w > 24:
            self._row_y += self._row_h
            self._row_x, self._row_h = 0, 0
        self._id += 1
        panel["id"] = self._id
        panel["gridPos"] = {"x": self._row_x, "y": self._row_y, "w": w, "h": h}
        self._row_x += w
        self._row_h = max(self._row_h, h)
        self.panels.append(panel)
        return panel

    def json(self) -> dict:
        return {
            "uid": self.uid, "title": self.title, "description": self.description, "tags": [FOLDER_TAG],
            "timezone": TZ, "schemaVersion": 39, "version": 1, "editable": True, "graphTooltip": 1,
            "refresh": self.refresh, "time": {"from": self.time_from, "to": "now"},
            "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
            "templating": {"list": self.variables}, "links": self.links,
            "annotations": {"list": [{
                "name": "Okna testów i przerw", "enable": True, "iconColor": "rgba(255, 152, 48, 0.6)",
                "datasource": DS, "target": {"refId": "Anno", "datasource": DS, "editorMode": "code",
                                              "format": "table", "rawQuery": True, "rawSql": ANNOTATION_SQL}}]},
            "panels": self.panels,
        }


def target(sql: str, fmt: str = "time_series", ref: str = "A", hide: bool = False) -> dict:
    return {"refId": ref, "datasource": DS, "editorMode": "code", "format": fmt, "rawQuery": True,
            "rawSql": " ".join(sql.split()), "hide": hide}


def _panel(kind: str, title: str, description: str, targets: list[dict], unit: str = "", options: dict | None = None,
           custom: dict | None = None, mappings: list | None = None, thresholds: list | None = None,
           overrides: list | None = None, decimals: int | None = None, min_: float | None = None,
           max_: float | None = None, transformations: list | None = None, time_from: str | None = None,
           no_value: str | None = None) -> dict:
    defaults: dict = {"unit": unit, "color": {"mode": "palette-classic"}}
    if mappings:
        defaults["mappings"] = mappings
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
    if decimals is not None:
        defaults["decimals"] = decimals
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_
    if custom:
        defaults["custom"] = custom
    panel = {"type": kind, "title": title, "description": description, "datasource": DS, "targets": targets,
             "fieldConfig": {"defaults": defaults, "overrides": overrides or []}, "options": options or {}}
    if transformations:
        panel["transformations"] = transformations
    if time_from:                       # własny zakres czasu panelu, niezależny od pulpitu (K7-V1, V2)
        panel["timeFrom"] = time_from
        panel["hideTimeOverride"] = False
    if no_value is not None:
        panel["fieldConfig"]["defaults"]["noValue"] = no_value
    return panel


def timeseries(title, description, targets, unit="", span_ms=5000, bars=False, **kw):
    # Linie bez wypełnienia (K7-V11, V12: wypełnienia i tła nic nie znaczyły); słupki wyrównane do POCZĄTKU wiaderka (K7-V5)
    custom = {"lineWidth": 1, "fillOpacity": 60 if bars else 0, "showPoints": "never", "spanNulls": span_ms,
              "drawStyle": "bars" if bars else "line", "barAlignment": 1 if bars else 0}
    options = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
               "tooltip": {"mode": "multi", "sort": "none"}}
    return _panel("timeseries", title, description, targets, unit, options=options, custom=custom, **kw)


def stat(title, description, targets, unit="", calc="lastNotNull", color_mode="value", **kw):
    options = {"reduceOptions": {"calcs": [calc], "fields": "", "values": False}, "colorMode": color_mode,
               "graphMode": "none", "textMode": "auto", "justifyMode": "center"}
    return _panel("stat", title, description, targets, unit, options=options, **kw)


def table(title, description, targets, **kw):
    return _panel("table", title, description, targets, options={"showHeader": True, "cellHeight": "sm"}, **kw)


def state_timeline(title, description, targets, mappings, **kw):
    options = {"mergeValues": True, "showValue": "auto", "alignValue": "left", "rowHeight": 0.8,
               "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
               "tooltip": {"mode": "single"}}
    return _panel("state-timeline", title, description, targets, mappings=mappings, options=options,
                  custom={"fillOpacity": 85, "lineWidth": 0}, **kw)


def barchart(title, description, targets, unit="", **kw):
    options = {"orientation": "vertical", "xTickLabelRotation": -45, "showValue": "never", "stacking": "none",
               "legend": {"showLegend": False}, "tooltip": {"mode": "single"}}
    return _panel("barchart", title, description, targets, unit, options=options, custom={"fillOpacity": 80}, **kw)


def variables(*names: str) -> list[dict]:
    labels = {
        "u_nom": "Napięcie znamionowe [V]", "u_band_pct": "Pasmo napięcia [± %] (orientacyjne)",
        "f_nom": "Częstotliwość znamionowa [Hz]", "f_band_hz": "Pasmo częstotliwości [± Hz]",
        "stale_s": "Dane uznane za stare po [s]",
    }
    out = [device_variable("device", "Licznik", "energy_meter")]
    for name in names:
        out.append(textbox(name, labels[name]))
    return out


def device_variable(name: str, label: str, kind: str) -> dict:
    """Lista urządzeń danego rodzaju; etykieta z dopiskiem SYMULACJA z devices.source (S10, K6-U2: wartość = device_id bez zmian)."""
    sql = f"SELECT device_id AS __value, {SIM_LABEL} AS __text FROM devices WHERE kind = '{kind}' AND enabled ORDER BY 1"
    return {"type": "query", "name": name, "label": label, "datasource": DS, "refresh": 1, "sort": 1,
            "multi": False, "includeAll": False, "hide": 0, "query": sql, "definition": sql, "current": {}}


def textbox(name: str, label: str) -> dict:
    return {"type": "textbox", "name": name, "label": label, "query": DEFAULTS[name],
            "current": {"text": DEFAULTS[name], "value": DEFAULTS[name]}, "hide": 0,
            "options": [{"selected": True, "text": DEFAULTS[name], "value": DEFAULTS[name]}]}


def nav_links() -> list[dict]:
    items = [("Przegląd", "aip-przeglad"), ("Licznik na żywo", "aip-na-zywo"), ("Jakość energii", "aip-jakosc"),
             ("Energia i profil", "aip-energia"), ("Stan i diagnostyka", "aip-diagnostyka"), ("Flota", "aip-flota"),
             ("Pompa", "aip-pompa")]
    return [{"type": "link", "title": title, "url": f"/d/{uid}", "icon": "dashboard", "includeVars": True,
             "keepTime": True, "targetBlank": False, "asDropdown": False} for title, uid in items]


def new_dash(uid, title, description, *var_names, refresh="", time_from="now-24h") -> Dash:
    d = Dash(uid, title, description, refresh, time_from)
    d.variables = variables(*var_names)
    d.links = nav_links()
    return d


# --- 1. Przegląd -------------------------------------------------------------------------------------------------------------

COVERAGE_AXIS = {"id": "custom.axisPlacement", "value": "right"}


def coverage_override(name: str, dashed: bool = False, style: str = "line") -> dict:
    props = [{"id": "unit", "value": "percentunit"}, COVERAGE_AXIS, {"id": "custom.drawStyle", "value": style},
             {"id": "min", "value": 0}, {"id": "max", "value": 1}, {"id": "custom.fillOpacity", "value": 0}]
    if dashed:
        props.append({"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 6]}})
        props.append({"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}})
    else:
        props.append({"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}})
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def overview() -> Dash:
    d = new_dash("aip-przeglad", "Przegląd",
                 "Strona startowa: stan, bieżąca moc i zużycie dziś i wczoraj. Wartości „dziś” liczone od północy czasu lokalnego "
                 "(Europe/Warsaw), niezależnie od wybranego zakresu czasu.", "stale_s", refresh="30s", time_from="now-6h")
    link_age = (f"SELECT time, value FROM measurements WHERE device_id = {PLC} AND metric = 'link_status' "
                "AND time > now() - interval '1 hour' ORDER BY time DESC LIMIT 1")
    meter_age = (f"SELECT time, value FROM measurements WHERE {DEV} AND metric = 'meter_status' "
                 "AND time > now() - interval '1 hour' ORDER BY time DESC LIMIT 1")
    tile_sql = (f"WITH l AS ({link_age}), m AS ({meter_age}) SELECT now() AS time, CASE "
                f"WHEN l.time IS NULL OR now() - l.time > {STALE} OR l.value <> 0 THEN {NO_DATA_CODE} "
                f"WHEN m.time IS NULL OR now() - m.time > {STALE} THEN {NO_METER_CODE} ELSE m.value END AS \"Stan licznika\" "
                "FROM (SELECT 1) x LEFT JOIN l ON true LEFT JOIN m ON true")
    plc_sql = (f"WITH l AS ({link_age}) SELECT now() AS time, CASE WHEN l.time IS NULL OR now() - l.time > {STALE} "
               f"THEN {NO_DATA_CODE} ELSE l.value END AS \"Stan PLC\" FROM (SELECT 1) x LEFT JOIN l ON true")
    d.add(stat("Stan licznika",
               "Stan licznika uwzględniający łącze z PLC (K3-U3): „Brak danych z PLC”, gdy link_status ≠ 0 albo ostatni wpis link_status "
               "jest starszy niż próg ze zmiennej „Dane uznane za stare po”; „Brak danych z licznika”, gdy ostatni meter_status jest "
               "starszy niż ten próg; w pozostałych przypadkach nazwa stanu z docs/status-codes.md.",
               [target(tile_sql, "table")], mappings=TILE_MAP, color_mode="background",
               thresholds=[{"color": "green", "value": None}]), 6, 4)
    d.add(stat("Stan PLC", "Stan łącza z PLC (link_status). „Brak danych”: ostatni wpis starszy niż próg ze zmiennej „Dane uznane za stare po”.",
               [target(plc_sql, "table")], mappings=LINK_MAP, color_mode="background",
               thresholds=[{"color": "green", "value": None}]), 6, 4)
    d.add(stat("Moc czynna teraz",
               "Ostatnia zmierzona moc czynna P [W] z ostatnich 10 minut (średnia moc pobierana z sieci).",
               [target(f"SELECT time, value AS \"Moc czynna\" FROM measurements WHERE {DEV} AND metric = 'active_power' "
                       "AND time > now() - interval '10 minutes' ORDER BY time", "time_series")], unit="watt", decimals=1), 6, 4)
    d.add(stat("Wiek ostatniego odczytu",
               "Ile sekund minęło od ostatniego pomiaru tego licznika w bazie. Powyżej progu „Dane uznane za stare po” oznacza brak świeżych danych.",
               [target(f"SELECT now() AS time, extract(epoch FROM now() - max(time)) AS \"Wiek odczytu\" FROM measurements "
                       f"WHERE {DEV} AND time > now() - interval '1 hour'", "table")], unit="s", decimals=0,
               thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 10}, {"color": "red", "value": 60}]), 6, 4)

    day = "(now() AT TIME ZONE 'Europe/Warsaw')::date"
    d.add(stat("Zużycie dziś",
               "Energia czynna z pomiarów od północy (czas lokalny): całka mocy, czyli suma mocy z obecnych próbek × okres próbkowania. Przy pokryciu poniżej 100% to dolna granica "
               "(luki nie są interpolowane). Pokrycie i szacunek pełnej doby w tabeli obok.",
               [target(f"SELECT now() AS time, integral_wh AS \"Energia\" FROM energy_daily_check WHERE {DEV} AND day = {day}", "table")],
               unit="watth", decimals=1), 4, 5, new_row=True)
    d.add(stat("Zużycie wczoraj", "Energia czynna z pomiarów za poprzednią dobę (czas lokalny), jak obok. Dolna granica przy pokryciu poniżej 100%.",
               [target(f"SELECT now() AS time, integral_wh AS \"Energia\" FROM energy_daily_check WHERE {DEV} AND day = {day} - 1", "table")],
               unit="watth", decimals=1), 4, 5)
    d.add(table("Zużycie dziś i wczoraj",
                "Zawsze dwie ostatnie doby lokalne, niezależnie od zakresu czasu. Z pomiarów [Wh]: energia z całki mocy (dolna granica). Pokrycie doby: część CAŁEJ doby z pomiarem mocy (dla bieżącej doby "
                "także godziny, które jeszcze nie nastąpiły; kafelek „Pokrycie danych od północy” liczy tylko upłynioną część). Ekstrapolacja [Wh]: energia / pokrycie, tylko przy pokryciu ≥ 50%. Licznik [Wh]: przyrost licznika wzorcowego "
                "(kwantyzacja 100 Wh, więc informacyjnie). Zakończona: doba już się skończyła.",
                [target(f"SELECT to_char(day, 'YYYY-MM-DD') AS \"Doba\", integral_wh AS \"Z pomiarów\", coverage AS \"Pokrycie doby\", "
                        f"integral_extrapolated_wh AS \"Ekstrapolacja\", counter_delta_wh AS \"Licznik\", "
                        f"day_complete AS \"Zakończona\" FROM energy_daily_check WHERE {DEV} AND day >= {day} - 1 ORDER BY day DESC",
                        "table")],
                decimals=0,
                custom={"minWidth": 50, "align": "right"},
                overrides=[{"matcher": {"id": "byName", "options": "Pokrycie doby"}, "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 0}]}]),
          16, 5)
    d.add(table("Moc maksymalna dziś",
                "Minuta z największą mocą czynną od północy (czas lokalny) i jej wartość. Dokładność czasu: jedna minuta.",
                [target(f"SELECT bucket AS \"Minuta\", active_power_max AS \"Moc maks. [W]\" FROM energy_1m WHERE {DEV} "
                        f"AND bucket >= {LOCAL_MIDNIGHT} AND active_power_max IS NOT NULL ORDER BY active_power_max DESC LIMIT 1", "table")]),
          6, 4, new_row=True)
    d.add(stat("Średni cos φ dziś", "Współczynnik mocy PF liczony od północy jako suma / liczba próbek z agregatu minutowego.",
               [target(f"SELECT now() AS time, sum(power_factor_sum) / nullif(sum(power_factor_n), 0) AS \"cos φ\" FROM energy_1m "
                       f"WHERE {DEV} AND bucket >= {LOCAL_MIDNIGHT}", "table")], decimals=2), 6, 4)
    d.add(stat("Pokrycie danych od północy",
               "Jaka część czasu od północy (czas lokalny) ma pomiar mocy: liczba próbek × okres próbkowania / upłynięty czas. Luki (awarie, zaniki) obniżają wartość.",
               [target(f"SELECT now() AS time, least(1.0, sum(active_power_n) * {POLL} / extract(epoch FROM now() - {LOCAL_MIDNIGHT})) "
                       f"AS \"Pokrycie\" FROM energy_1m WHERE {DEV} AND bucket >= {LOCAL_MIDNIGHT}", "table")],
               unit="percentunit", decimals=1,
               thresholds=[{"color": "red", "value": None}, {"color": "orange", "value": 0.8}, {"color": "green", "value": 0.95}]), 6, 4)
    d.add(stat("Epizody błędu licznika dziś",
               "Liczba przejść meter_status z 0 na wartość ≠ 0 w bazie od północy (czas lokalny), także sprzed zaniku zasilania lub restartu PLC. "
               "Licznik meter_error_count z PLC zeruje się przy restarcie PLC, więc nie musi się z tą liczbą zgadzać (w „Stanie i diagnostyce” widać jego przebieg). "
               "Brak pokrycia z powodu awarii PLC nie jest błędem licznika.",
               [target(f"SELECT now() AS time, count(*) AS \"Epizody\" FROM (SELECT value, lag(value) OVER (ORDER BY time) AS prev "
                       f"FROM measurements WHERE {DEV} AND metric = 'meter_status' AND time >= {LOCAL_MIDNIGHT}) s "
                       "WHERE value <> 0 AND prev = 0", "table")], decimals=0,
               thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}]), 6, 4)
    d.add(timeseries("Moc czynna", "Moc czynna P [W] w wybranym zakresie czasu (średnia w kroku wykresu), z agregatu minutowego.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Moc czynna\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     unit="watt", span_ms=150000), 24, 8, new_row=True)
    return d


# --- 2. Licznik na żywo ------------------------------------------------------------------------------------------------------

VAR_UNIT = "suffix: var"           # Grafana nie ma jednostki wyświetlającej "var": własny sufiks (K7-V7)
# metryka, skrót (tytuł kafelka), nazwa wykresu, jednostka, opis, szerokość kafelka
LIVE = [
    ("voltage", "Napięcie U", "Napięcie U", "volt", "Napięcie fazowe [V].", 4),
    ("current", "Prąd I", "Prąd I", "amp", "Prąd [A].", 4),
    ("active_power", "Moc czynna P", "Moc czynna P", "watt", "Moc czynna P [W]: faktycznie pobierana energia.", 4),
    ("reactive_power", "Moc bierna Q", "Moc bierna Q", VAR_UNIT, "Moc bierna Q [var].", 3),
    ("apparent_power", "Moc pozorna S", "Moc pozorna S", "voltamp", "Moc pozorna S [VA] = U × I.", 3),
    ("power_factor", "Współczynnik mocy PF", "Współczynnik mocy PF", "", "PF = P / S (cos φ przy przebiegach sinusoidalnych), bez jednostki.", 3),
    ("frequency", "Częstotliwość f", "Częstotliwość f", "hertz", "Częstotliwość sieci [Hz].", 3),
]


NO_V2 = "Brak danych (mapa v1)"          # metryki mapy v2: przed v2 brak wartości = brak danych, nigdy zero
# metryka, tytuł kafelka (pełna nazwa, K8-V2), nazwa wykresu, jednostka, opis, szerokość kafelka
LIVE_V2 = [
    ("thd_voltage", "THD napięcia", "THD napięcia (THD U)", "percent",
     "Zawartość harmonicznych napięcia U1 [%] (mapa v2).", 6),
    ("thd_current", "THD prądu", "THD prądu (THD I)", "percent",
     "Zawartość harmonicznych prądu I1 [%] (mapa v2). Zasilacze impulsowe dają wartości rzędu 100–150%. Przy małym prądzie względem zakresu licznika "
     "(80 mA wobec 40 A) wartość może być niepewna.", 6),
    ("phase_angle", "Kąt U–I", "Kąt U–I", "degree",
     "Kąt między napięciem a prądem [°] (mapa v2). U nas kąt jest ujemny przy mocy biernej Q < 0 (zmierzone 25.11.2026: −50,6° przy Q ≈ −9 var); "
     "konwencja znaku Findera nie jest potwierdzona w dokumentacji.", 6),
    ("meter_temperature", "Temperatura licznika", "Temperatura licznika", "celsius",
     "Temperatura wewnętrzna licznika [°C] (mapa v2), odświeżana w PLC co 10 s.", 6),
]


def live() -> Dash:
    d = new_dash("aip-na-zywo", "Licznik na żywo",
                 "Pomiary z licznika w czasie rzeczywistym (odświeżanie 5 s, domyślnie ostatnie 15 min). Dla zakresów dłuższych niż kilka godzin "
                 "użyj dashboardów „Jakość energii” i „Energia i profil” (dane zagregowane).", refresh="5s", time_from="now-15m")
    for metric, short, title, unit, desc, width in LIVE:
        d.add(stat(short, f"{title}: ostatnia wartość w oknie. {desc}",
                   [target(f"SELECT $__timeGroupAlias(time, $__interval), avg(value) AS \"{title}\" FROM measurements WHERE $__timeFilter(time) "
                           f"AND {DEV} AND metric = '{metric}' GROUP BY 1 ORDER BY 1")], unit=unit, decimals=2,
                   color_mode="none"), width, 3, new_row=(metric == LIVE[0][0]))
    for metric, short, title, unit, desc, width in LIVE_V2:
        d.add(stat(short, f"{title}: ostatnia wartość w oknie. {desc}",
                   [target(f"SELECT $__timeGroupAlias(time, $__interval), avg(value) AS \"{title}\" FROM measurements WHERE $__timeFilter(time) "
                           f"AND {DEV} AND metric = '{metric}' GROUP BY 1 ORDER BY 1")], unit=unit, decimals=2,
                   color_mode="none", no_value=NO_V2), width, 3, new_row=(metric == LIVE_V2[0][0]))
    d.add(table("Wartości w oknie",
                "Ostatnia, minimalna, maksymalna i średnia wartość każdej wielkości w wybranym oknie czasu.",
                [target(f"SELECT CASE metric WHEN 'voltage' THEN 'Napięcie U [V]' WHEN 'current' THEN 'Prąd I [A]' "
                        "WHEN 'active_power' THEN 'Moc czynna P [W]' WHEN 'reactive_power' THEN 'Moc bierna Q [var]' "
                        "WHEN 'apparent_power' THEN 'Moc pozorna S [VA]' WHEN 'power_factor' THEN 'PF' WHEN 'frequency' THEN 'Częstotliwość f [Hz]' "
                        "WHEN 'thd_voltage' THEN 'THD U [%]' WHEN 'thd_current' THEN 'THD I [%]' WHEN 'phase_angle' THEN 'Kąt U–I [°]' "
                        "ELSE 'Temperatura [°C]' END AS \"Wielkość\", "
                        "last(value, time) AS \"Ostatnia\", min(value) AS \"Min\", max(value) AS \"Maks\", "
                        "avg(value) AS \"Średnia\" FROM measurements WHERE $__timeFilter(time) AND "
                        f"{DEV} AND metric IN ('voltage','current','active_power','reactive_power','apparent_power','power_factor','frequency',"
                        "'thd_voltage','thd_current','phase_angle','meter_temperature') "
                        "GROUP BY metric ORDER BY 1", "table")], decimals=2, no_value=NO_V2), 24, 14, new_row=True)   # K8-V3: 11 wierszy bez przewijania
    charts = [item for item in LIVE] + [item for item in LIVE_V2 if item[0] != "meter_temperature"]      # temperatura: „Stan i diagnostyka”
    for i, (metric, short, title, unit, desc, width) in enumerate(charts):
        extra = {"min_": 0, "max_": 1} if metric == "power_factor" else {}
        last = i == len(charts) - 1 and len(charts) % 2 == 1
        d.add(timeseries(title, desc + " Średnia w kroku wykresu; luki dłuższe niż 5 s przerywają linię (brak danych, nie zero).",
                         [target(f"SELECT $__timeGroupAlias(time, $__interval), avg(value) AS \"{title}\" FROM measurements WHERE $__timeFilter(time) "
                                 f"AND {DEV} AND metric = '{metric}' GROUP BY 1 ORDER BY 1")], unit=unit, decimals=2, no_value=NO_V2, **extra),
              24 if last else 12, 7, new_row=(i == 0))
    return d


# --- 3. Jakość energii -------------------------------------------------------------------------------------------------------

def quality() -> Dash:
    d = new_dash("aip-jakosc", "Jakość energii",
                 "Napięcie, częstotliwość i współczynnik mocy z agregatu minutowego. Pasma (±% napięcia, ±Hz częstotliwości) są wartościami orientacyjnymi "
                 "ze zmiennych dashboardu, nie oceną zgodności z normą.", "u_nom", "u_band_pct", "f_nom", "f_band_hz", time_from="now-24h")
    band = "$u_nom * (1 - $u_band_pct / 100.0)"
    band_hi = "$u_nom * (1 + $u_band_pct / 100.0)"
    dashed_red = [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                  {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}, {"id": "custom.lineWidth", "value": 2}]
    # Linia dokładnie na brzegu obszaru wykresu bywa przycinana (górna wyglądała na szarą, K7c W-9): niewidoczne serie dają zapas osi.
    hidden_range = [{"matcher": {"id": "byRegexp", "options": "Zakres osi.*"},
                     "properties": [{"id": "custom.lineWidth", "value": 0}, {"id": "custom.fillOpacity", "value": 0},
                                    {"id": "custom.hideFrom", "value": {"legend": True, "tooltip": True, "viz": False}}]}]
    d.add(timeseries("Napięcie (min, średnia, maks.)",
                     "Napięcie [V] w kroku wykresu: minimum, średnia i maksimum z agregatu minutowego. Czerwone przerywane linie to granice pasma orientacyjnego "
                     "(napięcie znamionowe ± pasmo %); linia napięcia poza nimi oznacza wyjście z pasma.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), min(voltage_min) AS \"Minimum\", "
                             "sum(voltage_sum) / nullif(sum(voltage_n), 0) AS \"Średnia\", max(voltage_max) AS \"Maksimum\", "
                             f"{band} AS \"Dolna granica pasma\", {band_hi} AS \"Górna granica pasma\", "
                             f"{band} - 2 AS \"Zakres osi (dół)\", {band_hi} + 2 AS \"Zakres osi (góra)\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     unit="volt", span_ms=150000, decimals=1,
                     overrides=[{"matcher": {"id": "byRegexp", "options": ".*granica pasma"}, "properties": dashed_red}, *hidden_range]), 14, 9)
    d.add(stat("Poza pasmem U [min]",
               "Liczba minut w wybranym zakresie, w których minimum lub maksimum napięcia wyszło poza pasmo (napięcie znamionowe ± pasmo %). "
               "Pasmo jest orientacyjne i nie oznacza oceny zgodności z normą.",
               [target(f"SELECT now() AS time, count(*) AS \"Minuty\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} "
                       f"AND (voltage_min < {band} OR voltage_max > {band_hi})", "table")], decimals=0,
               thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}]), 5, 9)
    d.add(stat("Z danymi U [min]",
               "Liczba minut w zakresie, w których jest pomiar napięcia (mianownik dla panelu „Poza pasmem U [min]”).",
               [target(f"SELECT now() AS time, count(*) FILTER (WHERE voltage_n > 0) AS \"Minuty\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV}",
                       "table")], decimals=0, color_mode="none"), 5, 9)
    d.add(barchart("Rozkład napięcia (histogram)",
                   "Liczba minut w koszykach po 0,5 V według średniego napięcia minuty, w wybranym zakresie czasu.",
                   [target(f"SELECT to_char(floor(voltage_sum / voltage_n * 2) / 2, 'FM999.0') AS \"Napięcie [V]\", count(*) AS \"Minuty\" "
                           f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} AND voltage_n > 0 GROUP BY floor(voltage_sum / voltage_n * 2) "
                           "ORDER BY floor(voltage_sum / voltage_n * 2)", "table")]), 12, 8, new_row=True)
    d.add(timeseries("Odchyłka częstotliwości od znamionowej",
                     "Średnia częstotliwość sieci minus częstotliwość znamionowa [Hz] w kroku wykresu, z granicami pasma (± zmienna, czerwone przerywane linie).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(frequency_sum) / nullif(sum(frequency_n), 0) - $f_nom AS \"Odchyłka\", "
                             "$f_band_hz AS \"Górna granica\", -$f_band_hz AS \"Dolna granica\", "
                             "$f_band_hz * 1.1 AS \"Zakres osi (góra)\", -$f_band_hz * 1.1 AS \"Zakres osi (dół)\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     unit="suffix: Hz", span_ms=150000, decimals=2,
                     overrides=[{"matcher": {"id": "byRegexp", "options": ".*granica"}, "properties": dashed_red}, *hidden_range]), 12, 8)
    d.add(timeseries("Współczynnik mocy PF",
                     "Współczynnik mocy PF z licznika (średnia w kroku wykresu, 0–1) oraz, od mapy v2, cos φ = cos(kąt U–I) (średnia cos z próbek, z agregatu). "
                     "PF to nie jest cos φ, gdy prąd jest odkształcony: PF = cos φ / √(1 + THD_I²). Przy THD prądu ok. 140% PF wynosi 0,37, a cos φ 0,64 "
                     "(zmierzone 25.11.2026: kąt −50,6°, THD I 140,2%). Seria cos φ nie ma wartości przed mapą v2.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(power_factor_sum) / nullif(sum(power_factor_n), 0) AS \"PF\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1"),
                      target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(phase_cos_sum) / nullif(sum(phase_angle_n), 0) AS \"cos φ\" "
                             f"FROM energy_ext_1m WHERE $__timeFilter(bucket) AND {DEV} AND phase_angle_n > 0 GROUP BY 1 ORDER BY 1", ref="B")],
                     span_ms=150000, decimals=2, min_=0, max_=1), 12, 8, new_row=True)
    d.add(timeseries("Stosunek mocy biernej do czynnej (Q/P)",
                     "Stosunek średniej mocy biernej do średniej mocy czynnej Q/P w kroku wykresu; pusty, gdy P ≈ 0. Znak zależy od charakteru obciążenia (indukcyjne lub pojemnościowe).",
                     [target("SELECT $__timeGroupAlias(bucket, $__interval), (sum(reactive_power_sum) / nullif(sum(reactive_power_n), 0)) / "
                             "nullif(sum(active_power_sum) / nullif(sum(active_power_n), 0), 0) AS \"Q/P\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     span_ms=150000, decimals=2), 12, 8)
    def quality_panel(title, desc, metric_key, column, unit, label):
        return timeseries(title, desc,
                          [target(f"SELECT $__timeGroupAlias(bucket, $__interval), min({column}_min) AS \"Minimum\", "
                                  f"sum({column}_sum) / nullif(sum({column}_n), 0) AS \"Średnia\", max({column}_max) AS \"Maksimum\" "
                                  f"FROM energy_ext_1m WHERE $__timeFilter(bucket) AND {DEV} AND {column}_n > 0 GROUP BY 1 ORDER BY 1")],
                          unit=unit, span_ms=150000, decimals=2, no_value=NO_V2)

    d.add(quality_panel("THD napięcia (THD U)",
                        "Zawartość harmonicznych napięcia U1 [%]: minimum, średnia i maksimum w kroku wykresu (agregat minutowy, mapa v2). Brak wartości przed mapą v2.",
                        "thd_voltage", "thd_voltage", "percent", "THD U"), 8, 8, new_row=True)
    d.add(quality_panel("THD prądu (THD I)",
                        "Zawartość harmonicznych prądu I1 [%]: minimum, średnia i maksimum w kroku wykresu (mapa v2). Zasilacze impulsowe dają ok. 100–150%. "
                        "Przy małym prądzie względem zakresu licznika (80 mA wobec 40 A) wartość może być niepewna; nie oceniamy jej progami.",
                        "thd_current", "thd_current", "percent", "THD I"), 8, 8)
    d.add(quality_panel("Kąt U–I",
                        "Kąt między napięciem a prądem [°]: minimum, średnia i maksimum w kroku wykresu (mapa v2). U nas kąt jest ujemny przy mocy biernej Q < 0 "
                        "(zmierzone 25.11.2026: −50,6° przy Q ≈ −9 var); konwencja znaku Findera nie jest potwierdzona w dokumentacji.",
                        "phase_angle", "phase_angle", "degree", "Kąt"), 8, 8)
    return d


# --- 4. Energia i profil -----------------------------------------------------------------------------------------------------

WEEKDAYS = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"]
PART = "Pokrycie upłynionej części (w toku)"      # jedna nazwa i definicja dla minuty, godziny i doby (K7c W-4)
PROFILE_RANGE = "28d"
DAYS_RANGE = "14d"
PROFILE_DAYS, DAILY_DAYS = 28, 14
BASE_NIGHTS = 14                 # ostatnie noce w panelu mocy bazowej (K8-V6), zakres jak doby
# Własny zakres panelu liczony w SQL od „teraz”, a nie nadpisaniem `timeFrom`: Grafana stosuje `timeFrom` tylko przy WZGLĘDNYM zakresie pulpitu,
# a przy bezwzględnym (np. po zaznaczeniu wykresu) go ignoruje, więc panele pokazywały godziny z zakresu pulpitu (K7C-V1, k7d).
# Znacznik w SQL dla każdego takiego panelu (pilnuje go test): panel -> fragment zapytania.
OWN_RANGE_MARKER = {
    "daily": f"(now() AT TIME ZONE '{TZ}')::date - {DAILY_DAYS - 1}",
    "profile": f"now() - interval '{PROFILE_DAYS} days'",
}
OWN_RANGE_PANELS = {            # (dashboard, tytuł) -> klucz znacznika
    ("energia", f"Zużycie na dobę (ostatnie {DAYS_RANGE})"): "daily",
    ("energia", f"Profil: godzina × dzień tygodnia (ostatnie {PROFILE_RANGE})"): "profile",
    ("energia", "Moc maks. profilu"): "profile",
    ("energia", f"Kontrola całki mocy a licznik wzorcowy (doby, ostatnie {DAYS_RANGE})"): "daily",
    ("energia", f"Energia bierna na dobę: całka i licznik (ostatnie {DAYS_RANGE})"): "daily",
    ("energia", f"Moc bazowa (5. percentyl nocą, ostatnie {BASE_NIGHTS} nocy)"): "daily",
}


# Etykieta doby jako TEKST (K8-V5): samo "23.11" Grafana odczytywala jako liczbe 23,11 i dopisywala jednostke osi wartosci ("23.1 varh").
# Skrot dnia tygodnia (jak w profilu) czyni etykiete jednoznacznie tekstowa i dodaje informacje.
def _day_label(day_expr: str) -> str:
    names = " ".join(f"WHEN {i + 1} THEN '{name}'" for i, name in enumerate(WEEKDAYS))
    return f"to_char({day_expr}, 'DD.MM') || ' ' || CASE extract(isodow FROM {day_expr})::int {names} END"


def _elapsed(bucket_expr: str, width: str) -> str:
    """Sekundy upłynięte w wiaderku (dla wiaderka w toku tylko część do `now()`)."""
    return f"extract(epoch FROM least(now(), {bucket_expr} + interval '{width}') - {bucket_expr})"


def energy() -> Dash:
    d = new_dash("aip-energia", "Energia i profil",
                 "Zużycie energii z całki mocy (suma mocy z obecnych próbek × okres próbkowania) z pokryciem, profil godzinowo-tygodniowy, "
                 "porównania okresów, moc bazowa i kontrola zgodności z licznikiem wzorcowym. Luki nie są interpolowane: zużycie przy pokryciu poniżej 100% jest dolną granicą. "
                 f"Panele „Zużycie na dobę”, profil i kontrola z licznikiem mają własny zakres czasu (ostatnie {DAYS_RANGE} i {PROFILE_RANGE}, liczone od teraz), niezależny od zakresu pulpitu.",
                 time_from="now-7d")
    d.add(timeseries("Zużycie na minutę",
                     "Energia czynna [Wh] w każdej minucie (całka mocy, linia; niepełna, bieżąca minuta nie jest rysowana, żeby nie wyglądała na spadek zużycia) oraz pokrycie pełnych minut "
                     "pomiarem (żółta linia po prawej). Pomarańczowy punkt „" + PART + "” to pokrycie samej upłyniętej części bieżącej minuty (inna definicja niż pokrycie pełnych minut). "
                     "Obie osie zaczynają się od zera. Panel działa dla zakresów do 7 dni; dla dłuższych użyj paneli godzinowego i dobowego.",
                     [target(f"SELECT bucket AS time, CASE WHEN bucket + interval '1 minute' <= now() THEN active_power_sum * {POLL} / 3600.0 END AS \"Energia [Wh]\", "
                             f"CASE WHEN bucket + interval '1 minute' <= now() THEN least(1.0, active_power_n * {POLL} / 60.0) END AS \"Pokrycie\", "
                             f"CASE WHEN bucket + interval '1 minute' > now() THEN least(1.0, active_power_n * {POLL} / greatest({_elapsed('bucket', '1 minute')}, 1)) END "
                             f"AS \"{PART}\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} AND {SPAN_GUARD_7D} ORDER BY 1")],
                     unit="suffix: Wh", span_ms=150000, decimals=3, min_=0,
                     overrides=[coverage_override("Pokrycie"), coverage_override(PART, dashed=True, style="points")]), 24, 8)
    d.add(timeseries("Zużycie na godzinę",
                     "Energia czynna [Wh] w każdej godzinie (agregat godzinny; słupek zaczyna się na początku godziny) oraz pokrycie godziny pomiarem (żółta linia po prawej). "
                     "Pomarańczowy punkt „" + PART + "” (godzina w toku) to pokrycie samej upłyniętej części godziny, a nie całej godziny, żeby brak końcówki nie wyglądał na awarię.",
                     [target(f"SELECT bucket AS time, active_power_sum * {POLL} / 3600.0 AS \"Energia [Wh]\", "
                             f"CASE WHEN bucket + interval '1 hour' <= now() THEN least(1.0, active_power_n * {POLL} / 3600.0) END AS \"Pokrycie\", "
                             f"CASE WHEN bucket + interval '1 hour' > now() THEN least(1.0, active_power_n * {POLL} / greatest({_elapsed('bucket', '1 hour')}, 1)) END "
                             f"AS \"{PART}\" FROM energy_1h WHERE $__timeFilter(bucket) AND {DEV} ORDER BY 1")],
                     unit="watth", bars=True, span_ms=9000000, decimals=2, min_=0,
                     overrides=[coverage_override("Pokrycie"), coverage_override(PART, dashed=True, style="points")]), 12, 8, new_row=True)
    day_len = f"extract(epoch FROM ((day + 1)::timestamp AT TIME ZONE '{TZ}') - (day::timestamp AT TIME ZONE '{TZ}'))"
    day_elapsed = f"extract(epoch FROM now() - (day::timestamp AT TIME ZONE '{TZ}'))"
    d.add(barchart(f"Zużycie na dobę (ostatnie {DAYS_RANGE})",
                   "Energia czynna [Wh] w dobie lokalnej (Europe/Warsaw) z pomiarów (dolna granica przy braku pokrycia). W nawiasie pod słupkiem: pokrycie doby pomiarem; "
                   "dla doby w toku „w toku” i " + PART.lower() + " (samej upłyniętej części doby, nie całej doby). "
                   f"Zakres: ostatnie {DAYS_RANGE} liczone od teraz, niezależnie od zakresu pulpitu (także bezwzględnego).",
                   [target(f"SELECT to_char(day, 'DD.MM') || CASE WHEN day_complete THEN ' (' || coalesce(round(coverage * 100)::text, '?') || '%)' "
                           f"ELSE ' (w toku, ' || coalesce(round(least(1.0, coverage * {day_len} / greatest({day_elapsed}, 1)) * 100)::text, '?') || '%)' END "
                           f"AS \"Doba (pokrycie)\", integral_wh AS \"Energia [Wh]\" FROM energy_daily_check "
                           f"WHERE {DEV} AND day >= {OWN_RANGE_MARKER['daily']} ORDER BY day", "table")],
                   unit="watth", decimals=1, min_=0), 12, 8)
    grouped = (f"SELECT extract(hour FROM bucket AT TIME ZONE '{TZ}')::int AS hour, extract(isodow FROM bucket AT TIME ZONE '{TZ}')::int AS dow, "
               f"sum(active_power_sum) / nullif(sum(active_power_n), 0) AS w FROM energy_1h WHERE bucket >= {OWN_RANGE_MARKER['profile']} AND {DEV} GROUP BY 1, 2")
    cols = ", ".join(f"max(p) FILTER (WHERE dow = {i + 1}) AS \"{name}\"" for i, name in enumerate(WEEKDAYS))
    d.add(table(f"Profil: godzina × dzień tygodnia (ostatnie {PROFILE_RANGE})",
                f"Średnia moc czynna dla każdej godziny doby (czas lokalny) i dnia tygodnia w ostatnich {PROFILE_RANGE} (liczone od teraz, niezależnie od zakresu pulpitu, także bezwzględnego; z agregatu godzinnego), "
                "jako **procent największej średniej mocy w profilu** (100% = wartość z kafelka obok). Jedna wspólna, jednobarwna skala od jasnoniebieskiego (mało) do ciemnoniebieskiego (dużo): "
                "to profil zużycia, nie ocena dobrze/źle. Pusta, przezroczysta komórka bez liczby oznacza brak danych.",
                [target(f"SELECT hour AS \"Godzina\", {cols} FROM (SELECT hour, dow, 100.0 * w / nullif(max(w) OVER (), 0) AS p FROM ({grouped}) g) n "
                        "GROUP BY hour ORDER BY hour", "table")],
                custom={"cellOptions": {"type": "color-background", "mode": "gradient"}, "minWidth": 40, "align": "center"},   # 8 kolumn bez przewijania (K8-V7)
                decimals=0, unit="percent", min_=0, max_=100,
                overrides=[{"matcher": {"id": "byName", "options": "Godzina"},
                            "properties": [{"id": "custom.cellOptions", "value": {"type": "auto"}}, {"id": "unit", "value": "none"},
                                           {"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}}]}]), 18, 12, new_row=True)
    d.panels[-1]["fieldConfig"]["defaults"]["color"] = {"mode": "continuous-blues"}
    d.panels[-1]["fieldConfig"]["defaults"]["mappings"] = [{"type": "special", "options": {
        "match": "null+nan", "result": {"text": "", "color": "transparent", "index": 0}}}]
    d.add(stat("Moc maks. profilu",
               f"Największa średnia moc godzinowa w profilu obok (ostatnie {PROFILE_RANGE}, liczone od teraz niezależnie od zakresu pulpitu) [W]: to jest 100% skali kolorów.",
               [target(f"SELECT now() AS time, max(w) AS \"Maks. średnia moc\" FROM ({grouped}) g", "table")], unit="watt", decimals=1,
               color_mode="none"), 6, 12)
    d.add(timeseries("Moc: bieżący zakres a poprzednia doba",
                     "Średnia moc czynna [W] w wybranym zakresie czasu oraz ta sama wielkość sprzed 24 godzin (przesunięta na oś bieżącego zakresu).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Teraz\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1"),
                      target(f"SELECT $__timeGroupAlias(bucket + interval '1 day', $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Doba wcześniej\" "
                             f"FROM energy_1m WHERE bucket BETWEEN $__timeFrom()::timestamptz - interval '1 day' AND $__timeTo()::timestamptz - interval '1 day' AND {DEV} GROUP BY 1 ORDER BY 1",
                             ref="B")],
                     unit="watt", span_ms=150000, decimals=2), 12, 8, new_row=True)
    d.add(timeseries("Moc: bieżący zakres a poprzedni tydzień",
                     "Średnia moc czynna [W] w wybranym zakresie czasu oraz ta sama wielkość sprzed 7 dni (przesunięta na oś bieżącego zakresu).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Teraz\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1"),
                      target(f"SELECT $__timeGroupAlias(bucket + interval '7 days', $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Tydzień wcześniej\" "
                             f"FROM energy_1m WHERE bucket BETWEEN $__timeFrom()::timestamptz - interval '7 days' AND $__timeTo()::timestamptz - interval '7 days' AND {DEV} GROUP BY 1 ORDER BY 1",
                             ref="B")],
                     unit="watt", span_ms=150000, decimals=2), 12, 8)
    night_day = f"(bucket AT TIME ZONE '{TZ}')::date"
    d.add(barchart(f"Moc bazowa (5. percentyl nocą, ostatnie {BASE_NIGHTS} nocy)",
                   "Moc bazowa doby: 5. percentyl średniej minutowej mocy czynnej [W] w godzinach lokalnych 00:00–05:00 (obciążenie tła, gdy maszyny nie pracują). "
                   f"Jedna wartość na dobę lokalną. Zakres: ostatnie {BASE_NIGHTS} nocy liczone od teraz, niezależnie od zakresu pulpitu (także bezwzględnego): "
                   "przy krótkim zakresie (np. 1 godzina) nie ma nocy, więc panel o zakresie pulpitu byłby pusty.",
                   [target(f"SELECT {_day_label(night_day)} AS \"Noc (doba)\", "
                           "percentile_cont(0.05) WITHIN GROUP (ORDER BY active_power_sum / active_power_n) AS \"Moc bazowa [W]\" FROM energy_1m "
                           f"WHERE {night_day} >= {OWN_RANGE_MARKER['daily']} AND {DEV} AND active_power_n > 0 "
                           f"AND extract(hour FROM bucket AT TIME ZONE '{TZ}') < 5 "
                           f"GROUP BY {night_day} ORDER BY {night_day}", "table")],
                   unit="watt", decimals=2, min_=0), 24, 8, new_row=True)
    d.add(timeseries("Energia bierna z mocy (całka Q, godziny)",
                     "Energia bierna z całki mocy biernej [varh] w każdej godzinie, z podziałem na znak Q (suma Q × okres próbkowania / 3600 z obecnych próbek; "
                     "agregat godzinny, obejmuje także okres sprzed mapy v2). Q > 0: indukcyjna (konwencja odbiornika), Q < 0: pojemnościowa, podana jako moduł, "
                     "żeby porównywać ją ze stanem licznika n4. Bieżąca godzina jest niepełna z natury.",
                     [target(f"SELECT bucket AS time, reactive_pos_sum * {POLL} / 3600.0 AS \"Q > 0 [varh]\", -reactive_neg_sum * {POLL} / 3600.0 AS \"|Q| przy Q < 0 [varh]\" "
                             f"FROM energy_ext_1h WHERE $__timeFilter(bucket) AND {DEV} AND reactive_power_n > 0 ORDER BY 1")],
                     unit="suffix: varh", bars=True, span_ms=9000000, decimals=2, min_=0), 12, 8, new_row=True)
    d.add(barchart(f"Energia bierna na dobę: całka i licznik (ostatnie {DAYS_RANGE})",
                   "Energia bierna [varh] w dobie lokalnej: całka mocy biernej (Q > 0 i |Q| przy Q < 0) oraz przyrost liczników n2 (Q > 0) i n4 (Q < 0). "
                   "Przyrost liczy zapytanie z agregatu godzinnego z zapasem 3 dni wstecz (jak widok reactive_1h_calc, ale bez przeglądania całej historii). "
                   "Licznik zmienia stan co 100 varh, a przy Q ≈ −9 var to jeden krok na ok. 11 godzin, więc przyrost dobowy to 0, 100 lub 200: "
                   "brak przyrostu oznacza „brak kroku licznika”, a nie „brak energii biernej”. Przyrost licznika jest pusty przed mapą v2 (brak danych, nie zero): dane licznika są od 25.11.2026 10:43 UTC, a do pierwszego kroku licznika n4 "
                   "(co 100 varh) seria licznika jest pusta lub zerowa, co nie oznacza błędu. "
                   f"Zakres: ostatnie {DAYS_RANGE} liczone od teraz, niezależnie od zakresu pulpitu (także bezwzględnego).",
                   [target("WITH h AS (SELECT bucket, counter_pos_first AS pf, counter_pos_last AS pl, counter_neg_first AS nf, counter_neg_last AS nl, "
                           "reactive_pos_sum, reactive_neg_sum FROM energy_ext_1h WHERE " + DEV + " AND bucket >= now() - interval '17 days'), "
                           "pos AS (SELECT bucket, pf, pl, lag(pl) OVER (ORDER BY bucket) AS prev FROM h WHERE pl IS NOT NULL), "
                           "neg AS (SELECT bucket, nf, nl, lag(nl) OVER (ORDER BY bucket) AS prev FROM h WHERE nl IS NOT NULL) "
                           f"SELECT {_day_label('day')} AS \"Doba\", pos_int AS \"Całka Q > 0\", neg_int AS \"Całka |Q| (Q < 0)\", "
                           "pos_delta AS \"Licznik n2 (Q > 0)\", neg_delta AS \"Licznik n4 (Q < 0)\" FROM ("
                           f"SELECT (h.bucket AT TIME ZONE '{TZ}')::date AS day, sum(h.reactive_pos_sum) * {POLL} / 3600.0 AS pos_int, "
                           f"-sum(h.reactive_neg_sum) * {POLL} / 3600.0 AS neg_int, "
                           "sum(CASE WHEN p.pl IS NULL THEN NULL WHEN p.prev IS NULL THEN p.pl - p.pf WHEN p.pl < p.prev THEN p.pl ELSE p.pl - p.prev END) AS pos_delta, "
                           "sum(CASE WHEN n.nl IS NULL THEN NULL WHEN n.prev IS NULL THEN n.nl - n.nf WHEN n.nl < n.prev THEN n.nl ELSE n.nl - n.prev END) AS neg_delta "
                           "FROM h LEFT JOIN pos p ON p.bucket = h.bucket LEFT JOIN neg n ON n.bucket = h.bucket "
                           f"WHERE (h.bucket AT TIME ZONE '{TZ}')::date >= {OWN_RANGE_MARKER['daily']} GROUP BY 1) g ORDER BY day", "table")],
                   unit="suffix: varh", decimals=1, min_=0, no_value=NO_V2), 12, 8)
    d.add(table(f"Kontrola całki mocy a licznik wzorcowy (doby, ostatnie {DAYS_RANGE})",
                "Dla każdej doby lokalnej: energia z całki mocy, pokrycie doby, przyrost licznika wzorcowego i różnica. Skróty: Licznik = przyrost licznika wzorcowego, "
                "Ekstrap. = całka uzupełniona do pełnej doby (całka / pokrycie), Rozdz. = rozdzielczość licznika, W rozdz. = różnica nie większa niż jeden krok licznika, "
                "Luki = godziny po luce w danych. Licznik zmienia stan co 100 Wh, więc przy małym "
                "obciążeniu przyrost dobowy to 1–2 kroki: główną miarą zgodności jest „W granicach rozdzielczości”, a odchyłka procentowa jest podawana tylko przy "
                f"przyroście co najmniej 5 kroków licznika. Zakres: ostatnie {DAYS_RANGE} liczone od teraz, niezależnie od zakresu pulpitu (także bezwzględnego).",
                [target(f"SELECT to_char(day, 'YYYY-MM-DD') AS \"Doba\", integral_wh AS \"Całka [Wh]\", coverage AS \"Pokrycie doby\", counter_delta_wh AS \"Licznik [Wh]\", "
                        "integral_extrapolated_wh AS \"Ekstrap. [Wh]\", diff_wh AS \"Różnica [Wh]\", resolution_wh AS \"Rozdz. [Wh]\", "
                        "within_resolution AS \"W rozdz.\", deviation_pct AS \"Odchyłka [%]\", day_complete AS \"Zakończona\", "
                        f"gap_before_count AS \"Luki\" FROM energy_daily_check WHERE {DEV} AND day >= {OWN_RANGE_MARKER['daily']} "
                        "ORDER BY day DESC", "table")], decimals=1,
                custom={"minWidth": 50, "align": "right"},
                overrides=[{"matcher": {"id": "byName", "options": "Pokrycie doby"}, "properties": [{"id": "unit", "value": "percentunit"}]}]),
          24, 8, new_row=True)
    return d


# --- 5. Stan i diagnostyka ---------------------------------------------------------------------------------------------------

SENTINEL = "SELECT $__timeFrom()::timestamptz, NULL"      # wiersz zapewniający pole czasu także przy pustym wyniku (K7-V4)


def _states(metric_device: str, metric: str, label: str) -> str:
    """Zmiany stanu metryki + sztuczny stan „brak danych” po luce dłuższej niż $stale_s (zakres do 7 dni).
    K8-V1: pierwszy wiersz PO luce jest też wierszem stanu, nawet gdy wartość się nie zmieniła (0 -> 0); bez niego oś
    zostawała w „Brak danych” do końca zakresu."""
    return (
        f"WITH s AS (SELECT time, value, lag(value) OVER w AS prev, lag(time) OVER w AS prev_time, lead(time) OVER w AS next_time "
        f"FROM measurements "
        f"WHERE $__timeFilter(time) AND device_id = {metric_device} AND metric = '{metric}' AND {SPAN_GUARD_7D} WINDOW w AS (ORDER BY time)) "
        f"SELECT time, value AS \"{label}\" FROM s WHERE prev IS DISTINCT FROM value OR time - prev_time > {STALE} "
        f"UNION ALL SELECT time + {STALE}, {NO_DATA_CODE} FROM s WHERE next_time - time > {STALE} "
        f"UNION ALL {SENTINEL} ORDER BY 1")


def diagnostics() -> Dash:
    d = new_dash("aip-diagnostyka", "Stan i diagnostyka",
                 "Stan łącza z PLC i licznika, kody błędów komunikacji, liczniki błędów, wiek danych i luki. Zmiany stanów są liczone dla zakresów do 7 dni. "
                 "Brak pokrycia z powodu awarii PLC nie jest błędem licznika.", "stale_s", time_from="now-24h")
    d.add(state_timeline("Łącze z PLC (link_status)",
                         "Stan łącza collectora z PLC: kody i komunikaty z docs/status-codes.md. „Brak danych”: luka w danych dłuższa niż próg (collector zatrzymany, zanik zasilania).",
                         [target(_states(PLC, "link_status", "Łącze z PLC"))], LINK_MAP), 24, 5)
    d.add(state_timeline("Stan licznika (meter_status)",
                         "Stan licznika z PLC: kody i komunikaty z docs/status-codes.md. Przy link_status ≠ 0 licznik nie publikuje statusu (stąd „Brak danych”).",
                         [target(_states(f"'$device'", "meter_status", "Stan licznika"))], METER_MAP), 24, 5, new_row=True)
    d.add(state_timeline("Kod błędu komunikacji PLC–licznik (meter_error_code)",
                         "Kod błędu publikowany tylko przy meter_status ≠ 0: 161 RESPONSE_TIMEOUT, 162 RESPONSE_CRC_FAIL, 163 RESPONSE_WRONG_SLAVE "
                         "(źródło nazw: dokumentacja CODESYS MB_ErrorCodes, patrz docs/status-codes.md). Kod jest pokazywany tylko w czasie błędu (meter_status ≠ 0), "
                         "poza nim „Brak błędu” (zielony). Epizody są krótkie (ok. 4 s), więc przy długich zakresach ich opisy bywają ucięte do pierwszych znaków (np. „16”): "
                         "przybliż wykres, żeby zobaczyć pełną nazwę.",
                         [target("WITH s AS (SELECT time, value, lead(time) OVER w AS next_time FROM measurements WHERE $__timeFilter(time) AND "
                                 f"{DEV} AND metric = 'meter_error_code' AND {SPAN_GUARD_7D} WINDOW w AS (ORDER BY time)) "
                                 "SELECT time, value AS \"Kod błędu\" FROM s "
                                 "UNION ALL SELECT time + interval '1 second', 0 FROM s WHERE next_time IS NULL OR next_time - time > interval '2 seconds' "
                                 "UNION ALL SELECT $__timeFrom()::timestamptz, 0 ORDER BY 1")], ERROR_MAP, no_value="Brak błędów w zakresie"), 24, 4, new_row=True)
    d.add(timeseries("Licznik błędów komunikacji (meter_error_count)",
                     "Licznik błędów komunikacji PLC–licznik (16-bitowy, po 65535 wraca do 0; restart PLC go zeruje).",
                     [target(f"SELECT $__timeGroupAlias(time, $__interval), max(value) AS \"meter_error_count\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND {DEV} AND metric = 'meter_error_count' GROUP BY 1 ORDER BY 1")], span_ms=60000, decimals=0), 12, 7, new_row=True)
    d.add(timeseries("Wiek danych licznika (meter_data_age_ms)",
                     "Czas od ostatniej udanej odpowiedzi licznika [ms], maksimum w kroku wykresu. Przy NO_DATA (FFFFFFFF) wartość nie jest publikowana.",
                     [target(f"SELECT $__timeGroupAlias(time, $__interval), max(value) AS \"Wiek danych\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND {DEV} AND metric = 'meter_data_age_ms' GROUP BY 1 ORDER BY 1")], unit="ms", span_ms=60000, decimals=0), 12, 7)
    missing = f"greatest(0, {_elapsed('bucket', '1 hour')} - active_power_n * {POLL})"
    d.add(timeseries("Sekundy bez pomiaru mocy na godzinę",
                     "Ile sekund w godzinie nie ma pomiaru mocy, liczone tylko względem upłyniętej części godziny (godzina w toku, jasna seria, nie jest karana za czas, który jeszcze nie nastąpił). "
                     "Awaria PLC i zanik zasilania także dają sekundy bez pomiaru, ale nie są błędem licznika.",
                     [target(f"SELECT bucket AS time, CASE WHEN bucket + interval '1 hour' <= now() THEN {missing} END AS \"Godzina zakończona\", "
                             f"CASE WHEN bucket + interval '1 hour' > now() THEN {missing} END AS \"Godzina w toku\" FROM energy_1h "
                             f"WHERE $__timeFilter(bucket) AND {DEV} AND {POLL} IS NOT NULL ORDER BY 1")],
                     unit="s", bars=True, span_ms=9000000, decimals=0, min_=0), 12, 7, new_row=True)
    d.add(timeseries("Wiersze na minutę w bazie",
                     "Liczba wierszy zapisanych w bazie na minutę: sprawny licznik daje 13 wierszy na sekundę przy mapie v1 (780 na minutę) albo 20 przy mapie v2 (1 200 na minutę), "
                     "przy meter_status ≠ 0 5 na sekundę (300 na minutę), przy awarii PLC 1 na sekundę (60 na minutę); model z docs/status-codes.md. "
                     "Bieżąca, niepełna minuta jest pomijana. Panel dla zakresów do 24 godzin.",
                     [target(f"SELECT time_bucket(interval '1 minute', time) AS time, count(*) AS \"Wiersze\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND time < date_trunc('minute', now()) "
                             f"AND (device_id = '$device' OR device_id = {PLC}) AND ($__timeTo()::timestamptz - $__timeFrom()::timestamptz) <= interval '24 hours' GROUP BY 1 ORDER BY 1")],
                     span_ms=150000, decimals=0, min_=0), 12, 7)
    d.add(stat("Temperatura licznika",
               "Ostatnia temperatura wewnętrzna licznika [°C] w wybranym zakresie czasu (mapa v2, odświeżana w PLC co 10 s). Bez progów: granice z karty katalogowej nie są znane.",
               [target(f"SELECT now() AS time, (SELECT temperature_sum / nullif(temperature_n, 0) FROM energy_ext_1m WHERE {DEV} AND temperature_n > 0 "
                       f"AND $__timeFilter(bucket) ORDER BY bucket DESC LIMIT 1) AS \"Temperatura\"", "table")],
               unit="celsius", decimals=1, no_value=NO_V2), 4, 7, new_row=True)
    d.add(timeseries("Temperatura licznika [°C]",
                     "Temperatura wewnętrzna licznika: minimum, średnia i maksimum w kroku wykresu (agregat minutowy, mapa v2). Brak wartości przed mapą v2.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), min(temperature_min) AS \"Minimum\", "
                             f"sum(temperature_sum) / nullif(sum(temperature_n), 0) AS \"Średnia\", max(temperature_max) AS \"Maksimum\" "
                             f"FROM energy_ext_1m WHERE $__timeFilter(bucket) AND {DEV} AND temperature_n > 0 GROUP BY 1 ORDER BY 1")],
                     unit="celsius", span_ms=150000, decimals=1, no_value=NO_V2), 8, 7)
    d.add(stat("Czas pracy licznika",
               "Czas pracy licznika w dobach (ostatnia wartość z zakresu; mapa v2, odświeżany w PLC co 10 s). Wartość jest zapisywana jako REAL w sekundach, "
               "więc po ok. 194 dniach traci rozdzielczość 1 s; wykres obok pokazuje zerowania (restart licznika).",
               [target(f"SELECT now() AS time, (SELECT run_time_last / 86400.0 FROM energy_ext_1m WHERE {DEV} AND run_time_last IS NOT NULL "
                       f"AND $__timeFilter(bucket) ORDER BY bucket DESC LIMIT 1) AS \"Czas pracy\"", "table")],
               unit="suffix: d", decimals=2, no_value=NO_V2), 4, 7)
    d.add(timeseries("Czas pracy licznika [dni]",
                     "Czas pracy licznika [dni] (ostatnia wartość w kroku wykresu, agregat minutowy, mapa v2). Spadek wartości oznacza restart licznika; brak wartości przed mapą v2.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), min(run_time_min) / 86400.0 AS \"Minimum\", max(run_time_max) / 86400.0 AS \"Maksimum\" "
                             f"FROM energy_ext_1m WHERE $__timeFilter(bucket) AND {DEV} AND run_time_last IS NOT NULL GROUP BY 1 ORDER BY 1")],
                     unit="suffix: d", span_ms=150000, decimals=3, no_value=NO_V2), 8, 7)
    return d


# --- 6. Flota (E3-k6) --------------------------------------------------------------------------------------------------------

METERS = "d.kind = 'energy_meter' AND d.enabled"
D_POLL = "(d.meta ->> 'poll_interval_s')::float8"
D_LABEL = SIM_LABEL.replace("name", "d.name").replace("source", "d.source")
# K6R-V3: Grafana mierzy etykiety osi kategorii (oś wierszy osi stanów, oś kategorii wykresu słupkowego) o kilka pikseli za wąsko
# i najszerszej etykiecie ucina pierwszą literę; tych osi nie da się poszerzyć opcją. Dwie spacje cyfrowe (U+2007) z przodu
# poszerzają wyliczoną oś; etykieta wyrównana do prawej, więc odstęp jest niewidoczny.
AXIS_PAD = "repeat(chr(8199), 2) || "
D_AXIS_LABEL = AXIS_PAD + "(" + D_LABEL + ")"
KWH = "suffix: kWh"               # K6R-V6: stała jednostka w kWh (jednostka "kwatth" przełączała małe wartości na Wh)
FRESH_MAP = mapping({2: "Dane", 1: "Dane niepełne", 0: "Brak danych"})
for _code, _color in {2: "green", 1: "orange", 0: "red"}.items():
    FRESH_MAP[0]["options"][str(_code)]["color"] = _color


def banner(d: Dash) -> None:
    panel = _panel("text", "Dane symulowane", "Objaśnienie znacznika SYMULACJA (S10).", [],
                   options={"mode": "markdown", "content": SIM_BANNER})
    d.add(panel, 24, 3, new_row=True)


def coverage_states(device_filter: str, label: str, poll: str, source: str, n_col: str, hourly: str) -> str:
    """Oś stanów świeżości/pokrycia: kubełki co max($__interval, 1 min) wygenerowane w SQL (brak wiersza w agregacie = „Brak danych”,
    a nie przerwa w osi), na urządzenie. Kubełek w toku liczony tylko z upłyniętej części. Kubełki w całości przed pierwszym odczytem
    urządzenia nie mają stanu (NULL, przezroczyste; K6R-V2): urządzenie, którego jeszcze nie było, nie jest awarią. Pierwszy odczyt
    raz na urządzenie (CTE `f`): godzina z małego agregatu godzinnego (`min` na agregacie minutowym trwał sekundy), a gdy wypada
    w zakresie, dokładny kubełek z danych zakresu (`a`)."""
    return (f"WITH s AS (SELECT make_interval(secs => greatest($__interval_ms / 1000.0, 60)) AS step), "
            f"b AS (SELECT generate_series(time_bucket(s.step, $__timeFrom()::timestamptz), $__timeTo()::timestamptz, s.step) AS t FROM s), "
            f"a AS (SELECT time_bucket(s.step, bucket) AS t, device_id, sum({n_col}) AS n FROM {source}, s "
            f"WHERE $__timeFilter(bucket) GROUP BY 1, 2), "
            f"h AS MATERIALIZED (SELECT d.device_id, (SELECT min(x.bucket) FROM {hourly} x WHERE x.device_id = d.device_id) AS first_h "
            f"FROM devices d WHERE {device_filter}), "
            f"f AS MATERIALIZED (SELECT h.device_id, CASE WHEN h.first_h >= $__timeFrom()::timestamptz - interval '1 hour' "
            f"THEN (SELECT min(a.t) FROM a WHERE a.device_id = h.device_id) ELSE h.first_h END AS first FROM h) "
            f"SELECT b.t AS time, {label} AS metric, CASE "
            f"WHEN f.first IS NULL OR b.t + s.step <= f.first THEN NULL "
            f"WHEN coalesce(a.n, 0) * {poll} >= 0.95 * extract(epoch FROM least(now(), b.t + s.step) - b.t) THEN 2 "
            f"WHEN coalesce(a.n, 0) > 0 THEN 1 ELSE 0 END AS value "
            f"FROM b CROSS JOIN s CROSS JOIN devices d JOIN f ON f.device_id = d.device_id LEFT JOIN a ON a.t = b.t AND a.device_id = d.device_id "
            f"WHERE {device_filter} AND b.t <= now() ORDER BY 1, 2")


def fleet() -> Dash:
    d = Dash("aip-flota", "Flota",
             "Wszystkie liczniki energii naraz: prawdziwe (pomiar przez PLC) i symulowane (dopisek SYMULACJA). Stan = świeżość danych "
             "(nie praca/postój maszyny – to etap 4). Moc i energia z agregatów minutowych i godzinnych.", "30s", "now-24h")
    d.variables = [textbox("stale_s", "Dane uznane za stare po [s]")]
    d.links = nav_links()
    banner(d)
    last = ("(SELECT max(time) FROM measurements m WHERE m.device_id = d.device_id AND m.metric = 'active_power' "
            "AND m.time > now() - interval '1 hour')")
    power_now = (f"(SELECT value FROM measurements m WHERE m.device_id = d.device_id AND m.metric = 'active_power' "
                 f"AND m.time > now() - {STALE} ORDER BY m.time DESC LIMIT 1)")
    energy_today = (f"(SELECT c.integral_wh / 1000.0 FROM energy_daily_check c WHERE c.device_id = d.device_id "
                    f"AND c.day = (now() AT TIME ZONE '{TZ}')::date)")
    d.add(table("Liczniki floty",
                "Jeden wiersz na licznik (prawdziwe na górze). Źródło: „pomiar” (prawdziwy sprzęt) albo „SYMULACJA”. Stan: „Aktualne”, gdy ostatnia "
                "próbka mocy jest młodsza niż próg ze zmiennej „Dane uznane za stare po”, inaczej „Brak danych”. Wiek odczytu: sekundy od ostatniej "
                "próbki mocy (puste: brak próbki w ostatniej godzinie). Moc teraz: tylko gdy dane są aktualne (brak danych to nie zero). "
                "Energia od północy (czas lokalny) z całki mocy, przy lukach dolna granica.",
                [target(f"SELECT label AS \"Urządzenie\", src AS \"Źródło\", CASE WHEN last IS NULL OR now() - last > {STALE} THEN 'Brak danych' "
                        "ELSE 'Aktualne' END AS \"Stan\", extract(epoch FROM now() - last) AS \"Wiek odczytu\", p AS \"Moc teraz\", "
                        "e AS \"Energia od północy\" "
                        f"FROM (SELECT d.source, {D_LABEL} AS label, CASE WHEN d.source = 'sim' THEN '{SIM_MARK}' ELSE 'pomiar' END AS src, "
                        f"{last} AS last, {power_now} AS p, {energy_today} AS e FROM devices d WHERE {METERS}) f "
                        "ORDER BY source = 'sim', label", "table")],
                decimals=1,
                overrides=[
                    {"matcher": {"id": "byName", "options": "Źródło"}, "properties": [
                        {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                        {"id": "mappings", "value": [{"type": "value", "options": {
                            SIM_MARK: {"text": SIM_MARK, "color": "orange", "index": 0},
                            "pomiar": {"text": "pomiar", "color": "green", "index": 1}}}]}]},
                    {"matcher": {"id": "byName", "options": "Stan"}, "properties": [
                        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                        {"id": "mappings", "value": [{"type": "value", "options": {
                            "Aktualne": {"text": "Aktualne", "color": "green", "index": 0},
                            "Brak danych": {"text": "Brak danych", "color": "red", "index": 1}}}]}]},
                    {"matcher": {"id": "byName", "options": "Wiek odczytu"}, "properties": [{"id": "unit", "value": "s"}, {"id": "decimals", "value": 0}]},
                    {"matcher": {"id": "byName", "options": "Moc teraz"}, "properties": [{"id": "unit", "value": "watt"}]},
                    {"matcher": {"id": "byName", "options": "Energia od północy"}, "properties": [{"id": "unit", "value": KWH}, {"id": "decimals", "value": 3}]},
                ]), 24, 7, new_row=True)
    d.add(timeseries("Moc czynna – flota",
                     "Średnia moc czynna [W] każdego licznika w kroku wykresu, z agregatu minutowego. Luki dłuższe niż 2,5 min przerywają linię "
                     "(brak danych, nie zero).",
                     [target(f"SELECT $__timeGroupAlias(e.bucket, $__interval), {D_LABEL} AS metric, "
                             "sum(e.active_power_sum) / nullif(sum(e.active_power_n), 0) AS value FROM energy_1m e JOIN devices d USING (device_id) "
                             f"WHERE $__timeFilter(e.bucket) AND {METERS} GROUP BY 1, 2 ORDER BY 1")],
                     unit="watt", span_ms=150000, decimals=1), 24, 8, new_row=True)
    hourly = timeseries("Energia na godzinę – flota",
                        "Energia czynna [kWh] w każdej godzinie, słupki skumulowane na licznik (z agregatu godzinnego; godzina w toku niepełna). "
                        "Z całki mocy: przy lukach dolna granica.",
                        [target(f"SELECT e.bucket AS time, {D_LABEL} AS metric, e.active_power_sum * {D_POLL} / 3600000.0 AS value "
                                f"FROM energy_1h e JOIN devices d USING (device_id) WHERE $__timeFilter(e.bucket) AND {METERS} ORDER BY 1")],
                        unit=KWH, bars=True, span_ms=9000000, decimals=2, min_=0)
    hourly["fieldConfig"]["defaults"]["custom"]["stacking"] = {"mode": "normal", "group": "A"}
    d.add(hourly, 12, 8, new_row=True)
    d.add(_panel("barchart", "Udział w energii zakresu",
                 "Energia czynna [kWh] każdego licznika w wybranym zakresie czasu (pełne godziny z agregatu godzinnego, z całki mocy).",
                 [target(f"SELECT {D_AXIS_LABEL} AS \"Urządzenie\", sum(e.active_power_sum * {D_POLL}) / 3600000.0 AS \"Energia [kWh]\" "
                         f"FROM energy_1h e JOIN devices d USING (device_id) WHERE $__timeFilter(e.bucket) AND {METERS} "
                         "GROUP BY 1 ORDER BY 2 DESC", "table")],
                 unit=KWH, decimals=2, min_=0, custom={"fillOpacity": 80},
                 options={"orientation": "horizontal", "showValue": "always", "stacking": "none",
                          "legend": {"showLegend": False}, "tooltip": {"mode": "single"}}), 12, 8)
    d.add(state_timeline("Świeżość danych w czasie",
                         "Dla każdego licznika i kroku osi (co najmniej 1 min): „Dane” – pomiar mocy przez co najmniej 95% kroku, „Dane niepełne” – część "
                         "kroku bez pomiaru, „Brak danych” – żadnego pomiaru po pierwszym odczycie; przed pierwszym odczytem licznika oś jest pusta. Z agregatu minutowego; krok w toku liczony z upłyniętej części.",
                         [target(coverage_states(METERS, D_AXIS_LABEL, D_POLL, "energy_1m", "active_power_n", "energy_1h"))], FRESH_MAP), 24, 8, new_row=True)
    return d


# --- 7. Pompa (E3-k6) --------------------------------------------------------------------------------------------------------

PUMP = "device_id = '$pump'"
RPM_UNIT = "suffix: obr/min"     # K6R-V5: pełna liczba bez skrótu tysięcy (jednostka "rpm" dawała „3K rd/m”); dane nadal w rpm
TREND_DAYS = 90                  # własny zakres trendu drgań (S9, plan k6); 84 dni historii mieszczą się w nim
TREND_MARKER = f"now() - interval '{TREND_DAYS} days'"
RUN_NOTE = ("Minuta pracy (K4-D2): wszystkie próbki obrotów w minucie > 0; minuty postoju i częściowe (start, koniec zmiany) nie wchodzą "
            "do drgań – drgania w postoju i rozruchu nie mówią o stanie łożyska.")


def pump() -> Dash:
    d = Dash("aip-pompa", "Pompa",
             "Stan pompy z agregatu minutowego pump_1m: drgania, temperatura łożyska, prąd, przepływ, obroty. Trend drgań liczony tylko "
             "z minut pracy. Bez prognozy – szacowanie dni do przekroczenia progu to etap 5.", "1m", "now-7d")
    d.variables = [device_variable("pump", "Pompa", "pump")]
    d.links = nav_links()
    banner(d)
    d.add(stat("Drgania (ost. godz. pracy)",
               "Średnie drgania RMS [mm/s] z ostatnich 60 minut pracy (w ostatnich 7 dniach). " + RUN_NOTE,
               [target(f"SELECT now() AS time, avg(vibration_avg) AS \"Drgania\" FROM (SELECT vibration_avg FROM pump_1m_calc WHERE {PUMP} "
                       "AND running AND bucket > now() - interval '7 days' ORDER BY bucket DESC LIMIT 60) r", "table")],
               unit="suffix: mm/s", decimals=2, color_mode="none"), 6, 4, new_row=True)
    d.add(stat("Temperatura łożyska teraz",
               "Ostatnia średnia minutowa temperatury łożyska [°C] z ostatnich 10 minut.",
               [target(f"SELECT bucket AS time, bearing_temperature_avg AS \"Temperatura\" FROM pump_1m_calc WHERE {PUMP} "
                       "AND bucket > now() - interval '10 minutes' ORDER BY bucket")],
               unit="celsius", decimals=1, color_mode="none"), 6, 4)
    d.add(stat("Obroty teraz",
               "Ostatnia średnia minutowa obrotów [obr/min] z ostatnich 10 minut (0 = postój).",
               [target(f"SELECT bucket AS time, speed_avg AS \"Obroty\" FROM pump_1m_calc WHERE {PUMP} "
                       "AND bucket > now() - interval '10 minutes' ORDER BY bucket")],
               unit=RPM_UNIT, decimals=0, color_mode="none"), 6, 4)
    d.add(stat("Minuty pracy dziś",
               "Liczba minut pracy od północy (czas lokalny). " + RUN_NOTE,
               [target(f"SELECT now() AS time, count(*) FILTER (WHERE running) AS \"Minuty pracy\" FROM pump_1m_calc WHERE {PUMP} "
                       f"AND bucket >= {LOCAL_MIDNIGHT}", "table")], decimals=0, color_mode="none"), 6, 4)
    trend = timeseries(f"Trend drgań z minut pracy (ostatnie {TREND_DAYS} dni)",
                       f"Średnia dobowa drgań RMS [mm/s] tylko z minut pracy (doba lokalna) i liczba minut pracy w dobie (prawa oś, pokrycie). "
                       f"Oś {TREND_DAYS} dni od teraz; przy zaznaczeniu fragmentu wykresu oś idzie za pulpitem (dane nadal {TREND_DAYS} dni, liczone od teraz, niezależnie od zakresu pulpitu). Doby bez pracy (np. niedziele) są puste. "
                       + RUN_NOTE,
                       [target(f"SELECT time_bucket('1 day', bucket, '{TZ}') AS time, avg(vibration_avg) AS \"Drgania (średnia doby pracy)\", "
                               f"count(*) AS \"Minuty pracy\" FROM pump_1m_calc WHERE {PUMP} AND running AND bucket >= {TREND_MARKER} "
                               "GROUP BY 1 ORDER BY 1")],
                       unit="suffix: mm/s", span_ms=90000000, decimals=2, min_=0,
                       overrides=[{"matcher": {"id": "byName", "options": "Minuty pracy"}, "properties": [
                           COVERAGE_AXIS, {"id": "unit", "value": "none"}, {"id": "custom.drawStyle", "value": "bars"},
                           {"id": "custom.fillOpacity", "value": 25}, {"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}]}])
    trend["fieldConfig"]["defaults"]["custom"]["showPoints"] = "always"
    # K6R-V1: oś 90 dni przez `timeFrom` (działa przy względnym zakresie pulpitu), dane 90 dni w SQL (także przy bezwzględnym,
    # gdy Grafana pomija `timeFrom`; wtedy oś jest zakresem pulpitu).
    trend["timeFrom"], trend["hideTimeOverride"] = f"{TREND_DAYS}d", False
    d.add(trend, 24, 9, new_row=True)
    d.add(timeseries("Drgania – minuty pracy",
                     "Drgania RMS [mm/s] w kroku wykresu, średnia tylko z minut pracy; postoje i minuty częściowe są puste (przerwa w linii, nie zero). "
                     + RUN_NOTE,
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), avg(vibration_avg) FILTER (WHERE running) AS \"Drgania (praca)\" "
                             f"FROM pump_1m_calc WHERE $__timeFilter(bucket) AND {PUMP} GROUP BY 1 ORDER BY 1")],
                     unit="suffix: mm/s", span_ms=150000, decimals=2, min_=0), 12, 8, new_row=True)
    d.add(timeseries("Obroty",
                     "Obroty [obr/min] w kroku wykresu, wszystkie minuty: 0 = postój. Pokazuje, kiedy pompa pracowała.",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), avg(speed_avg) AS \"Obroty\" "
                             f"FROM pump_1m_calc WHERE $__timeFilter(bucket) AND {PUMP} GROUP BY 1 ORDER BY 1")],
                     unit=RPM_UNIT, span_ms=150000, decimals=0, min_=0), 12, 8)
    for title, column, unit, desc in (
            ("Temperatura łożyska", "bearing_temperature_avg", "celsius", "Temperatura łożyska [°C], średnia w kroku wykresu, wszystkie minuty."),
            ("Prąd silnika", "motor_current_avg", "amp", "Prąd silnika [A], średnia w kroku wykresu, wszystkie minuty (0 = postój)."),
            ("Przepływ", "flow_avg", "suffix: m³/h", "Przepływ [m³/h], średnia w kroku wykresu, wszystkie minuty (0 = postój).")):
        d.add(timeseries(title, desc + " Luki dłuższe niż 2,5 min przerywają linię (brak danych, nie zero).",
                         [target(f"SELECT $__timeGroupAlias(bucket, $__interval), avg({column}) AS \"{title}\" "
                                 f"FROM pump_1m_calc WHERE $__timeFilter(bucket) AND {PUMP} GROUP BY 1 ORDER BY 1")],
                         unit=unit, span_ms=150000, decimals=1), 8, 7, new_row=(column == "bearing_temperature_avg"))
    share = timeseries("Udział minut pracy na godzinę",
                       "Część minut każdej godziny, które były minutami pracy (0–100%). " + RUN_NOTE,
                       [target(f"SELECT time_bucket('1 hour', bucket) AS time, avg(running::int) AS \"Udział minut pracy\" "
                               f"FROM pump_1m_calc WHERE $__timeFilter(bucket) AND {PUMP} GROUP BY 1 ORDER BY 1")],
                       unit="percentunit", bars=True, span_ms=9000000, decimals=0, min_=0, max_=1)
    d.add(share, 24, 6, new_row=True)
    return d


DASHBOARDS = {"przeglad": overview, "na-zywo": live, "jakosc": quality, "energia": energy, "diagnostyka": diagnostics,
              "flota": fleet, "pompa": pump}


def render() -> dict[str, str]:
    return {name: json.dumps(build().json(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            for name, build in DASHBOARDS.items()}


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        bad = [n for n, text in rendered.items()
               if not (OUT / f"{n}.json").exists() or (OUT / f"{n}.json").read_text(encoding="utf-8") != text]
        if bad:
            print("Pliki różnią się od wyniku generatora:", ", ".join(bad))
            return 1
        print("OK: JSON zgodny z generatorem")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in rendered.items():
        with open(OUT / f"{name}.json", "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    print("zapisano:", ", ".join(f"{n}.json" for n in rendered))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
