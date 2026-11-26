"""Wczytanie i walidacja sekcji `simulator` z config/devices.yaml.

Parser jest niezależny od ingestu (jak parsery collectora i ingestu, decyzja K4-a); zgodność z ingestem pilnują testy.
Wszystkie wartości to parametry symulacji, nie fakty o maszynach. Brak lub zły parametr = ConfigError z polskim
komunikatem (usługa ma się wtedy zatrzymać, a nie zgadywać).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
SCHEDULES = ("shifts", "always")

# Parametry wymagane dla każdego typu modelu (wszystkie dodatnie poza wymienionymi niżej jako ułamki).
MODEL_PARAMS: dict[str, tuple[str, ...]] = {
    "thermostat": ("cycle_s", "on_fraction", "p_on_kw", "p_idle_kw", "p_off_kw", "pf_run", "pf_idle", "pf_off"),
    "compressor": ("on_min", "off_min", "ambient_gain", "p_on_kw", "p_off_kw", "pf_run", "pf_off"),
    "batch": ("batch_min", "mix_min", "ramp_s", "p_mix_kw", "p_pause_kw", "p_off_kw", "pf_run", "pf_idle", "pf_off"),
    "continuous": ("p_run_kw", "swing", "p_idle_kw", "p_off_kw", "pf_run", "pf_idle", "pf_off"),
    "pump": ("speed_rpm", "flow_m3_h", "current_a", "vibration_good_mm_s", "vibration_end_mm_s", "bearing_good_c",
             "bearing_end_c", "warmup_tau_min", "cooldown_tau_min"),
}
FRACTIONS = {"on_fraction", "swing", "ambient_gain"}         # ułamki: 0 < x < 1 (ambient_gain: 0 <= x < 1)
POWER_FACTORS = {"pf_run", "pf_idle", "pf_off"}               # 0 < PF <= 1
METER_KINDS = {"thermostat", "compressor", "batch", "continuous"}

T_ZERO_MISSING = ("simulator.t_zero nie jest ustawione: tryb na żywo i historia nie wystartują; "
                  "datę ustala wdrożenie (k7), np. t_zero: \"2026-12-01T00:00:00Z\"")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Shift:
    days: frozenset[int]          # ISO: 1 = poniedziałek … 7 = niedziela
    start_min: int                # minuty od północy czasu lokalnego
    end_min: int


@dataclass(frozen=True)
class Break:
    start_min: int
    minutes: int


@dataclass(frozen=True)
class Calendar:
    timezone: ZoneInfo
    shifts: tuple[Shift, ...]
    breaks: tuple[Break, ...]
    holidays: frozenset[date]


@dataclass(frozen=True)
class Ambient:
    mean_c: float
    swing_c: float
    warmest_hour: float


@dataclass(frozen=True)
class Electrical:
    voltage_v: float
    voltage_slow_v: float
    voltage_noise_v: float


@dataclass(frozen=True)
class History:
    meter_days: int
    pump_step_s: int


@dataclass(frozen=True)
class Degradation:
    days_total: float
    history_progress: float
    shape_k: float


@dataclass(frozen=True)
class SimDevice:
    device_id: str
    kind: str                      # energy_meter | pump
    model_type: str
    schedule: str
    params: dict[str, float] = field(default_factory=dict)
    energy_start_wh: float | None = None
    energy_resolution_wh: float | None = None
    phases: int | None = None


@dataclass(frozen=True)
class SimConfig:
    site: str
    line: str
    poll_interval_s: float
    t_zero: datetime | None
    seed: int
    calendar: Calendar
    ambient: Ambient
    electrical: Electrical
    history: History
    degradation: Degradation
    devices: tuple[SimDevice, ...]

    def require_t_zero(self) -> datetime:
        """K1-U2: bez daty nie liczymy postępu degradacji ani kotwicy licznika (żadnego podstawiania „teraz”)."""
        if self.t_zero is None:
            raise ConfigError(T_ZERO_MISSING)
        return self.t_zero

    def device(self, device_id: str) -> SimDevice:
        for dev in self.devices:
            if dev.device_id == device_id:
                return dev
        raise KeyError(device_id)


def _need(mapping: Any, key: str, where: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"brak pola '{key}' w sekcji {where}")
    return mapping[key]


def _number(value: Any, where: str, key: str, *, positive: bool = True, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ConfigError(f"{where}: {key}={value!r} nie jest liczbą")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where}: {key}={value!r} nie jest liczbą") from None
    if not math.isfinite(number):
        raise ConfigError(f"{where}: {key}={value!r} nie jest liczbą skończoną")
    if positive and (number < 0 or (number == 0 and not allow_zero)):
        raise ConfigError(f"{where}: {key}={value!r}, wymagana liczba {'nieujemna' if allow_zero else 'dodatnia'}")
    return number


def _int(value: Any, where: str, key: str) -> int:
    if type(value) is not int or value <= 0:
        raise ConfigError(f"{where}: {key}={value!r}, wymagana dodatnia liczba całkowita")
    return value


def _hhmm(value: Any, where: str) -> int:
    if not isinstance(value, str) or not HHMM.match(value):
        raise ConfigError(f"{where}: godzina {value!r}, wymagany format HH:MM")
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _t_zero(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):            # YAML sam rozpoznaje znaczniki czasu
        moment = value
    elif isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ConfigError(f"simulator.t_zero={value!r} nie jest datą ISO 8601") from None
    else:
        raise ConfigError(f"simulator.t_zero={value!r} nie jest datą ISO 8601")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ConfigError(f"simulator.t_zero={value!r} bez strefy czasowej (np. końcówka Z dla UTC)")
    if moment.microsecond or moment.second:
        raise ConfigError(f"simulator.t_zero={value!r}: wymagana pełna minuta")
    return moment


def _calendar(raw: Any) -> Calendar:
    where = "simulator.calendar"
    name = str(_need(raw, "timezone", where))
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"{where}: nieznana strefa czasowa '{name}'") from None
    shifts = []
    for item in _need(raw, "shifts", where) or []:
        days = _need(item, "days", f"{where}.shifts")
        if not isinstance(days, list) or not days or any(type(d) is not int or not 1 <= d <= 7 for d in days):
            raise ConfigError(f"{where}.shifts: days={days!r}, wymagane dni ISO 1-7")
        start, end = _hhmm(_need(item, "start", f"{where}.shifts"), f"{where}.shifts"), _hhmm(_need(item, "end", f"{where}.shifts"), f"{where}.shifts")
        if end <= start:
            raise ConfigError(f"{where}.shifts: koniec zmiany przed początkiem (zmiany przez północ nie są obsługiwane)")
        shifts.append(Shift(frozenset(days), start, end))
    if not shifts:
        raise ConfigError(f"{where}: brak zmian")
    covered = [d for s in shifts for d in s.days]
    if len(covered) != len(set(covered)):
        raise ConfigError(f"{where}: dzień tygodnia w więcej niż jednej zmianie")
    breaks = []
    for item in raw.get("breaks") or []:
        start = _hhmm(_need(item, "start", f"{where}.breaks"), f"{where}.breaks")
        breaks.append(Break(start, _int(_need(item, "minutes", f"{where}.breaks"), f"{where}.breaks", "minutes")))
    holidays = set()
    for item in raw.get("holidays") or []:
        try:
            holidays.add(item if isinstance(item, date) else date.fromisoformat(str(item)))
        except ValueError:
            raise ConfigError(f"{where}.holidays: {item!r} nie jest datą YYYY-MM-DD") from None
    return Calendar(zone, tuple(shifts), tuple(sorted(breaks, key=lambda b: b.start_min)), frozenset(holidays))


def _device(dev: Any, poll: float) -> SimDevice:
    dev_id = str(_need(dev, "id", "simulator.devices"))
    where = f"simulator.devices.{dev_id}"
    if not SEGMENT.match(dev_id):
        raise ConfigError(f"{where}: niedozwolone znaki w id")
    kind = str(_need(dev, "kind", where))
    model = _need(dev, "model", where)
    model_type = str(_need(model, "type", f"{where}.model"))
    if model_type not in MODEL_PARAMS:
        raise ConfigError(f"{where}.model: nieznany typ '{model_type}' ({', '.join(MODEL_PARAMS)})")
    if (kind == "pump") != (model_type == "pump") or kind not in ("energy_meter", "pump"):
        raise ConfigError(f"{where}: model '{model_type}' nie pasuje do rodzaju '{kind}'")
    schedule = str(_need(model, "schedule", f"{where}.model"))
    if schedule not in SCHEDULES:
        raise ConfigError(f"{where}.model: schedule='{schedule}', dozwolone {', '.join(SCHEDULES)}")
    params: dict[str, float] = {}
    for key in MODEL_PARAMS[model_type]:
        value = _need(model, key, f"{where}.model")
        if key in FRACTIONS:
            number = _number(value, f"{where}.model", key, allow_zero=(key == "ambient_gain"))
            if number >= 1:
                raise ConfigError(f"{where}.model: {key}={value!r}, wymagany ułamek < 1")
        elif key in POWER_FACTORS:
            number = _number(value, f"{where}.model", key)
            if number > 1:
                raise ConfigError(f"{where}.model: {key}={value!r}, współczynnik mocy w (0, 1]")
        else:
            number = _number(value, f"{where}.model", key)
        params[key] = number
    unknown = set(model) - set(MODEL_PARAMS[model_type]) - {"type", "schedule"}
    if unknown:
        raise ConfigError(f"{where}.model: nieznane parametry {sorted(unknown)}")
    if model_type in ("batch", "pump") and schedule != "shifts":
        raise ConfigError(f"{where}.model: typ '{model_type}' wymaga schedule: shifts (liczy od początku zmiany)")
    if model_type == "batch" and params["mix_min"] >= params["batch_min"]:
        raise ConfigError(f"{where}.model: mix_min musi być krótsze niż batch_min")
    if model_type == "batch" and params["ramp_s"] >= params["mix_min"] * 60:
        raise ConfigError(f"{where}.model: ramp_s musi być krótsze niż mieszanie")
    if model_type == "thermostat" and params["cycle_s"] < 2 * poll:
        raise ConfigError(f"{where}.model: cycle_s za krótki względem okresu próbek")
    if model_type == "pump" and params["vibration_end_mm_s"] <= params["vibration_good_mm_s"]:
        raise ConfigError(f"{where}.model: vibration_end_mm_s musi być większe niż vibration_good_mm_s")
    if model_type == "pump" and params["bearing_end_c"] <= params["bearing_good_c"]:
        raise ConfigError(f"{where}.model: bearing_end_c musi być większe niż bearing_good_c")
    energy_start = resolution = phases = None
    if kind == "energy_meter":
        energy_start = _number(_need(dev, "energy_start_wh", where), where, "energy_start_wh", allow_zero=True)
        resolution = _number(_need(dev, "energy_resolution_wh", where), where, "energy_resolution_wh")
        phases = dev.get("phases")
        if type(phases) is not int or phases not in (1, 3):
            raise ConfigError(f"{where}: phases={phases!r}, dozwolone 1 lub 3")
    return SimDevice(dev_id, kind, model_type, schedule, params, energy_start, resolution, phases)


def load_config_dict(raw: dict) -> SimConfig:
    section = _need(raw, "simulator", "główna")
    if not isinstance(section, dict):
        raise ConfigError("simulator: oczekiwano słownika")
    site, line = str(_need(section, "site", "simulator")), str(_need(section, "line", "simulator"))
    for label, value in (("site", site), ("line", line)):
        if not SEGMENT.match(value):
            raise ConfigError(f"simulator: {label}='{value}': dozwolone tylko ASCII, cyfry, '_' i '-'")
    poll = _number(_need(section, "poll_interval_s", "simulator"), "simulator", "poll_interval_s")
    if poll != 1.0:
        raise ConfigError("simulator: poll_interval_s musi wynosić 1.0 (widoki energii zakładają próbki co 1 s, K0-D1)")
    seed = section.get("seed")
    if type(seed) is not int:
        raise ConfigError(f"simulator: seed={seed!r}, wymagana liczba całkowita")
    amb = _need(section, "ambient", "simulator")
    ambient = Ambient(_number(_need(amb, "mean_c", "simulator.ambient"), "simulator.ambient", "mean_c", positive=False),
                      _number(_need(amb, "swing_c", "simulator.ambient"), "simulator.ambient", "swing_c", allow_zero=True),
                      _number(_need(amb, "warmest_hour", "simulator.ambient"), "simulator.ambient", "warmest_hour", allow_zero=True))
    if ambient.warmest_hour >= 24:
        raise ConfigError("simulator.ambient: warmest_hour w [0, 24)")
    el = _need(section, "electrical", "simulator")
    electrical = Electrical(*(_number(_need(el, k, "simulator.electrical"), "simulator.electrical", k, allow_zero=(k != "voltage_v"))
                              for k in ("voltage_v", "voltage_slow_v", "voltage_noise_v")))
    hist = _need(section, "history", "simulator")
    history = History(_int(_need(hist, "meter_days", "simulator.history"), "simulator.history", "meter_days"),
                      _int(_need(hist, "pump_step_s", "simulator.history"), "simulator.history", "pump_step_s"))
    deg = _need(section, "degradation", "simulator")
    degradation = Degradation(*(_number(_need(deg, k, "simulator.degradation"), "simulator.degradation", k)
                                for k in ("days_total", "history_progress", "shape_k")))
    if degradation.history_progress >= 1:
        raise ConfigError("simulator.degradation: history_progress musi być < 1")
    devices = tuple(_device(dev, poll) for dev in (_need(section, "devices", "simulator") or []))
    ids = [d.device_id for d in devices]
    if len(ids) != len(set(ids)):
        raise ConfigError("simulator.devices: powtórzone id")
    return SimConfig(site, line, poll, _t_zero(section.get("t_zero")), seed, _calendar(_need(section, "calendar", "simulator")),
                     ambient, electrical, history, degradation, devices)


def load_config(path: str | Path) -> SimConfig:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"nie można wczytać {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: oczekiwano słownika na najwyższym poziomie")
    return load_config_dict(raw)
