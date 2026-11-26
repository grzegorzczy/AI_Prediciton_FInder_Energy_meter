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


SIM_IDS = {"sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka", "sim_pump_p101"}


def test_sync_creates_plc_and_meter(pg, migrated_db, writer_store, config):
    upserted, disabled = writer_store.sync_devices(config)
    assert (upserted, disabled) == (7, 0)
    rows = devices(pg, migrated_db)
    assert set(rows) == {"plc-01", "finder_7m24_1"} | SIM_IDS
    name, site, line, kind, source, enabled, meta = rows["plc-01"]
    assert (site, line, kind, source, enabled) == ("zaklad1", "linia1", "plc", "real", True)    # U1
    assert meta == {"map_versions": [1, 2]}
    _, _, _, kind, source, enabled, meta = rows["finder_7m24_1"]
    assert (kind, source, enabled) == ("energy_meter", "real", True)
    assert meta == {"profile": "finder_7m24", "block_base": 10, "serial": "F0183363",
                    "poll_interval_s": 1.0, "energy_resolution_wh": 100.0, "reactive_resolution_varh": 100.0, "phases": 1}
    assert rows["finder_7m24_1"][1:3] == ("zaklad1", "linia1")


def test_simulated_devices_are_stored_with_their_own_line(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    rows = devices(pg, migrated_db)
    for dev_id in SIM_IDS:
        name, site, line, kind, source, enabled, meta = rows[dev_id]
        assert (site, line, source, enabled) == ("zaklad1", "linia2", "sim", True), dev_id
        assert kind == ("pump" if dev_id == "sim_pump_p101" else "energy_meter")
    assert rows["sim_chlodnia"][0] == "Agregat chłodniczy" and rows["sim_chlodnia"][6]["phases"] == 3


def test_real_rows_are_unchanged_by_the_simulator_section_except_finder_phases(pg, migrated_db, writer_store, make_config):
    """Regresja: wiersze PLC i Findera z configiem bez sekcji `simulator` i z nią są identyczne (wszystkie kolumny).
    Różnicę metadanych Findera względem stanu sprzed k1 (wyłącznie `phases`) sprawdza test loadera."""
    writer_store.sync_devices(make_config(lambda raw: raw.pop("simulator")))
    before = devices(pg, migrated_db)
    assert set(before) == {"plc-01", "finder_7m24_1"}
    writer_store.sync_devices(make_config())
    after = devices(pg, migrated_db)
    assert {k: after[k] for k in before} == before


def test_ip_address_is_not_stored(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    with admin_connect(pg, migrated_db) as conn:
        text = conn.execute("SELECT string_agg(meta::text || name, ' ') FROM devices").fetchone()[0]
    assert "192.168" not in text


def test_second_sync_changes_nothing(pg, migrated_db, writer_store, config):
    writer_store.sync_devices(config)
    before = devices(pg, migrated_db)
    assert writer_store.sync_devices(config) == (7, 0)
    assert devices(pg, migrated_db) == before


def test_device_removed_from_config_is_disabled_and_restored_later(pg, migrated_db, writer_store, make_config):
    full = make_config()
    writer_store.sync_devices(full)
    only_plc = make_config(lambda raw: raw["devices"].clear())
    upserted, disabled = writer_store.sync_devices(only_plc)
    assert (upserted, disabled) == (6, 1)
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



def test_simulated_device_removed_from_config_is_disabled_and_real_ones_stay(pg, migrated_db, writer_store, make_config):
    writer_store.sync_devices(make_config())
    without_pump = make_config(lambda raw: raw["simulator"]["devices"].pop())
    assert writer_store.sync_devices(without_pump) == (6, 1)
    rows = devices(pg, migrated_db)
    assert rows["sim_pump_p101"][5] is False
    assert all(rows[k][5] is True for k in rows if k != "sim_pump_p101")



def test_removing_the_whole_simulator_section_disables_all_simulated_devices(pg, migrated_db, writer_store, make_config):
    writer_store.sync_devices(make_config())
    assert writer_store.sync_devices(make_config(lambda raw: raw.pop("simulator"))) == (2, 5)
    rows = devices(pg, migrated_db)
    assert {k for k, r in rows.items() if r[5] is False} == SIM_IDS
    assert rows["plc-01"][5] is True and rows["finder_7m24_1"][5] is True
