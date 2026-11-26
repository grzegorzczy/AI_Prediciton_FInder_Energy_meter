"""Jedno wejście dla trybu na żywo (k3) i historii (k5): wartości wszystkich metryk urządzeń sim w chwili t."""
from __future__ import annotations

from datetime import datetime

from .calendar import CalendarModel
from .config import SimConfig
from .daycache import DayCache, cache_key
from .energy import EnergyCounter
from .meters import MeterModel
from .pump import PumpModel

# Kolejność i jednostki publikowanych metryk (29 = 4 liczniki × 6 + pompa × 5); nazwy jak w bazie, jednostki po angielsku (K2-U5).
METER_METRICS = (("active_power", "W"), ("reactive_power", "var"), ("voltage", "V"), ("current", "A"),
                 ("power_factor", ""), ("energy_import_wh", "Wh"))
PUMP_METRICS = (("vibration_rms", "mm/s"), ("bearing_temperature", "°C"), ("motor_current", "A"), ("flow", "m³/h"),
                ("speed", "rpm"))


class Simulator:
    def __init__(self, config: SimConfig, cache_path: str | None = None) -> None:
        config.require_meter_anchor()                    # K1-U2 / K2R-D1: bez dat nie liczymy niczego
        for dev in config.devices:
            if dev.kind == "pump":
                config.require_bearing_installed_at(dev)
        self.config = config
        self.calendar = CalendarModel(config.calendar, config.ambient)
        self.cache = DayCache(cache_path, cache_key(config))
        self.meters: dict[str, tuple[MeterModel, EnergyCounter]] = {}
        self.pumps: dict[str, PumpModel] = {}
        for dev in config.devices:
            if dev.kind == "energy_meter":
                meter = MeterModel(config, dev, self.calendar)
                self.meters[dev.device_id] = (meter, EnergyCounter(meter, self.cache))
            else:
                self.pumps[dev.device_id] = PumpModel(config, dev, self.calendar)
        # K2R-D3: ostatnia zapisana doba każdego licznika przeliczona od zera; niezgodność = plik odrzucony
        self.cache.verify(lambda device, day: self.meters[device][1].compute_day(day) if device in self.meters else None)

    def prime(self, t: int) -> None:
        """Start liczników energii w chwili t (sumy dób z pliku albo liczone) i zapis pamięci sum."""
        for _, counter in self.meters.values():
            counter.value_wh(t)
        self.cache.flush()

    @staticmethod
    def _seconds(t: int | datetime) -> int:
        if isinstance(t, datetime):
            if t.tzinfo is None:
                raise ValueError("chwila bez strefy czasowej")
            if t.microsecond:
                raise ValueError("próbki są na pełnych sekundach")
            return int(t.timestamp())
        return int(t)

    def samples_at(self, t: int | datetime, devices: set[str] | None = None) -> list[tuple[str, str, float, str]]:
        """(device_id, metryka, wartość, jednostka) dla chwili t (sekundy UTC od 1970 albo datetime ze strefą)."""
        moment = self._seconds(t)
        out: list[tuple[str, str, float, str]] = []
        for dev_id, (meter, counter) in self.meters.items():
            if devices is not None and dev_id not in devices:
                continue
            values = meter.sample(moment)
            values["energy_import_wh"] = counter.value_wh(moment)
            out.extend((dev_id, metric, values[metric], unit) for metric, unit in METER_METRICS)
        for dev_id, pump in self.pumps.items():
            if devices is not None and dev_id not in devices:
                continue
            values = pump.sample(moment)
            out.extend((dev_id, metric, values[metric], unit) for metric, unit in PUMP_METRICS)
        return out
