"""config/devices.yaml: struktura, spójność rejestrów, decyzja D1 (nazwy tematów MQTT)."""
from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(os.environ.get("REPO_DIR", "/repo"))
SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
TYPE_LEN = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "real32": 2}


@pytest.fixture(scope="module")
def cfg() -> dict:
    with open(REPO / "config" / "devices.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def spans(profile: dict) -> list[tuple[str, int, int]]:
    """(nazwa, początek, długość) wszystkich pól profilu względem bazy bloku."""
    out = [("status", profile["status"]["offset"], 1)]
    for name, item in profile.get("diagnostics", {}).items():
        out.append((name, item["offset"], TYPE_LEN[item["type"]]))
    for name, item in profile["metrics"].items():
        out.append((name, item["offset"], TYPE_LEN[item["type"]]))
    for name, item in profile.get("energy", {}).items():
        out.append((name + ".mantissa", item["mantissa"], 2))
        out.append((name + ".exponent", item["exponent"], 1))
    serial = profile["serial"]
    out.append(("serial", serial["offset"], serial["registers"]))
    return out


def test_d1_site_and_line(cfg):
    assert cfg["site"] == "zaklad1"
    assert cfg["line"] == "linia1"


def test_topic_segments_are_safe(cfg):
    ids = [cfg["plc"]["id"]] + [d["id"] for d in cfg["devices"]]
    for value in [cfg["site"], cfg["line"], *ids]:
        assert SEGMENT.match(value), f"niedozwolony segment tematu MQTT: {value!r}"


def test_ids_unique(cfg):
    ids = [cfg["plc"]["id"]] + [d["id"] for d in cfg["devices"]]
    assert len(ids) == len(set(ids))


def test_plc_connection_follows_contract(cfg):
    plc = cfg["plc"]
    ipaddress.ip_address(plc["host"])
    assert plc["port"] == 502
    assert plc["unit_id"] == 1
    assert plc["function"] == 4, "kontrakt dopuszcza wyłącznie FC04 (odczyt)"
    assert plc["read"] == {"start": 0, "count": 44}
    assert plc["map_version"] == 1
    assert plc["heartbeat_timeout_s"] == 5
    assert plc["poll_interval_s"] > 0


def test_devices_reference_existing_profile(cfg):
    for dev in cfg["devices"]:
        assert dev["profile"] in cfg["profiles"]
        assert dev["source"] in ("real", "sim")
        assert dev["kind"] in ("energy_meter", "pump")
        assert re.match(r"^[A-Z0-9]+$", dev["serial"])


def test_register_layout_is_consistent(cfg):
    read_start = cfg["plc"]["read"]["start"]
    read_end = read_start + cfg["plc"]["read"]["count"]
    header = [
        ("heartbeat", cfg["plc"]["heartbeat"]["offset"], 2),
        ("map_version", cfg["plc"]["map_version_register"]["offset"], 1),
    ]
    taken = {}
    for name, start, length in header:
        for reg in range(start, start + length):
            assert reg not in taken, f"nakładanie: {name} i {taken[reg]}"
            taken[reg] = name

    for dev in cfg["devices"]:
        profile = cfg["profiles"][dev["profile"]]
        base = dev["block_base"]
        for name, offset, length in spans(profile):
            assert offset + length <= profile["block_size"], f"{name} poza blokiem"
            for reg in range(base + offset, base + offset + length):
                assert read_start <= reg < read_end, f"{dev['id']}.{name}: rejestr {reg} poza zapytaniem"
                assert reg not in taken, f"nakładanie rejestrów: {dev['id']}.{name} i {taken[reg]}"
                taken[reg] = f"{dev['id']}.{name}"


def test_metric_names_match_database_constraint(cfg):
    pattern = re.compile(r"^[a-z0-9_]+$")  # to samo ograniczenie co CHECK w measurements
    for profile in cfg["profiles"].values():
        names = list(profile["metrics"]) + list(profile.get("energy", {}))
        for name in names:
            assert pattern.match(name), name
