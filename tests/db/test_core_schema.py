"""Schemat rdzenia (001_core): hypertable, kompresja, retencja, ograniczenia, U1 (plc-01)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)


def add_devices(conn):
    conn.execute(
        "INSERT INTO devices (device_id, name, site, line, kind, source) VALUES "
        "('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real'), "
        "('finder_7m24_1', 'Licznik', 'zaklad1', 'linia1', 'energy_meter', 'real')"
    )


def insert_measurement(conn, device="finder_7m24_1", metric="voltage", value=240.4, time=NOW, source="real"):
    return conn.execute(
        "INSERT INTO measurements (time, device_id, metric, value, unit, source) VALUES (%s, %s, %s, %s, 'V', %s)",
        (time, device, metric, value, source),
    )


def test_measurements_is_hypertable_with_one_day_chunks(admin):
    row = admin.execute(
        "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name = 'measurements'"
    ).fetchone()
    assert row is not None and row[0] is True
    interval = admin.execute(
        "SELECT time_interval FROM timescaledb_information.dimensions WHERE hypertable_name = 'measurements'"
    ).fetchone()[0]
    assert interval == timedelta(days=1)


def test_compression_segmentby_and_orderby(admin):
    rows = admin.execute(
        "SELECT attname, segmentby_column_index, orderby_column_index, orderby_asc "
        "FROM timescaledb_information.compression_settings WHERE hypertable_name = 'measurements'"
    ).fetchall()
    segment = {r[0] for r in rows if r[1] is not None}
    order = [(r[0], r[3]) for r in rows if r[2] is not None]
    assert segment == {"device_id", "metric"}
    assert order == [("time", False)]


def test_compression_and_retention_policies(admin):
    jobs = {
        r[0]: r[1]
        for r in admin.execute(
            "SELECT proc_name, config FROM timescaledb_information.jobs WHERE hypertable_name = 'measurements'"
        ).fetchall()
    }
    compression = next(v for k, v in jobs.items() if "compress" in k or "columnstore" in k)
    retention = jobs["policy_retention"]
    assert compression["compress_after"] == "1 day"
    assert retention["drop_after"] == "90 days"


def test_plc_is_a_device_kind(writer):
    """U1: link_status od plc-01 wymaga wpisu w devices."""
    add_devices(writer)
    insert_measurement(writer, device="plc-01", metric="link_status", value=0)
    count = writer.execute("SELECT count(*) FROM measurements WHERE device_id = 'plc-01'").fetchone()[0]
    assert count == 1


def test_unknown_device_is_rejected(writer):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        insert_measurement(writer, device="nieznane")


def test_bad_source_is_rejected(writer):
    add_devices(writer)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_measurement(writer, source="x")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_values_are_rejected(writer, bad):
    add_devices(writer)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_measurement(writer, value=float(bad))


def test_bad_metric_name_is_rejected(writer):
    add_devices(writer)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_measurement(writer, metric="Zła Metryka")


def test_duplicate_is_an_error_but_on_conflict_do_nothing_is_safe(writer):
    add_devices(writer)
    insert_measurement(writer)
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_measurement(writer)
    cur = writer.execute(
        "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
        "VALUES (%s, 'finder_7m24_1', 'voltage', 1, 'V', 'real') ON CONFLICT DO NOTHING", (NOW,))
    assert cur.rowcount == 0
    assert writer.execute("SELECT count(*) FROM measurements").fetchone()[0] == 1


def test_insert_into_compressed_chunk_still_works(admin, writer):
    """Zachowanie wersji przypiętej: późny wiersz i duplikat po kompresji kawałka."""
    add_devices(writer)
    old = datetime.now(timezone.utc) - timedelta(days=3)
    insert_measurement(writer, time=old)
    compressed = admin.execute(
        "SELECT compress_chunk(c) FROM show_chunks('measurements', older_than => interval '1 day') c").fetchall()
    assert compressed, "brak kawałka do skompresowania"

    insert_measurement(writer, time=old + timedelta(seconds=1))          # późny wiersz w skompresowanym kawałku
    cur = writer.execute(
        "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
        "VALUES (%s, 'finder_7m24_1', 'voltage', 1, 'V', 'real') ON CONFLICT DO NOTHING", (old,))
    assert cur.rowcount == 0                                              # duplikat po kompresji pominięty
    assert writer.execute("SELECT count(*) FROM measurements").fetchone()[0] == 2
