"""Tabela data_windows (004): okna testów i przerw jako adnotacje Grafany i wykluczenia analityki."""
from __future__ import annotations

import psycopg
import pytest

# Zapytanie adnotacji w dashboardach (grafana/generate.py importuje tę samą treść; test pilnuje, że zwraca okna z zakresu)
ANNOTATION_SQL = (
    "SELECT start_time AS time, end_time AS \"timeEnd\", kind AS tags, description AS text FROM data_windows "
    "WHERE start_time <= %(to)s AND end_time >= %(from)s ORDER BY start_time"
)


def test_seed_windows_are_present_and_consistent(admin):
    rows = admin.execute("SELECT kind, start_time, end_time, exclude_from_analytics FROM data_windows ORDER BY start_time").fetchall()
    kinds = [r[0] for r in rows]
    assert kinds == ["collector_start", "calm_window", "mqtt_broker_restart", "collector_stopped", "rs485_break",
                     "plc_lan1_unplugged", "plc_program_stop", "power_outage", "collector_stopped", "deploy"]
    assert all(r[2] >= r[1] for r in rows)
    assert {r[0] for r in rows if not r[3]} == {"calm_window"}          # tylko okno referencyjne zostaje w analityce


def test_power_outage_matches_the_documented_gap(admin):
    start, end = admin.execute("SELECT start_time, end_time FROM data_windows WHERE kind = 'power_outage'").fetchone()
    assert start.isoformat().startswith("2026-11-23T23:16:57")
    assert end.isoformat().startswith("2026-11-24T06:52:43")


def test_annotation_query_returns_the_windows_of_a_range(admin):
    rows = admin.execute(ANNOTATION_SQL, {"from": "2026-11-23 22:30:00+00", "to": "2026-11-23 23:10:00+00"}).fetchall()
    assert [r[2] for r in rows] == ["collector_start", "calm_window", "mqtt_broker_restart", "collector_stopped",
                                    "rs485_break", "plc_lan1_unplugged", "plc_program_stop"]
    assert admin.execute(ANNOTATION_SQL, {"from": "2026-11-20 00:00:00+00", "to": "2026-11-20 12:00:00+00"}).fetchall() == []


def test_reader_reads_and_writer_and_reader_cannot_change(reader, writer):
    assert reader.execute("SELECT count(*) FROM data_windows").fetchone()[0] == 10
    with pytest.raises(psycopg.Error):
        reader.execute("DELETE FROM data_windows")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        writer.execute("INSERT INTO data_windows (start_time, end_time, kind, description) "
                       "VALUES (now(), now(), 'x', 'y')")


def test_constraints(admin):
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("INSERT INTO data_windows (start_time, end_time, kind, description) "
                      "VALUES ('2026-11-24 10:00+00', '2026-11-24 09:00+00', 'x', 'koniec przed początkiem')")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("INSERT INTO data_windows (start_time, end_time, kind, description) "
                      "VALUES (now(), now(), 'Zla Nazwa', 'zły rodzaj')")
