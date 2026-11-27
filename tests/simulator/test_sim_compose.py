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



def test_tools_service_has_the_database_and_the_live_service_does_not():
    """K5-D1: hasło bazy (konto tylko do odczytu) tylko w simulator-tools z profilem `tools`; usługa na żywo bez bazy."""
    services = compose()["services"]
    live, tools = services["simulator"], services["simulator-tools"]
    assert not any(key.startswith("DB_") for key in live["environment"])
    assert tools["profiles"] == ["tools"] and tools["restart"] == "no"
    assert tools["environment"]["DB_USER"] == "app_reader" and tools["environment"]["DB_PASSWORD"] == "${APP_READER_PASSWORD:?ustaw w .env}"
    assert tools["environment"]["SIM_CACHE"] == live["environment"]["SIM_CACHE"]                 # K5-U4: wspólna pamięć sum
    assert "aip_simulator_data:/var/lib/simulator" in tools["volumes"] and tools["read_only"] is True
    assert tools["mem_limit"] == "128m" and tools["image"] == live["image"]
