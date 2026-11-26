"""Usługa `simulator` w docker-compose.yml (E3-k3): utwardzenie, limity, wolumen, konto MQTT; obraz (Dockerfile)."""
from __future__ import annotations

import yaml

from dbtools import REPO


def compose():
    with open(REPO / "docker-compose.yml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_simulator_service_is_hardened_and_limited():
    svc = compose()["services"]["simulator"]
    assert svc["container_name"] == "aip-simulator" and svc["restart"] == "unless-stopped"
    assert svc["read_only"] is True and svc["cap_drop"] == ["ALL"] and "no-new-privileges:true" in svc["security_opt"]
    assert svc["mem_limit"] == "128m" and svc["memswap_limit"] == "128m"
    assert "/tmp" in svc["tmpfs"] and "ports" not in svc
    assert svc["volumes"] == ["./config/devices.yaml:/config/devices.yaml:ro", "aip_simulator_data:/var/lib/simulator"]
    assert svc["depends_on"] == {"mosquitto": {"condition": "service_healthy"}}
    assert svc["healthcheck"]["test"] == ["CMD", "python", "-m", "simulator.health"]
    env = svc["environment"]
    assert env["MQTT_USER"] == "${MQTT_SIM_USER:-}" and env["MQTT_PASSWORD"] == "${MQTT_SIM_PASSWORD:-}"
    assert env["SIM_BUFFER_MAX"] == "36000" and env["SIM_CACHE"] == "/var/lib/simulator/energy-days.json"
    assert "aip_simulator_data" in compose()["volumes"]


def test_mosquitto_gets_the_optional_simulator_account():
    env = compose()["services"]["mosquitto"]["environment"]
    assert env["MQTT_SIM_USER"] == "${MQTT_SIM_USER:-}" and env["MQTT_SIM_PASSWORD"] == "${MQTT_SIM_PASSWORD:-}"


def test_dockerfile_uses_tzdata_only_and_an_unprivileged_user():
    text = (REPO / "services" / "simulator" / "Dockerfile").read_text(encoding="utf-8")
    assert 'PYTHONTZPATH=""' in text                                   # K2R-U1
    assert "USER simulator" in text and "@sha256:" in text
    requirements = (REPO / "services" / "simulator" / "requirements.txt").read_text(encoding="utf-8")
    assert "tzdata==2025.2" in requirements and "paho-mqtt==2.2.0" in requirements
