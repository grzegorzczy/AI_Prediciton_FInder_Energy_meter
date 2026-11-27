"""Provisioning, uprawnienia źródła danych i dostęp do Grafany (k7)."""
from __future__ import annotations

import time

import pytest

from grafana_support import api, dashboards, ds_query


def test_dashboards_are_provisioned_into_the_folder(grafana_data):
    status, found = api("GET", "/api/search?type=dash-db")
    assert status == 200
    assert {d["uid"] for d in found} == {"aip-przeglad", "aip-na-zywo", "aip-jakosc", "aip-energia", "aip-diagnostyka",
                                         "aip-flota", "aip-pompa"}
    assert {d["folderTitle"] for d in found} == {"AI Predykcja"}


def test_home_dashboard_is_the_overview(grafana_data):
    status, home = api("GET", "/api/dashboards/home")
    assert status == 200
    assert home["dashboard"]["uid"] == "aip-przeglad" and home["dashboard"]["title"] == "Przegląd"


def test_datasource_is_app_reader_with_a_small_pool(grafana_data):
    status, source = api("GET", "/api/datasources/uid/aip-timescaledb")
    assert status == 200
    assert source["user"] == "app_reader"
    assert source["jsonData"]["maxOpenConns"] == 5 and source["jsonData"]["maxIdleConns"] == 2
    assert source["jsonData"]["timescaledb"] is True
    assert source["readOnly"] is True                       # edytowalność wyłączona (provisioning)
    assert not source.get("password")


def test_datasource_connects(grafana_data):
    status, health = api("GET", "/api/datasources/uid/aip-timescaledb/health")
    assert status == 200 and health["status"] == "OK", health


@pytest.mark.parametrize("sql", [
    "INSERT INTO data_windows (start_time, end_time, kind, description) VALUES (now(), now(), 'x', 'y')",
    "DELETE FROM measurements",
    "UPDATE devices SET name = 'x'",
    "CREATE TABLE zz_test (a int)",
    "DROP TABLE data_windows",
    "CALL refresh_continuous_aggregate('energy_1m', NULL, NULL)",
])
def test_writes_through_the_datasource_are_rejected(grafana_data, sql):
    now = time.time()
    result = ds_query(sql, "table", now - 60, now)
    assert result["error"], f"zapis przez źródło danych nie został odrzucony: {sql}"


def test_device_variable_lists_both_meters(grafana_data):
    now = time.time()
    sql = "SELECT device_id AS __value, name AS __text FROM devices WHERE kind = 'energy_meter' AND enabled ORDER BY 1"
    result = ds_query(sql, "table", now - 60, now)
    assert not result["error"]
    values = result["frames"][0]["data"]["values"]
    assert values[0] == ["finder_7m24_1", "finder_7m24_2"] and values[1] == ["Licznik 1", "Licznik 2"]


def test_device_variable_query_in_dashboards_is_the_same(grafana_data):
    """Lista urządzeń: wartość device_id, etykieta z dopiskiem SYMULACJA z devices.source (E3-k6, S10)."""
    label = "name || CASE WHEN source = 'sim' THEN ' (SYMULACJA)' ELSE '' END"
    for name, dash in dashboards().items():
        variable = next((v for v in dash["templating"]["list"] if v["type"] == "query"), None)
        if variable is None:                                  # „Flota”: wszystkie liczniki naraz, bez listy urządzeń
            continue
        assert variable["query"].startswith(f"SELECT device_id AS __value, {label} AS __text FROM devices"), name


def test_annotation_query_returns_the_known_windows(grafana_data):
    sql = dashboards()["przeglad"]["annotations"]["list"][0]["target"]["rawSql"]
    start = time.mktime(time.strptime("2026-11-23 22:30:00", "%Y-%m-%d %H:%M:%S")) - time.timezone
    result = ds_query(sql, "table", start, start + 40 * 60)
    assert not result["error"], result["error"]
    tags = result["frames"][0]["data"]["values"][2]
    assert tags == ["collector_start", "calm_window", "mqtt_broker_restart", "collector_stopped", "rs485_break",
                    "plc_lan1_unplugged", "plc_program_stop"]


def test_anonymous_access_and_signup_are_rejected(grafana_data):
    assert api("GET", "/api/health", auth=False)[0] == 200
    for path in ("/api/search", "/api/dashboards/uid/aip-przeglad", "/api/user", "/api/datasources", "/api/dashboards/home"):
        assert api("GET", path, auth=False)[0] == 401, path
    assert api("POST", "/api/user/signup", {"email": "a@b.c", "name": "x", "password": "yyyyyyyy"}, auth=False)[0] in (401, 403, 404)
    assert api("POST", "/api/ds/query", {"queries": []}, auth=False)[0] == 401
