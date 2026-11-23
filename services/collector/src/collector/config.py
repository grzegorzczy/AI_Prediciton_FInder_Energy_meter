"""Wczytanie i walidacja config/devices.yaml. Wszystkie adresy, rejestry i nazwy metryk pochodzą stąd (reguła 3)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .codec import TYPE_LENGTH

SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
METRIC = re.compile(r"^[a-z0-9_]+$")
SOURCES = ("real", "sim")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class FieldSpec:
    offset: int
    type: str
    unit: str = ""
    metric: str | None = None          # brak = pole tylko do logu / oceny, nie publikujemy
    omit_value: int | None = None      # wartość wskaźnikowa, przy której metryki nie publikujemy


@dataclass(frozen=True)
class EnergySpec:
    metric: str
    mantissa: int
    exponent: int
    unit: str


@dataclass(frozen=True)
class Profile:
    block_size: int
    status: FieldSpec
    error_code: FieldSpec | None
    error_count: FieldSpec | None
    data_age: FieldSpec | None
    metrics: dict[str, FieldSpec]
    energy: dict[str, EnergySpec]
    serial_offset: int
    serial_registers: int


@dataclass(frozen=True)
class MeterConfig:
    device_id: str
    name: str
    source: str
    profile: Profile
    block_base: int
    serial: str


@dataclass(frozen=True)
class PlcConfig:
    device_id: str
    name: str
    source: str
    host: str
    port: int
    unit_id: int
    read_start: int
    read_count: int
    poll_interval_s: float
    timeout_s: float
    reconnect_initial_s: float
    reconnect_max_s: float
    map_version: int
    map_version_offset: int
    heartbeat_offset: int
    heartbeat_timeout_s: float
    link_metric: str


@dataclass(frozen=True)
class Config:
    site: str
    line: str
    plc: PlcConfig
    meters: tuple[MeterConfig, ...]


def _require(mapping: dict, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"brak pola '{key}' w sekcji {where}")
    return mapping[key]


def _field(raw: dict, where: str, with_unit: bool = False) -> FieldSpec:
    kind = _require(raw, "type", where)
    if kind not in TYPE_LENGTH:
        raise ConfigError(f"{where}: nieznany typ '{kind}'")
    metric = raw.get("metric")
    if metric is not None and not METRIC.match(metric):
        raise ConfigError(f"{where}: niedozwolona nazwa metryki '{metric}'")
    return FieldSpec(
        offset=int(_require(raw, "offset", where)),
        type=kind,
        unit=str(raw.get("unit", "")),
        metric=metric,
        omit_value=raw.get("omit_value"),
    )


def _profile(name: str, raw: dict) -> Profile:
    where = f"profiles.{name}"
    diag = raw.get("diagnostics", {})
    metrics = {}
    for metric, spec in _require(raw, "metrics", where).items():
        if not METRIC.match(metric):
            raise ConfigError(f"{where}: niedozwolona nazwa metryki '{metric}'")
        metrics[metric] = _field(spec, f"{where}.metrics.{metric}")
    energy = {}
    for metric, spec in raw.get("energy", {}).items():
        if not METRIC.match(metric):
            raise ConfigError(f"{where}: niedozwolona nazwa metryki '{metric}'")
        energy[metric] = EnergySpec(
            metric=metric,
            mantissa=int(_require(spec, "mantissa", f"{where}.energy.{metric}")),
            exponent=int(_require(spec, "exponent", f"{where}.energy.{metric}")),
            unit=str(spec.get("unit", "")),
        )
    serial = _require(raw, "serial", where)
    status = _field(_require(raw, "status", where), f"{where}.status")
    if status.metric is None:
        raise ConfigError(f"{where}.status: wymagane pole 'metric' (nazwa metryki statusu licznika)")
    return Profile(
        block_size=int(_require(raw, "block_size", where)),
        status=status,
        error_code=_field(diag["error_code"], f"{where}.diagnostics.error_code") if "error_code" in diag else None,
        error_count=_field(diag["error_count"], f"{where}.diagnostics.error_count") if "error_count" in diag else None,
        data_age=_field(diag["data_age_ms"], f"{where}.diagnostics.data_age_ms") if "data_age_ms" in diag else None,
        metrics=metrics,
        energy=energy,
        serial_offset=int(_require(serial, "offset", f"{where}.serial")),
        serial_registers=int(_require(serial, "registers", f"{where}.serial")),
    )


def _spans(profile: Profile) -> list[tuple[str, int, int]]:
    out = [("status", profile.status.offset, 1)]
    for label, spec in (("error_code", profile.error_code), ("error_count", profile.error_count),
                        ("data_age_ms", profile.data_age)):
        if spec is not None:
            out.append((label, spec.offset, TYPE_LENGTH[spec.type]))
    for name, spec in profile.metrics.items():
        out.append((name, spec.offset, TYPE_LENGTH[spec.type]))
    for name, spec in profile.energy.items():
        out.append((name + ".mantissa", spec.mantissa, 2))
        out.append((name + ".exponent", spec.exponent, 1))
    out.append(("serial", profile.serial_offset, profile.serial_registers))
    return out


def load_config_dict(raw: dict) -> Config:
    site = str(_require(raw, "site", "główna"))
    line = str(_require(raw, "line", "główna"))
    for label, value in (("site", site), ("line", line)):
        if not SEGMENT.match(value):
            raise ConfigError(f"{label}='{value}': dozwolone tylko ASCII, cyfry, '_' i '-' (segment tematu MQTT)")

    p = _require(raw, "plc", "główna")
    function = _require(p, "function", "plc")
    if function != 4:
        raise ConfigError(f"plc.function={function}: kontrakt dopuszcza wyłącznie FC04 (odczyt)")
    read = _require(p, "read", "plc")
    reconnect = _require(p, "reconnect", "plc")
    plc_id = str(_require(p, "id", "plc"))
    plc = PlcConfig(
        device_id=plc_id,
        name=str(p.get("name", plc_id)),
        source=str(p.get("source", "real")),
        host=str(_require(p, "host", "plc")),
        port=int(_require(p, "port", "plc")),
        unit_id=int(_require(p, "unit_id", "plc")),
        read_start=int(_require(read, "start", "plc.read")),
        read_count=int(_require(read, "count", "plc.read")),
        poll_interval_s=float(_require(p, "poll_interval_s", "plc")),
        timeout_s=float(_require(p, "timeout_s", "plc")),
        reconnect_initial_s=float(_require(reconnect, "initial_s", "plc.reconnect")),
        reconnect_max_s=float(_require(reconnect, "max_s", "plc.reconnect")),
        map_version=int(_require(p, "map_version", "plc")),
        map_version_offset=int(_require(_require(p, "map_version_register", "plc"), "offset", "plc.map_version_register")),
        heartbeat_offset=int(_require(_require(p, "heartbeat", "plc"), "offset", "plc.heartbeat")),
        heartbeat_timeout_s=float(_require(p, "heartbeat_timeout_s", "plc")),
        link_metric=str(_require(p, "link_metric", "plc")),
    )
    if plc.source not in SOURCES:
        raise ConfigError(f"plc.source='{plc.source}': dozwolone real lub sim")
    if not SEGMENT.match(plc.device_id) or not METRIC.match(plc.link_metric):
        raise ConfigError("plc.id lub plc.link_metric zawiera niedozwolone znaki")
    if plc.poll_interval_s <= 0 or plc.timeout_s <= 0:
        raise ConfigError("poll_interval_s i timeout_s muszą być dodatnie")

    profiles = {name: _profile(name, spec) for name, spec in _require(raw, "profiles", "główna").items()}

    meters = []
    seen = {plc.device_id}
    taken: dict[int, str] = {}
    read_end = plc.read_start + plc.read_count
    header = [("heartbeat", plc.heartbeat_offset, 2), ("map_version", plc.map_version_offset, 1)]
    for name, start, length in header:
        for reg in range(start, start + length):
            if not plc.read_start <= reg < read_end:
                raise ConfigError(f"plc.{name}: rejestr {reg} poza zapytaniem {plc.read_start}-{read_end - 1}")
            taken[reg] = f"plc.{name}"

    for dev in _require(raw, "devices", "główna"):
        dev_id = str(_require(dev, "id", "devices"))
        if not SEGMENT.match(dev_id):
            raise ConfigError(f"devices.id='{dev_id}': niedozwolone znaki (segment tematu MQTT)")
        if dev_id in seen:
            raise ConfigError(f"powtórzone id urządzenia: {dev_id}")
        seen.add(dev_id)
        profile_name = _require(dev, "profile", f"devices.{dev_id}")
        if profile_name not in profiles:
            raise ConfigError(f"devices.{dev_id}: nieznany profil '{profile_name}'")
        source = str(_require(dev, "source", f"devices.{dev_id}"))
        if source not in SOURCES:
            raise ConfigError(f"devices.{dev_id}.source='{source}': dozwolone real lub sim")
        profile = profiles[profile_name]
        base = int(_require(dev, "block_base", f"devices.{dev_id}"))
        for label, offset, length in _spans(profile):
            if offset + length > profile.block_size:
                raise ConfigError(f"{dev_id}.{label}: poza blokiem ({profile.block_size} rejestrów)")
            for reg in range(base + offset, base + offset + length):
                if not plc.read_start <= reg < read_end:
                    raise ConfigError(f"{dev_id}.{label}: rejestr {reg} poza zapytaniem {plc.read_start}-{read_end - 1}")
                if reg in taken:
                    raise ConfigError(f"nakładanie rejestrów: {dev_id}.{label} i {taken[reg]}")
                taken[reg] = f"{dev_id}.{label}"
        meters.append(MeterConfig(
            device_id=dev_id, name=str(dev.get("name", dev_id)), source=source, profile=profile,
            block_base=base, serial=str(_require(dev, "serial", f"devices.{dev_id}")),
        ))
    return Config(site=site, line=line, plc=plc, meters=tuple(meters))


def load_config(path: str | Path) -> Config:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"nie można wczytać {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: oczekiwano słownika na najwyższym poziomie")
    return load_config_dict(raw)
