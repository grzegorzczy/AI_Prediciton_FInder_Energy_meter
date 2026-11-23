"""Usługa collector w docker-compose.yml: utwardzenie (K3-c), profil live (K3-f), limity i montowanie konfiguracji."""
from __future__ import annotations

import yaml

from dbtools import REPO


def service():
    with open(REPO / "docker-compose.yml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["services"]["collector"]


def test_collector_is_hardened():
    svc = service()
    assert svc["read_only"] is True
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    assert "/tmp" in svc["tmpfs"]


def test_collector_limits_and_restart():
    svc = service()
    assert svc["mem_limit"] == "128m" and svc["memswap_limit"] == "128m"
    assert svc["restart"] == "unless-stopped"


def test_collector_waits_for_broker_but_is_not_started_without_profile():
    svc = service()
    assert svc["profiles"] == ["live"]                      # do k5; potem profil zostaje usunięty
    assert svc["depends_on"]["mosquitto"]["condition"] == "service_healthy"


def test_collector_mounts_config_read_only_and_exposes_no_ports():
    svc = service()
    assert any(v.endswith("/config/devices.yaml:ro") for v in svc["volumes"])
    assert "ports" not in svc


def test_collector_uses_only_the_collector_mqtt_account():
    env = service()["environment"]
    assert "MQTT_COLLECTOR_USER" in env["MQTT_USER"] and "MQTT_COLLECTOR_PASSWORD" in env["MQTT_PASSWORD"]
    assert not any("INGEST" in str(v) or "POSTGRES" in str(v) or "APP_" in str(v) for v in env.values())


def test_dockerfile_runs_as_non_root_with_pinned_base():
    text = (REPO / "services" / "collector" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER collector" in text
    assert "@sha256:" in text
