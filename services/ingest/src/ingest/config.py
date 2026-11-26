"""Minimalny parser config/devices.yaml dla ingestu: site, line, PLC, urządzenia i urządzenia symulatora (bez układu rejestrów).

Ingest nie potrzebuje rejestrów Modbus, więc ma własny, mały parser zamiast wspólnej biblioteki z collectorem
(decyzja K4-a); zgodność obu parserów z jednym plikiem pilnują testy. Adres IP PLC nie jest wczytywany do bazy.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
KINDS = ("plc", "energy_meter", "pump")        # zgodne z CHECK w db/migrations/001_core.sql
SIM_KINDS = ("energy_meter", "pump")           # rodzaje urządzeń sekcji `simulator` (E3-k1)
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
    site: str = ""                 # zakład i linia urządzenia (temat MQTT i kolumny devices); E3-k1: na urządzenie
    line: str = ""


@dataclass(frozen=True)
class IngestConfig:
    site: str                      # zakład i linia prawdziwego sprzętu (PLC i `devices`)
    line: str
    devices: dict[str, DeviceSpec]

    def site_lines(self) -> list[tuple[str, str]]:
        """Pary (zakład, linia) występujące w configu, w kolejności pierwszego wystąpienia."""
        return list(dict.fromkeys((spec.site, spec.line) for spec in self.devices.values()))


def _need(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"brak pola '{key}' w sekcji {where}")
    return mapping[key]


def _energy_resolution(profile: Any, where: str, key: str = "resolution_wh") -> float | None:
    """Rozdzielczość liczników energii profilu (`resolution_wh` dla Wh, `resolution_varh` dla varh); liczniki tego samego
    rodzaju muszą ją podawać identycznie albo wcale."""
    if not isinstance(profile, dict):
        return None
    values = {float(item[key]) for item in (profile.get("energy") or {}).values()
              if isinstance(item, dict) and key in item}
    if len(values) > 1:
        raise ConfigError(f"{where}: różne {key} dla liczników energii: {sorted(values)}")
    return values.pop() if values else None


def _site_line(mapping: Any, where: str) -> tuple[str, str]:
    site = str(_need(mapping, "site", where))
    line = str(_need(mapping, "line", where))
    for label, value in (("site", site), ("line", line)):
        if not SEGMENT.match(value):
            raise ConfigError(f"{where}: {label}='{value}': dozwolone tylko ASCII, cyfry, '_' i '-'")
    return site, line


def load_config_dict(raw: dict) -> IngestConfig:
    site, line = _site_line(raw, "główna")

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
        meta={"map_versions": [int(v) for v in _need(plc, "map_versions", "plc")]},        # bez adresu IP
        site=site, line=line,
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
        reactive = _energy_resolution(profiles.get(profile_name), f"profiles.{profile_name}", "resolution_varh")
        if reactive is not None:
            meta["reactive_resolution_varh"] = reactive
        if "phases" in dev:                       # E3-k1 (U-1): liczba faz licznika (Finder: 1), dla etapu 4
            meta["phases"] = _phases(dev["phases"], f"devices.{dev_id}")
        add(DeviceSpec(
            device_id=dev_id, name=str(dev.get("name", dev_id)), kind=str(_need(dev, "kind", f"devices.{dev_id}")),
            source=str(_need(dev, "source", f"devices.{dev_id}")), meta=meta, site=site, line=line,
        ))
    _add_simulator(raw.get("simulator"), add, (site, line))
    return IngestConfig(site=site, line=line, devices=devices)


def _phases(value: Any, where: str) -> int:
    # `type(...) is int`: YAML-owe `true` (bool) i `3.0` (float) nie są liczbą faz (przegląd k1, ustalenie 5)
    if type(value) is not int or value not in (1, 3):
        raise ConfigError(f"{where}: phases={value!r}, dozwolone 1 lub 3")
    return value


def _positive(value: Any, where: str, key: str) -> float:
    """Dodatnia, skończona liczba z configu; zły typ lub zakres = ConfigError (ingest kończy się czytelnym komunikatem)."""
    if isinstance(value, bool):
        raise ConfigError(f"{where}: {key}={value!r} nie jest liczbą")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where}: {key}={value!r} nie jest liczbą") from None
    if not math.isfinite(number) or number <= 0:
        raise ConfigError(f"{where}: {key}={value!r}, wymagana liczba dodatnia")
    return number


def _add_simulator(section: Any, add, real_site_line: tuple[str, str]) -> None:
    """Urządzenia symulatora (E3-k1): własny zakład i linia (dane sim tylko w swojej linii, K0-D3), zawsze `source: sim`.
    Brak sekcji = brak urządzeń sim (zachowanie sprzed etapu 3). Parametry modeli czyta symulator (k2), nie ingest."""
    if section is None:
        return
    if not isinstance(section, dict):
        raise ConfigError("simulator: oczekiwano słownika")
    site, line = _site_line(section, "simulator")
    if (site, line) == real_site_line:                     # K0-D3 wymuszone w kodzie, nie tylko w teście pliku (przegląd k1)
        raise ConfigError(f"simulator: zakład/linia '{site}/{line}' muszą być inne niż linia prawdziwego sprzętu")
    poll_interval = section.get("poll_interval_s")
    if poll_interval is not None:
        poll_interval = _positive(poll_interval, "simulator", "poll_interval_s")
    for dev in _need(section, "devices", "simulator") or []:
        dev_id = str(_need(dev, "id", "simulator.devices"))
        where = f"simulator.devices.{dev_id}"
        kind = str(_need(dev, "kind", where))
        if kind not in SIM_KINDS:
            raise ConfigError(f"{where}: rodzaj '{kind}' niedozwolony dla symulatora ({', '.join(SIM_KINDS)})")
        source = str(_need(dev, "source", where))
        if source != "sim":
            raise ConfigError(f"{where}: source='{source}', urządzenie symulatora musi mieć source: sim")
        meta: dict[str, Any] = {}
        if poll_interval is not None:
            meta["poll_interval_s"] = poll_interval
        if kind == "energy_meter":                         # U-1, K0-D8: liczba faz i rozdzielczość wymagane dla etapu 4
            meta["energy_resolution_wh"] = _positive(_need(dev, "energy_resolution_wh", where), where, "energy_resolution_wh")
            meta["phases"] = _phases(_need(dev, "phases", where), where)
        else:
            for key in ("phases", "energy_resolution_wh"):
                if key in dev:
                    raise ConfigError(f"{where}: {key} nie dotyczy pompy (pompa nie publikuje energii, K0-D9)")
        if "rated_kw" in dev:
            meta["rated_kw"] = _positive(dev["rated_kw"], where, "rated_kw")
        add(DeviceSpec(device_id=dev_id, name=str(dev.get("name", dev_id)), kind=kind, source=source, meta=meta,
                       site=site, line=line))


def load_config(path: str | Path) -> IngestConfig:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"nie można wczytać {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: oczekiwano słownika na najwyższym poziomie")
    return load_config_dict(raw)
