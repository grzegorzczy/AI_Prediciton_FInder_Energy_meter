"""Kafelek „Stan licznika” (K3-U3): „Brak danych z PLC”, gdy link_status ≠ 0 lub dane starsze niż próg."""
from __future__ import annotations

import json

import pytest

from grafana_support import dashboards, expand_vars, load_generator, targets

METER = "finder_7m24_1"
NO_PLC, NO_METER = 100, 101


def tile_sql() -> str:
    dash = dashboards()["przeglad"]
    sql = next(t["rawSql"] for title, t in targets(dash) if title == "Stan licznika")
    return expand_vars(sql, METER)


def plc_sql() -> str:
    dash = dashboards()["przeglad"]
    return expand_vars(next(t["rawSql"] for title, t in targets(dash) if title == "Stan PLC"), METER)


@pytest.fixture
def seeded(admin):
    admin.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source, meta) VALUES "
        "('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real', '{}'), "
        "(%s, 'Licznik', 'zaklad1', 'linia1', 'energy_meter', 'real', %s)", (METER, json.dumps({"poll_interval_s": 1.0})))
    return admin


def put(conn, device, metric, value, age_s):
    conn.execute("INSERT INTO measurements (time, device_id, metric, value, unit, source) "
                 "VALUES (now() - make_interval(secs => %s), %s, %s, %s, '', 'real')", (age_s, device, metric, value))


def state(conn, sql) -> float | None:
    return conn.execute(sql).fetchone()[1]


# (wiek link_status [s] lub None, wartość link, wiek meter_status [s] lub None, wartość meter, oczekiwany kod kafelka)
CASES = [
    ("wszystko sprawne i świeże", (1, 0), (1, 0), 0),
    ("licznik zgłasza błąd komunikacji", (1, 0), (1, 1), 1),
    ("licznik bez danych po starcie PLC", (1, 0), (1, 2), 2),
    ("inny licznik niż w konfiguracji", (1, 0), (1, 10), 10),
    ("PLC offline (link_status = 1)", (1, 1), (1, 0), NO_PLC),
    ("PLC zatrzymany (link_status = 2)", (1, 2), (1, 0), NO_PLC),
    ("zła wersja mapy (link_status = 3)", (1, 3), (1, 0), NO_PLC),
    ("ostatni link_status starszy niż 10 s", (30, 0), (1, 0), NO_PLC),
    ("brak jakiegokolwiek link_status", None, (1, 0), NO_PLC),
    ("ostatni meter_status starszy niż 10 s", (1, 0), (30, 0), NO_METER),
    ("brak meter_status przy sprawnym łączu", (1, 0), None, NO_METER),
    ("PLC offline, stary meter_status", (1, 1), (60, 0), NO_PLC),
]


@pytest.mark.parametrize("name, link, meter, expected", CASES, ids=[c[0] for c in CASES])
def test_tile_cases(seeded, reader, name, link, meter, expected):
    if link:
        put(seeded, "plc-01", "link_status", link[1], link[0])
    if meter:
        put(seeded, METER, "meter_status", meter[1], meter[0])
    assert state(reader, tile_sql()) == expected, name


def test_plc_tile_reports_stale_data(seeded, reader):
    put(seeded, "plc-01", "link_status", 0, 1)
    assert state(reader, plc_sql()) == 0
    seeded.execute("DELETE FROM measurements")
    put(seeded, "plc-01", "link_status", 0, 30)
    assert state(reader, plc_sql()) == NO_PLC


def test_stale_threshold_is_the_dashboard_variable(seeded, reader):
    put(seeded, "plc-01", "link_status", 0, 30)
    put(seeded, METER, "meter_status", 0, 30)
    dash = dashboards()["przeglad"]
    sql = next(t["rawSql"] for title, t in targets(dash) if title == "Stan licznika")
    assert state(reader, expand_vars(sql, METER, {"stale_s": "120"})) == 0       # zmieniony próg: dane nie są już „stare”
    assert state(reader, expand_vars(sql, METER, {"stale_s": "10"})) == NO_PLC


def test_tile_texts_come_from_the_status_document():
    generator = load_generator()
    options = next(p for p in dashboards()["przeglad"]["panels"] if p["title"] == "Stan licznika")[
        "fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options[str(NO_PLC)]["text"] == "Brak danych z PLC"
    assert options["0"]["text"] == generator.CODES["meter"][0]
