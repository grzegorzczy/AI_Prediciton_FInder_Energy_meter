"""Wirtualne liczniki energii (trójfazowe, U-1): moc czynna z modelu pracy maszyny i stanu kalendarza, potem elektryka.

Typy modeli (parametry w config/devices.yaml):
- thermostat – regulacja dwustawna w cyklu `cycle_s` z udziałem włączenia `on_fraction`; w fazie wyłączonej grzałki
  obowiązuje `p_idle_kw` (pompy obiegowe i sterowanie pracują, K2-U6), w przerwach też `p_idle_kw`, poza zmianą `p_off_kw`;
- compressor – cykl sprężarki on/off; udział włączenia rośnie z temperaturą otoczenia (`ambient_gain`), wyznaczany na
  początek cyklu, więc cykl jest spójny;
- batch – partie `batch_min` od początku zmiany: rozbieg `ramp_s`, mieszanie do `mix_min`, potem przerwa partii;
- continuous – praca z wolnymi wahaniami ± `swing`.
Elektryka: U = U_nom + wolne wahania + szum; S = P / PF; Q = √(S² − P²) (odbiorniki indukcyjne, Q > 0);
I = S / (3 U) przy `phases: 3` (prąd jednej fazy przy obciążeniu symetrycznym).
"""
from __future__ import annotations

import math

from .calendar import BREAK, OFF, CalendarModel
from .config import SimConfig, SimDevice
from .noise import normal_pair, offset, slow, uniforms

POWER_NOISE = 0.01                 # względny szum mocy (1 %)


class MeterModel:
    def __init__(self, config: SimConfig, device: SimDevice, calendar: CalendarModel) -> None:
        self.config = config
        self.device = device
        self.cal = calendar
        self.p = device.params
        self.key = device.device_id
        if device.model_type == "thermostat":
            self._offset = offset(config.seed, self.key, int(self.p["cycle_s"]))
        elif device.model_type == "compressor":
            self._period = int(round((self.p["on_min"] + self.p["off_min"]) * 60))
            self._offset = offset(config.seed, self.key, self._period)
            self._frac_cache: dict[int, float] = {}

    def _state(self, t: int) -> str:
        if self.device.schedule == "always":
            return "work"
        return self.cal.state(t)

    def model_power(self, t: int) -> tuple[float, float]:
        """Moc czynna modelu [W] bez szumu i współczynnik mocy dla chwili t."""
        p, kind = self.p, self.device.model_type
        state = self._state(t)
        if state == OFF:
            return p["p_off_kw"] * 1000.0, p["pf_off"]
        if kind == "thermostat":
            if state == BREAK:
                return p["p_idle_kw"] * 1000.0, p["pf_idle"]
            cycle = int(p["cycle_s"])
            if (t + self._offset) % cycle < p["on_fraction"] * cycle:
                return p["p_on_kw"] * 1000.0, p["pf_run"]
            return p["p_idle_kw"] * 1000.0, p["pf_idle"]
        if kind == "compressor":
            pos = (t + self._offset) % self._period
            if pos < self._on_fraction(t - pos) * self._period:
                return p["p_on_kw"] * 1000.0, p["pf_run"]
            return p["p_off_kw"] * 1000.0, p["pf_off"]
        if kind == "batch":
            if state == BREAK:
                return p["p_pause_kw"] * 1000.0, p["pf_idle"]
            shift = self.cal.shift_at(t)
            pos = (t - shift[0]) % int(round(p["batch_min"] * 60))
            mix_s, ramp_s = p["mix_min"] * 60, p["ramp_s"]
            if pos < mix_s:
                fraction = min(1.0, pos / ramp_s)
                return (p["p_pause_kw"] + (p["p_mix_kw"] - p["p_pause_kw"]) * fraction) * 1000.0, p["pf_run"]
            return p["p_pause_kw"] * 1000.0, p["pf_idle"]
        # continuous
        if state == BREAK:
            return p["p_idle_kw"] * 1000.0, p["pf_idle"]
        wobble = slow(self.config.seed, self.key + "|load", t, 900.0)
        return p["p_run_kw"] * 1000.0 * (1.0 + p["swing"] * wobble), p["pf_run"]

    def _on_fraction(self, cycle_start: int) -> float:
        cached = self._frac_cache.get(cycle_start)
        if cached is None:
            base = self.p["on_min"] / (self.p["on_min"] + self.p["off_min"])
            cached = min(0.95, max(0.05, base * (1.0 + self.p["ambient_gain"] * self.cal.ambient_anomaly(cycle_start))))
            if len(self._frac_cache) > 4096:
                self._frac_cache.clear()
            self._frac_cache[cycle_start] = cached
        return cached

    def power(self, t: int) -> tuple[float, float, tuple[float, float]]:
        """Opublikowana moc czynna [W, zaokrąglona do 1 W], PF i dwie liczby N(0,1) tej sekundy (dla napięcia)."""
        model_w, pf = self.model_power(t)
        u = uniforms(self.config.seed, self.key, t)
        g1, g2 = normal_pair(u[0], u[1])
        return float(round(max(0.0, model_w * (1.0 + POWER_NOISE * g1)))), pf, (g1, g2)

    def sample(self, t: int) -> dict[str, float]:
        active, pf, (_, g2) = self.power(t)
        el = self.config.electrical
        voltage = el.voltage_v + el.voltage_slow_v * slow(self.config.seed, self.key + "|voltage", t, 3600.0) + el.voltage_noise_v * g2
        apparent = active / pf
        reactive = math.sqrt(max(apparent * apparent - active * active, 0.0))
        current = apparent / (self.device.phases * voltage)
        return {
            "active_power": active,
            "reactive_power": float(round(reactive)),
            "voltage": round(voltage, 1),
            "current": round(current, 3),
            "power_factor": round(pf, 3),
        }
