"""Minimalny parser config/devices.yaml dla ingestu: site, line, PLC i urządzenia (bez układu rejestrów).

Ingest nie potrzebuje rejestrów Modbus, więc ma własny, mały parser zamiast wspólnej biblioteki z collectorem
(decyzja K4-a); zgodność obu parserów z jednym plikiem pilnują testy. Adres IP PLC nie jest wczytywany do bazy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
KINDS = ("plc", "energy_meter", "pump")        # zgodne z CHECK w db/migrations/001_core.sql
SOURCES = ("real", "sim")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class DeviceSpec:
    device_id: str
    name: str
    kind: str
    source: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestConfig:
    site: str
    line: str
    devices: dict[str, DeviceSpec]


def _need(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"brak pola '{key}' w sekcji {where}")
    return mapping[key]


def _energy_resolution(profile: Any, where: str) -> float | None:
    """Rozdzielczość liczników energii profilu (Wh); wszystkie liczniki profilu muszą ją podawać identycznie albo wcale."""
    if not isinstance(profile, dict):
        return None
    values = {float(item["resolution_wh"]) for item in (profile.get("energy") or {}).values()
              if isinstance(item, dict) and "resolution_wh" in item}
    if len(values) > 1:
        raise ConfigError(f"{where}: różne resolution_wh dla liczników energii: {sorted(values)}")
    return values.pop() if values else None


def load_config_dict(raw: dict) -> IngestConfig:
    site = str(_need(raw, "site", "główna"))
    line = str(_need(raw, "line", "główna"))
    for label, value in (("site", site), ("line", line)):
        if not SEGMENT.match(value):
            raise ConfigError(f"{label}='{value}': dozwolone tylko ASCII, cyfry, '_' i '-'")

    devices: dict[str, DeviceSpec] = {}

    def add(spec: DeviceSpec) -> None:
        if not SEGMENT.match(spec.device_id):
            raise ConfigError(f"id='{spec.device_id}': niedozwolone znaki")
        if spec.device_id in devices:
            raise ConfigError(f"powtórzone id urządzenia: {spec.device_id}")
        if spec.kind not in KINDS:
            raise ConfigError(f"{spec.device_id}: nieznany rodzaj '{spec.kind}'")
        if spec.source not in SOURCES:
            raise ConfigError(f"{spec.device_id}: source='{spec.source}', dozwolone real lub sim")
        devices[spec.device_id] = spec

    plc = _need(raw, "plc", "główna")
    plc_id = str(_need(plc, "id", "plc"))
    add(DeviceSpec(
        device_id=plc_id, name=str(plc.get("name", plc_id)), kind="plc", source=str(plc.get("source", "real")),
        meta={"map_version": int(_need(plc, "map_version", "plc"))},        # bez adresu IP
    ))
    poll_interval = plc.get("poll_interval_s")
    profiles = raw.get("profiles") or {}
    for dev in _need(raw, "devices", "główna"):
        dev_id = str(_need(dev, "id", "devices"))
        profile_name = str(_need(dev, "profile", f"devices.{dev_id}"))
        meta = {"profile": profile_name,
                "block_base": int(_need(dev, "block_base", f"devices.{dev_id}")),
                "serial": str(_need(dev, "serial", f"devices.{dev_id}"))}
        # K6-d: okres próbkowania i rozdzielczość licznika dla widoków energii (reguła 3: nie jako stałe w SQL).
        # Brak wartości = brak klucza w meta (widoki dają NULL, nie domysł).
        if poll_interval is not None:
            meta["poll_interval_s"] = float(poll_interval)
        resolution = _energy_resolution(profiles.get(profile_name), f"profiles.{profile_name}")
        if resolution is not None:
            meta["energy_resolution_wh"] = resolution
        add(DeviceSpec(
            device_id=dev_id, name=str(dev.get("name", dev_id)), kind=str(_need(dev, "kind", f"devices.{dev_id}")),
            source=str(_need(dev, "source", f"devices.{dev_id}")), meta=meta,
        ))
    return IngestConfig(site=site, line=line, devices=devices)


def load_config(path: str | Path) -> IngestConfig:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"nie można wczytać {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: oczekiwano słownika na najwyższym poziomie")
    return load_config_dict(raw)
