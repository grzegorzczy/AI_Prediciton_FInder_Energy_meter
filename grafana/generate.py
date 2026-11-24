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
ERROR_MAP = mapping({c: f"{c} {n}" for c, n in CODES["errors"].items()}, {0: ("0 (brak kodu)", "text")})


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
           max_: float | None = None, transformations: list | None = None) -> dict:
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
    return panel


def timeseries(title, description, targets, unit="", span_ms=5000, bars=False, **kw):
    custom = {"lineWidth": 1, "fillOpacity": 25 if bars else 8, "showPoints": "never", "spanNulls": span_ms,
              "drawStyle": "bars" if bars else "line"}
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
    out = [{
        "type": "query", "name": "device", "label": "Licznik", "datasource": DS, "refresh": 1, "sort": 1,
        "multi": False, "includeAll": False, "hide": 0,
        "query": "SELECT device_id AS __value, name AS __text FROM devices WHERE kind = 'energy_meter' AND enabled ORDER BY 1",
        "definition": "SELECT device_id AS __value, name AS __text FROM devices WHERE kind = 'energy_meter' AND enabled ORDER BY 1",
        "current": {},
    }]
    for name in names:
        out.append({"type": "textbox", "name": name, "label": labels[name], "query": DEFAULTS[name],
                    "current": {"text": DEFAULTS[name], "value": DEFAULTS[name]}, "hide": 0,
                    "options": [{"selected": True, "text": DEFAULTS[name], "value": DEFAULTS[name]}]})
    return out


def nav_links() -> list[dict]:
    items = [("Przegląd", "aip-przeglad"), ("Licznik na żywo", "aip-na-zywo"), ("Jakość energii", "aip-jakosc"),
             ("Energia i profil", "aip-energia"), ("Stan i diagnostyka", "aip-diagnostyka")]
    return [{"type": "link", "title": title, "url": f"/d/{uid}", "icon": "dashboard", "includeVars": True,
             "keepTime": True, "targetBlank": False, "asDropdown": False} for title, uid in items]


def new_dash(uid, title, description, *var_names, refresh="", time_from="now-24h") -> Dash:
    d = Dash(uid, title, description, refresh, time_from)
    d.variables = variables(*var_names)
    d.links = nav_links()
    return d


# --- 1. Przegląd -------------------------------------------------------------------------------------------------------------

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
    d.add(stat("Zużycie dziś (z pomiarów)",
               "Energia czynna z całki mocy od północy: suma mocy z obecnych próbek × okres próbkowania. Przy pokryciu poniżej 100% to dolna granica "
               "(luki nie są interpolowane). Pokrycie i szacunek pełnej doby w tabeli obok.",
               [target(f"SELECT now() AS time, integral_wh AS \"Energia\" FROM energy_daily_check WHERE {DEV} AND day = {day}", "table")],
               unit="watth", decimals=1), 4, 4, new_row=True)
    d.add(stat("Zużycie wczoraj (z pomiarów)", "Jak obok, dla poprzedniej doby (czas lokalny). Dolna granica przy pokryciu poniżej 100%.",
               [target(f"SELECT now() AS time, integral_wh AS \"Energia\" FROM energy_daily_check WHERE {DEV} AND day = {day} - 1", "table")],
               unit="watth", decimals=1), 4, 4)
    d.add(table("Zużycie dziś i wczoraj",
                "Energia z całki mocy (dolna granica), pokrycie doby pomiarem, szacunek pełnej doby (całka / pokrycie, tylko przy pokryciu ≥ 50%) "
                "oraz przyrost licznika wzorcowego (kwantyzacja 100 Wh, więc informacyjnie). Dla bieżącej doby pokrycie obejmuje też godziny, które jeszcze nie nastąpiły.",
                [target(f"SELECT day AS \"Doba\", integral_wh AS \"Energia z pomiarów [Wh]\", coverage AS \"Pokrycie doby\", "
                        f"integral_extrapolated_wh AS \"Szacunek pełnej doby [Wh]\", counter_delta_wh AS \"Przyrost licznika [Wh]\", "
                        f"day_complete AS \"Doba zakończona\" FROM energy_daily_check WHERE {DEV} AND day >= {day} - 1 ORDER BY day DESC",
                        "table")],
                overrides=[{"matcher": {"id": "byName", "options": "Pokrycie doby"}, "properties": [{"id": "unit", "value": "percentunit"}]}]),
          12, 4)
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
               "Liczba przejść meter_status z 0 na wartość ≠ 0 od północy (czas lokalny). Brak pokrycia z powodu awarii PLC nie jest błędem licznika.",
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

LIVE = [
    ("voltage", "Napięcie U", "volt", "Napięcie fazowe [V]."),
    ("current", "Prąd I", "amp", "Prąd [A]."),
    ("active_power", "Moc czynna P", "watt", "Moc czynna P [W]: faktycznie pobierana energia."),
    ("reactive_power", "Moc bierna Q", "reactivevoltamp", "Moc bierna Q [var]."),
    ("apparent_power", "Moc pozorna S", "voltamp", "Moc pozorna S [VA] = U × I."),
    ("power_factor", "Współczynnik mocy PF", "", "PF = P / S (cos φ przy przebiegach sinusoidalnych), bez jednostki."),
    ("frequency", "Częstotliwość f", "hertz", "Częstotliwość sieci [Hz]."),
]


def live() -> Dash:
    d = new_dash("aip-na-zywo", "Licznik na żywo",
                 "Pomiary z licznika w czasie rzeczywistym (odświeżanie 5 s, domyślnie ostatnie 15 min). Dla zakresów dłuższych niż kilka godzin "
                 "użyj dashboardów „Jakość energii” i „Energia i profil” (dane zagregowane).", refresh="5s", time_from="now-15m")
    for metric, title, unit, desc in LIVE:
        d.add(stat(title + ": teraz", desc + " Ostatnia wartość w oknie.",
                   [target(f"SELECT $__timeGroupAlias(time, $__interval), avg(value) AS \"{title}\" FROM measurements WHERE $__timeFilter(time) "
                           f"AND {DEV} AND metric = '{metric}' GROUP BY 1 ORDER BY 1")], unit=unit, decimals=2,
                   color_mode="none"), 3, 3, new_row=(metric == LIVE[0][0]))
    d.add(table("Wartości w oknie",
                "Ostatnia, minimalna, maksymalna i średnia wartość każdej wielkości w wybranym oknie czasu.",
                [target(f"SELECT CASE metric WHEN 'voltage' THEN 'Napięcie U [V]' WHEN 'current' THEN 'Prąd I [A]' "
                        "WHEN 'active_power' THEN 'Moc czynna P [W]' WHEN 'reactive_power' THEN 'Moc bierna Q [var]' "
                        "WHEN 'apparent_power' THEN 'Moc pozorna S [VA]' WHEN 'power_factor' THEN 'PF' ELSE 'Częstotliwość f [Hz]' END AS \"Wielkość\", "
                        "(array_agg(value ORDER BY time DESC))[1] AS \"Ostatnia\", min(value) AS \"Min\", max(value) AS \"Maks\", "
                        "avg(value) AS \"Średnia\" FROM measurements WHERE $__timeFilter(time) AND "
                        f"{DEV} AND metric IN ('voltage','current','active_power','reactive_power','apparent_power','power_factor','frequency') "
                        "GROUP BY metric ORDER BY 1", "table")], decimals=2), 24, 7, new_row=True)
    for metric, title, unit, desc in LIVE:
        d.add(timeseries(title, desc + " Średnia w kroku wykresu; luki dłuższe niż 5 s przerywają linię (brak danych, nie zero).",
                         [target(f"SELECT $__timeGroupAlias(time, $__interval), avg(value) AS \"{title}\" FROM measurements WHERE $__timeFilter(time) "
                                 f"AND {DEV} AND metric = '{metric}' GROUP BY 1 ORDER BY 1")], unit=unit, decimals=2),
              12, 7, new_row=(metric == LIVE[0][0]))
    return d


# --- 3. Jakość energii -------------------------------------------------------------------------------------------------------

def quality() -> Dash:
    d = new_dash("aip-jakosc", "Jakość energii",
                 "Napięcie, częstotliwość i współczynnik mocy z agregatu minutowego. Pasma (±% napięcia, ±Hz częstotliwości) są wartościami orientacyjnymi "
                 "ze zmiennych dashboardu, nie oceną zgodności z normą.", "u_nom", "u_band_pct", "f_nom", "f_band_hz", time_from="now-24h")
    band = "$u_nom * (1 - $u_band_pct / 100.0)"
    band_hi = "$u_nom * (1 + $u_band_pct / 100.0)"
    d.add(timeseries("Napięcie (min, średnia, maks.)",
                     "Napięcie [V] w kroku wykresu: minimum, średnia i maksimum z agregatu minutowego, z granicami pasma orientacyjnego "
                     "(napięcie znamionowe ± pasmo %).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), min(voltage_min) AS \"Minimum\", "
                             "sum(voltage_sum) / nullif(sum(voltage_n), 0) AS \"Średnia\", max(voltage_max) AS \"Maksimum\", "
                             f"{band} AS \"Dolna granica pasma\", {band_hi} AS \"Górna granica pasma\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     unit="volt", span_ms=150000, decimals=1,
                     overrides=[{"matcher": {"id": "byRegexp", "options": ".*granica pasma"},
                                 "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                                {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]), 16, 9)
    d.add(stat("Minuty z napięciem poza pasmem",
               "Liczba minut w wybranym zakresie, w których minimum lub maksimum napięcia wyszło poza pasmo (napięcie znamionowe ± pasmo %). "
               "Pasmo jest orientacyjne i nie oznacza oceny zgodności z normą.",
               [target(f"SELECT now() AS time, count(*) AS \"Minuty\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} "
                       f"AND (voltage_min < {band} OR voltage_max > {band_hi})", "table")], decimals=0,
               thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}]), 4, 5)
    d.add(stat("Minuty z danymi napięcia", "Liczba minut w zakresie, w których jest pomiar napięcia (mianownik dla panelu obok).",
               [target(f"SELECT now() AS time, count(*) FILTER (WHERE voltage_n > 0) AS \"Minuty\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV}",
                       "table")], decimals=0, color_mode="none"), 4, 4)
    d.add(barchart("Rozkład napięcia (histogram)",
                   "Liczba minut w koszykach po 0,5 V według średniego napięcia minuty, w wybranym zakresie czasu.",
                   [target(f"SELECT to_char(floor(voltage_sum / voltage_n * 2) / 2, 'FM999.0') AS \"Napięcie [V]\", count(*) AS \"Minuty\" "
                           f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} AND voltage_n > 0 GROUP BY floor(voltage_sum / voltage_n * 2) "
                           "ORDER BY floor(voltage_sum / voltage_n * 2)", "table")]), 8, 9)
    d.add(timeseries("Odchyłka częstotliwości od znamionowej",
                     "Średnia częstotliwość sieci minus częstotliwość znamionowa [Hz] w kroku wykresu, z granicami pasma (± zmienna).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(frequency_sum) / nullif(sum(frequency_n), 0) - $f_nom AS \"Odchyłka\", "
                             "$f_band_hz AS \"Górna granica\", -$f_band_hz AS \"Dolna granica\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     unit="hertz", span_ms=150000, decimals=3,
                     overrides=[{"matcher": {"id": "byRegexp", "options": ".*granica"},
                                 "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
                                                {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]}]), 12, 8, new_row=True)
    d.add(timeseries("Współczynnik mocy (cos φ) i stosunek Q/P",
                     "Współczynnik mocy PF (średnia w kroku wykresu) oraz stosunek mocy biernej do czynnej Q/P (średnie w kroku; pusty, gdy P ≈ 0).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(power_factor_sum) / nullif(sum(power_factor_n), 0) AS \"cos φ\", "
                             "(sum(reactive_power_sum) / nullif(sum(reactive_power_n), 0)) / "
                             "nullif(sum(active_power_sum) / nullif(sum(active_power_n), 0), 0) AS \"Q/P\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1")],
                     span_ms=150000, decimals=2), 12, 8)
    return d


# --- 4. Energia i profil -----------------------------------------------------------------------------------------------------

WEEKDAYS = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Niedz"]


def energy() -> Dash:
    d = new_dash("aip-energia", "Energia i profil",
                 "Zużycie energii z całki mocy (suma mocy z obecnych próbek × okres próbkowania) z pokryciem, profil godzinowo-tygodniowy, "
                 "porównania okresów, moc bazowa i kontrola zgodności z licznikiem wzorcowym. Luki nie są interpolowane: zużycie przy pokryciu poniżej 100% jest dolną granicą.",
                 time_from="now-7d")
    d.add(timeseries("Zużycie na minutę",
                     "Energia czynna [Wh] w każdej minucie (całka mocy) oraz pokrycie minuty pomiarem. Panel działa dla zakresów do 7 dni; dla dłuższych użyj paneli godzinowego i dobowego.",
                     [target(f"SELECT bucket AS time, active_power_sum * {POLL} / 3600.0 AS \"Energia [Wh]\", "
                             f"least(1.0, active_power_n * {POLL} / 60.0) AS \"Pokrycie\" FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} "
                             f"AND {SPAN_GUARD_7D} ORDER BY 1")],
                     unit="watth", bars=True, span_ms=150000, decimals=3,
                     overrides=[{"matcher": {"id": "byName", "options": "Pokrycie"},
                                 "properties": [{"id": "unit", "value": "percentunit"}, {"id": "custom.axisPlacement", "value": "right"},
                                                {"id": "custom.drawStyle", "value": "line"}, {"id": "max", "value": 1}]}]), 24, 8)
    d.add(timeseries("Zużycie na godzinę",
                     "Energia czynna [Wh] w każdej godzinie (agregat godzinny) oraz pokrycie godziny pomiarem. Bieżąca godzina ma pokrycie poniżej 1 z natury (jeszcze trwa).",
                     [target(f"SELECT bucket AS time, energy_integral_wh AS \"Energia [Wh]\", coverage AS \"Pokrycie\" FROM energy_1h_calc "
                             f"WHERE $__timeFilter(bucket) AND {DEV} ORDER BY 1")],
                     unit="watth", bars=True, span_ms=9000000, decimals=2,
                     overrides=[{"matcher": {"id": "byName", "options": "Pokrycie"},
                                 "properties": [{"id": "unit", "value": "percentunit"}, {"id": "custom.axisPlacement", "value": "right"},
                                                {"id": "custom.drawStyle", "value": "line"}, {"id": "max", "value": 1}]}]), 12, 8, new_row=True)
    d.add(timeseries("Zużycie na dobę",
                     "Energia czynna [Wh] w dobie lokalnej (Europe/Warsaw) i pokrycie doby pomiarem. Doba w toku ma pokrycie poniżej 1.",
                     [target(f"SELECT day::timestamp AT TIME ZONE '{TZ}' AS time, integral_wh AS \"Energia [Wh]\", coverage AS \"Pokrycie\" "
                             f"FROM energy_daily_check WHERE {DEV} AND day::timestamp AT TIME ZONE '{TZ}' BETWEEN $__timeFrom()::timestamptz - interval '1 day' AND $__timeTo() ORDER BY 1")],
                     unit="watth", bars=True, span_ms=200000000, decimals=1,
                     overrides=[{"matcher": {"id": "byName", "options": "Pokrycie"},
                                 "properties": [{"id": "unit", "value": "percentunit"}, {"id": "custom.axisPlacement", "value": "right"},
                                                {"id": "custom.drawStyle", "value": "points"}, {"id": "max", "value": 1}]}]), 12, 8)
    cols = ", ".join(
        f"avg(w) FILTER (WHERE dow = {i + 1}) AS \"{name}\"" for i, name in enumerate(WEEKDAYS))
    d.add(table("Profil: godzina × dzień tygodnia (średnia moc)",
                "Średnia moc czynna [W] dla każdej godziny doby (czas lokalny) i dnia tygodnia w wybranym zakresie czasu, z agregatu godzinnego. "
                "Kolor komórki rośnie ze średnią mocą; pusta komórka oznacza brak danych w tym zakresie.",
                [target(f"SELECT hour AS \"Godzina\", {cols} FROM (SELECT extract(hour FROM bucket AT TIME ZONE '{TZ}')::int AS hour, "
                        f"extract(isodow FROM bucket AT TIME ZONE '{TZ}')::int AS dow, active_power_sum / nullif(active_power_n, 0) AS w "
                        f"FROM energy_1h WHERE $__timeFilter(bucket) AND {DEV}) s GROUP BY hour ORDER BY hour", "table")],
                custom={"cellOptions": {"type": "color-background", "mode": "gradient"}}, decimals=1, unit="watt",
                overrides=[{"matcher": {"id": "byName", "options": "Godzina"},
                            "properties": [{"id": "custom.cellOptions", "value": {"type": "auto"}}, {"id": "unit", "value": "none"},
                                           {"id": "decimals", "value": 0}]}]), 24, 12, new_row=True)
    d.add(timeseries("Moc: bieżący zakres a poprzednia doba",
                     "Średnia moc czynna [W] w wybranym zakresie czasu oraz ta sama wielkość sprzed 24 godzin (przesunięta na oś bieżącego zakresu).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Teraz\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1"),
                      target(f"SELECT $__timeGroupAlias(bucket + interval '1 day', $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Doba wcześniej\" "
                             f"FROM energy_1m WHERE bucket BETWEEN $__timeFrom()::timestamptz - interval '1 day' AND $__timeTo()::timestamptz - interval '1 day' AND {DEV} GROUP BY 1 ORDER BY 1",
                             ref="B")],
                     unit="watt", span_ms=150000, decimals=1), 12, 8, new_row=True)
    d.add(timeseries("Moc: bieżący zakres a poprzedni tydzień",
                     "Średnia moc czynna [W] w wybranym zakresie czasu oraz ta sama wielkość sprzed 7 dni (przesunięta na oś bieżącego zakresu).",
                     [target(f"SELECT $__timeGroupAlias(bucket, $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Teraz\" "
                             f"FROM energy_1m WHERE $__timeFilter(bucket) AND {DEV} GROUP BY 1 ORDER BY 1"),
                      target(f"SELECT $__timeGroupAlias(bucket + interval '7 days', $__interval), sum(active_power_sum) / nullif(sum(active_power_n), 0) AS \"Tydzień wcześniej\" "
                             f"FROM energy_1m WHERE bucket BETWEEN $__timeFrom()::timestamptz - interval '7 days' AND $__timeTo()::timestamptz - interval '7 days' AND {DEV} GROUP BY 1 ORDER BY 1",
                             ref="B")],
                     unit="watt", span_ms=150000, decimals=1), 12, 8)
    d.add(timeseries("Moc bazowa (5. percentyl nocą)",
                     "Moc bazowa doby: 5. percentyl średniej minutowej mocy czynnej [W] w godzinach lokalnych 00:00–05:00 (obciążenie tła, gdy maszyny nie pracują). "
                     "Jedna wartość na dobę lokalną.",
                     [target(f"SELECT (bucket AT TIME ZONE '{TZ}')::date::timestamp AT TIME ZONE '{TZ}' AS time, "
                             "percentile_cont(0.05) WITHIN GROUP (ORDER BY active_power_sum / active_power_n) AS \"Moc bazowa\" FROM energy_1m "
                             f"WHERE $__timeFilter(bucket) AND {DEV} AND active_power_n > 0 AND extract(hour FROM bucket AT TIME ZONE '{TZ}') < 5 "
                             "GROUP BY 1 ORDER BY 1")],
                     unit="watt", span_ms=200000000, decimals=1), 12, 8, new_row=True)
    d.add(table("Kontrola całki mocy a licznik wzorcowy (doby)",
                "Dla każdej doby lokalnej: energia z całki mocy, pokrycie, przyrost licznika wzorcowego i różnica. Licznik zmienia stan co 100 Wh, więc przy małym "
                "obciążeniu przyrost dobowy to 1–2 kroki: główną miarą zgodności jest „W granicach rozdzielczości”, a odchyłka procentowa jest podawana tylko przy "
                "przyroście co najmniej 5 kroków licznika.",
                [target(f"SELECT day AS \"Doba\", integral_wh AS \"Całka [Wh]\", coverage AS \"Pokrycie\", counter_delta_wh AS \"Przyrost licznika [Wh]\", "
                        "integral_extrapolated_wh AS \"Całka uzupełniona do doby [Wh]\", diff_wh AS \"Różnica [Wh]\", resolution_wh AS \"Rozdzielczość [Wh]\", "
                        "within_resolution AS \"W granicach rozdzielczości\", deviation_pct AS \"Odchyłka [%]\", day_complete AS \"Doba zakończona\", "
                        f"gap_before_count AS \"Godziny po luce\" FROM energy_daily_check WHERE {DEV} AND day::timestamp AT TIME ZONE '{TZ}' "
                        "BETWEEN $__timeFrom()::timestamptz - interval '1 day' AND $__timeTo() ORDER BY day DESC", "table")], decimals=1,
                overrides=[{"matcher": {"id": "byName", "options": "Pokrycie"}, "properties": [{"id": "unit", "value": "percentunit"}]}]),
          24, 8, new_row=True)
    return d


# --- 5. Stan i diagnostyka ---------------------------------------------------------------------------------------------------

def _states(metric_device: str, metric: str, label: str) -> str:
    """Zmiany stanu metryki + sztuczny stan „brak danych” po luce dłuższej niż $stale_s (zakres do 7 dni)."""
    return (
        f"WITH s AS (SELECT time, value, lag(value) OVER w AS prev, lead(time) OVER w AS next_time FROM measurements "
        f"WHERE $__timeFilter(time) AND device_id = {metric_device} AND metric = '{metric}' AND {SPAN_GUARD_7D} WINDOW w AS (ORDER BY time)) "
        f"SELECT time, value AS \"{label}\" FROM s WHERE prev IS DISTINCT FROM value "
        f"UNION ALL SELECT time + {STALE}, {NO_DATA_CODE} FROM s WHERE next_time - time > {STALE} ORDER BY 1")


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
                         "(źródło nazw: dokumentacja CODESYS MB_ErrorCodes, patrz docs/status-codes.md). Pusty pasek: brak błędu.",
                         [target(f"SELECT time, value AS \"Kod błędu\" FROM measurements WHERE $__timeFilter(time) AND {DEV} AND metric = 'meter_error_code' "
                                 f"AND {SPAN_GUARD_7D} ORDER BY time")], ERROR_MAP), 24, 4, new_row=True)
    d.add(timeseries("Licznik błędów komunikacji (meter_error_count)",
                     "Licznik błędów komunikacji PLC–licznik (16-bitowy, po 65535 wraca do 0; restart PLC go zeruje).",
                     [target(f"SELECT $__timeGroupAlias(time, $__interval), max(value) AS \"meter_error_count\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND {DEV} AND metric = 'meter_error_count' GROUP BY 1 ORDER BY 1")], span_ms=60000, decimals=0), 12, 7, new_row=True)
    d.add(timeseries("Wiek danych licznika (meter_data_age_ms)",
                     "Czas od ostatniej udanej odpowiedzi licznika [ms], maksimum w kroku wykresu. Przy NO_DATA (FFFFFFFF) wartość nie jest publikowana.",
                     [target(f"SELECT $__timeGroupAlias(time, $__interval), max(value) AS \"Wiek danych\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND {DEV} AND metric = 'meter_data_age_ms' GROUP BY 1 ORDER BY 1")], unit="ms", span_ms=60000, decimals=0), 12, 7)
    d.add(timeseries("Sekundy bez pomiaru mocy na godzinę",
                     "Ile sekund w godzinie nie ma pomiaru mocy (3600 × (1 − pokrycie)). Godzina w toku (jasna seria) jest niepełna z natury; "
                     "awaria PLC i zanik zasilania także dają sekundy bez pomiaru, ale nie są błędem licznika.",
                     [target(f"SELECT bucket AS time, CASE WHEN bucket_complete THEN 3600 * (1 - coverage) END AS \"Godzina zakończona\", "
                             f"CASE WHEN NOT bucket_complete THEN 3600 * (1 - coverage) END AS \"Godzina w toku\" FROM energy_1h_calc "
                             f"WHERE $__timeFilter(bucket) AND {DEV} AND coverage IS NOT NULL ORDER BY 1")],
                     unit="s", bars=True, span_ms=9000000, decimals=0), 12, 7, new_row=True)
    d.add(timeseries("Wiersze na minutę w bazie",
                     "Liczba wierszy zapisanych w bazie na minutę: sprawny licznik daje 13 na sekundę (780 na minutę), przy meter_status ≠ 0 5 na sekundę, "
                     "przy awarii PLC 1 na sekundę (model z docs/status-codes.md). Panel dla zakresów do 24 godzin.",
                     [target(f"SELECT time_bucket(interval '1 minute', time) AS time, count(*) AS \"Wiersze\" FROM measurements WHERE $__timeFilter(time) "
                             f"AND (device_id = '$device' OR device_id = {PLC}) AND ($__timeTo()::timestamptz - $__timeFrom()::timestamptz) <= interval '24 hours' GROUP BY 1 ORDER BY 1")],
                     span_ms=150000, decimals=0), 12, 7)
    return d


DASHBOARDS = {"przeglad": overview, "na-zywo": live, "jakosc": quality, "energia": energy, "diagnostyka": diagnostics}


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
