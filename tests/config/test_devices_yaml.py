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
    assert plc["read"] == {"start": 0, "count": 60}
    assert plc["map_versions"] == [1, 2]
    assert plc["heartbeat_timeout_s"] == 5
    assert plc["poll_interval_s"] > 0


def test_collector_settings_live_in_configuration(cfg):
    """Reguła 3 i K3-g: limity czasowe, ponawianie i nazwy metryk statusów są w configu, nie w kodzie."""
    plc = cfg["plc"]
    assert plc["timeout_s"] == 2.0
    assert plc["reconnect"] == {"initial_s": 1, "max_s": 10}
    assert plc["link_metric"] == "link_status"
    assert plc["source"] in ("real", "sim")
    profile = cfg["profiles"]["finder_7m24"]
    assert profile["status"]["metric"] == "meter_status"
    assert profile["diagnostics"]["error_count"]["metric"] == "meter_error_count"
    assert profile["diagnostics"]["data_age_ms"]["metric"] == "meter_data_age_ms"
    assert profile["diagnostics"]["data_age_ms"]["omit_value"] == 0xFFFFFFFF
    assert profile["diagnostics"]["error_code"]["metric"] == "meter_error_code"   # publikowany tylko przy status != 0
    for name in ("energy_import_wh", "energy_export_wh"):
        assert profile["energy"][name]["resolution_wh"] == 100                    # rozdzielczość licznika (agregaty energii)


def test_status_metric_names_match_database_constraint(cfg):
    pattern = re.compile(r"^[a-z0-9_]+$")
    names = [cfg["plc"]["link_metric"], cfg["profiles"]["finder_7m24"]["status"]["metric"]]
    names += [d["metric"] for d in cfg["profiles"]["finder_7m24"]["diagnostics"].values() if "metric" in d]
    assert all(pattern.match(n) for n in names)


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



# --- E3-k1: sekcja `simulator` (urządzenia sim, własna linia) ----------------------------------------------------------

def test_simulator_section_identity_and_metadata(cfg):
    sim = cfg["simulator"]
    assert sim["site"] == cfg["site"] and sim["line"] == "linia2" and sim["line"] != cfg["line"]       # K0-D3
    assert SEGMENT.match(sim["line"]) and sim["poll_interval_s"] == 1.0 and sim["t_zero"] is None   # t_zero w k7 (U-2)
    devices = sim["devices"]
    assert [d["id"] for d in devices] == ["sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka", "sim_pump_p101"]
    for dev in devices:
        assert dev["id"].startswith("sim_") and SEGMENT.match(dev["id"]) and dev["source"] == "sim", dev
        assert "SYMULACJA" not in dev["name"].upper(), dev                    # znacznik dokłada Grafana z `source` (k6)
        if dev["kind"] == "energy_meter":
            assert dev["phases"] == 3 and dev["energy_resolution_wh"] == 100, dev     # U-1, K0-D8
        else:
            assert dev["kind"] == "pump" and "phases" not in dev and "energy_resolution_wh" not in dev
    assert {d["id"]: d["rated_kw"] for d in devices} == {"sim_pasteryzator": 18, "sim_chlodnia": 11, "sim_mieszalnik": 7.5,
                                                          "sim_pakowaczka": 4, "sim_pump_p101": 11}


def test_ids_unique_across_real_and_simulated_devices(cfg):
    ids = [cfg["plc"]["id"]] + [d["id"] for d in cfg["devices"]] + [d["id"] for d in cfg["simulator"]["devices"]]
    assert len(ids) == len(set(ids))


def test_finder_is_single_phase(cfg):
    assert [d["phases"] for d in cfg["devices"]] == [1]
