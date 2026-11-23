"""Usługa ingest w docker-compose.yml: utwardzenie, limity, brak profilu i portów, najmniejsze uprawnienia."""
from __future__ import annotations

import yaml

from dbtools import REPO


def service():
    with open(REPO / "docker-compose.yml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["services"]["ingest"]


def test_ingest_is_hardened():
    svc = service()
    assert svc["read_only"] is True
    assert svc["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in svc["security_opt"]
    assert "/tmp" in svc["tmpfs"]


def test_ingest_limits_and_restart():
    svc = service()
    assert svc["mem_limit"] == "128m" and svc["memswap_limit"] == "128m"
    assert svc["restart"] == "unless-stopped"


def test_ingest_starts_with_the_stack_without_profile_and_has_no_ports():
    svc = service()
    assert "profiles" not in svc and "ports" not in svc
    assert svc["depends_on"]["mosquitto"]["condition"] == "service_healthy"
    assert svc["depends_on"]["timescaledb"]["condition"] == "service_healthy"


def test_ingest_mounts_config_read_only():
    assert any(v.endswith("/config/devices.yaml:ro") for v in service()["volumes"])


def test_ingest_uses_only_its_own_accounts():
    env = service()["environment"]
    assert "MQTT_INGEST_USER" in env["MQTT_USER"] and "MQTT_INGEST_PASSWORD" in env["MQTT_PASSWORD"]
    assert env["DB_USER"] == "app_writer" and "APP_WRITER_PASSWORD" in env["DB_PASSWORD"]
    forbidden = ("COLLECTOR", "POSTGRES_PASSWORD", "APP_READER", "GF_")
    assert not any(any(word in str(v) for word in forbidden) for v in env.values())


def test_ingest_session_settings_match_the_broker():
    env = service()["environment"]
    assert env["INGEST_CLIENT_ID"] == "aip-ingest"
    assert int(env["INGEST_BATCH_MAX"]) <= 100          # max_inflight_messages w mosquitto.conf


def test_batch_size_fits_the_broker_inflight_limit():
    text = (REPO / "config" / "mosquitto" / "mosquitto.conf").read_text(encoding="utf-8")
    inflight = int(next(line.split()[1] for line in text.splitlines() if line.startswith("max_inflight_messages")))
    assert int(service()["environment"]["INGEST_BATCH_MAX"]) <= inflight


def test_dockerfile_non_root_with_pinned_base():
    text = (REPO / "services" / "ingest" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER ingest" in text and "@sha256:" in text
