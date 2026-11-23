"""Synchronizacja `devices` z config/devices.yaml (U1): upsert, plc-01 jako urządzenie, enabled=false dla usuniętych."""
from __future__ import annotations

import os

import pytest

from dbtools import admin_connect

pytestmark = pytest.mark.skipif("DB_HOST" not in os.environ, reason="wymaga bazy (projekt aip-test)")


def devices(pg, dbname):
    with admin_connect(pg, dbname) as conn:
        return {r[0]: r[1:] for r in conn.execute(
            "SELECT device_id, name, site, line, kind, source, enabled, meta FROM devices ORDER BY 1").fetchall()}


def test_sync_creates_plc_and_meter(pg, migrated_db, writer_store, config):
    upserted, disabled = writer_store.sync_devices(config)
    assert (upserted, disabled) == (2, 0)
    rows = devices(pg, migrated_db)
    assert set(rows) == {"plc-01", "finder_7m24_1"}
    name, site, line, kind, source, enabled, meta = rows["plc-01"]
    assert (site, line, kind, source, enabled) == ("zaklad1", "linia1", "plc", "real", True)    # U1
    assert meta == {"map_version": 1}
    _, _, _, kind, source, enabled, meta = rows["finder_7m24_1"]
    assert (kind, source, enabled) == ("energy_meter", "real", True)
    assert meta == {"profile": "finder_7m24", "block_base": 10, "serial": "F0183363"}


def test_ip_address_is_not_stored(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    with admin_connect(pg, migrated_db) as conn:
        text = conn.execute("SELECT string_agg(meta::text || name, ' ') FROM devices").fetchone()[0]
    assert "192.168" not in text


def test_second_sync_changes_nothing(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    before = devices(pg, migrated_db)
    assert writer_store.sync_devices(config) == (2, 0)
    assert devices(pg, migrated_db) == before


def test_device_removed_from_config_is_disabled_and_restored_later(pg, migrated_db, writer_store, make_config):
    full = make_config()
    writer_store.sync_devices(full)
    only_plc = make_config(lambda raw: raw["devices"].clear())
    upserted, disabled = writer_store.sync_devices(only_plc)
    assert (upserted, disabled) == (1, 1)
    rows = devices(pg, migrated_db)
    assert rows["finder_7m24_1"][5] is False and rows["plc-01"][5] is True       # wiersz nie jest usuwany
    writer_store.sync_devices(full)
    assert devices(pg, migrated_db)["finder_7m24_1"][5] is True


def test_changed_name_and_source_are_updated(pg, migrated_db, writer_store, make_config):
    writer_store.sync_devices(make_config())

    def rename(raw):
        raw["devices"][0]["name"] = "Nowa nazwa"
        raw["devices"][0]["source"] = "sim"

    writer_store.sync_devices(make_config(rename))
    name, _, _, _, source, _, _ = devices(pg, migrated_db)["finder_7m24_1"]
    assert (name, source) == ("Nowa nazwa", "sim")


def test_sync_runs_as_the_writer_role(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    with admin_connect(pg, migrated_db) as conn:
        user = conn.execute(
            "SELECT usename FROM pg_stat_activity WHERE application_name = 'aip-ingest' LIMIT 1").fetchone()
    assert user is not None and user[0] == "app_writer"
