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
                     "plc_lan1_unplugged", "plc_program_stop", "power_outage", "collector_stopped", "plc_program_download",
                     "deploy", "plc_program_download", "plc_program_download", "ipc_reboot", "network_outage"]
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
    assert reader.execute("SELECT count(*) FROM data_windows").fetchone()[0] == 15
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


def test_plc_program_download_window_has_the_exact_boundaries_from_the_data(admin):
    """k7c A-1: pierwszy i ostatni wiersz link_status = 1 (24.11.2026, 14:25:03.390 – 14:25:20.392 UTC)."""
    start, end, description, exclude = admin.execute(
        "SELECT start_time, end_time, description, exclude_from_analytics FROM data_windows WHERE kind = 'plc_program_download' ORDER BY start_time LIMIT 1").fetchone()
    assert start.isoformat() == "2026-11-24T14:25:03.390000+00:00" and end.isoformat() == "2026-11-24T14:25:20.392000+00:00"
    assert description == "Download programu PLC (Grzegorz), reset liczników FB" and exclude is True


def test_plc1_download_window_of_25_november_has_the_exact_boundaries_from_the_data(admin):
    """E2-PLC2 (migracja 006): pierwszy i ostatni wiersz link_status != 0 (25.11.2026, 08:16:10.574 – 08:16:18.577 UTC)."""
    rows = admin.execute(
        "SELECT start_time, end_time, description, exclude_from_analytics FROM data_windows "
        "WHERE kind = 'plc_program_download' ORDER BY start_time").fetchall()
    assert len(rows) == 3
    start, end, description, exclude = rows[1]
    assert start.isoformat() == "2026-11-25T08:16:10.574000+00:00" and end.isoformat() == "2026-11-25T08:16:18.577000+00:00"
    assert "PLC-1" in description and exclude is True


def test_plc2_download_window_of_25_november_has_the_exact_boundaries_from_the_data(admin):
    """E2-PLC2 krok 4 (migracja 010): pierwszy i ostatni wiersz link_status != 0 przy przełączeniu na mapę v2 (10:43:01.518 – 10:43:09.521 UTC)."""
    rows = admin.execute(
        "SELECT start_time, end_time, description, exclude_from_analytics FROM data_windows "
        "WHERE kind = 'plc_program_download' ORDER BY start_time").fetchall()
    start, end, description, exclude = rows[2]
    assert start.isoformat() == "2026-11-25T10:43:01.518000+00:00" and end.isoformat() == "2026-11-25T10:43:09.521000+00:00"
    assert "PLC-2" in description and "v2" in description and exclude is True


def test_ipc_reboot_window_matches_the_measured_gap(admin):
    start, end = admin.execute("SELECT start_time, end_time FROM data_windows WHERE kind = 'ipc_reboot'").fetchone()
    assert start.isoformat().startswith("2026-11-25T12:03:47.557")
    assert end.isoformat().startswith("2026-11-25T12:04:24.705")


def test_cable_move_window_matches_the_measured_gap(admin):
    """E3-k7a: przełożenie kabla IPC do enp2s0 27.11 (013)."""
    start, end, exclude = admin.execute("SELECT start_time, end_time, exclude_from_analytics FROM data_windows "
                                        "WHERE kind = 'network_outage'").fetchone()
    assert start.isoformat().startswith("2026-11-27T19:49:22.16") and end.isoformat().startswith("2026-11-27T19:49:35.155")
    assert exclude is True



@pytest.mark.parametrize("kind, exclude", [("sim_reset", True), ("sim_backfill", False)])
def test_simulator_window_kinds_are_accepted_and_visible(admin, reader, kind, exclude):
    """E3-k4: okna symulatora (K2R-D2 wymiana łożyska – wyłączone z analityki; K4-U3 wgrywanie historii – tylko adnotacja).
    Wstawiane tu w bazie testowej; na produkcji każde okno to osobna migracja wg szablonu w docs/ops (sekcja Symulator)."""
    admin.execute("INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) "
                  "VALUES ('2027-03-01 06:00:00+00', '2027-03-01 06:01:00+00', %s, 'test', %s)", (kind, exclude))
    rows = reader.execute(ANNOTATION_SQL, {"from": "2027-03-01 05:00:00+00", "to": "2027-03-01 07:00:00+00"}).fetchall()
    assert [r[2] for r in rows] == [kind]
    assert reader.execute("SELECT exclude_from_analytics FROM data_windows WHERE kind = %s", (kind,)).fetchone()[0] is exclude
