"""Pompa (model `pump`): degradacja łożyska (S5, S6, K0-D2) i wielkości procesowe.

Postęp x(t) = (t − montaż łożyska) / D (K2R-D1): x = 0 w chwili `bearing_installed_at`; przy wdrożeniu montaż = wdrożenie
− 84 dni, więc „teraz” x = 0,70 (K0-D2). Po końcu krzywej (x > 1) wartości zostają jak dla x = 1, a w logu pojawia się raz
WARNING (K2-U1). Wymiana łożyska = nowa `bearing_installed_at` (x = 0) i okno `sim_reset` w `data_windows`; liczniki energii
nietknięte, historii nie wgrywamy ponownie (K2R-D2).
Krzywa przyspieszająca f(x) = (e^{kx} − 1) / (e^k − 1). Drgania RMS = v_dobry + (v_koniec − v_dobry) · f(x) – v_koniec to
koniec zakresu modelu, nie próg alarmowy (progi: etap 5).
Pompa pracuje przez całą zmianę, także w przerwach (cyrkulacja procesowa), a stoi poza zmianami (K2-U4). Prąd silnika
rośnie z degradacją o 5 % przy x = 1 (wariant przyjęty w k2, K2-U4). Temperatura łożyska rośnie razem z drganiami,
nagrzewa się po starcie zmiany (stała warmup_tau_min, od temperatury otoczenia) i stygnie po jej końcu (cooldown_tau_min).
"""
from __future__ import annotations

import logging
import math

from .calendar import CalendarModel
from .config import SimConfig, SimDevice
from .noise import normal_pair, slow, uniforms

LOG = logging.getLogger("simulator.pump")
DAY = 86400.0
CURRENT_WEAR_GAIN = 0.05           # +5 % prądu przy x = 1 (K2-U4)
FLOW_WEAR_LOSS = 0.05              # −5 % przepływu przy x = 1
STANDSTILL_VIBRATION = 0.1         # drgania tła przy postoju [mm/s]


def curve(x: float, k: float) -> float:
    return (math.exp(k * x) - 1.0) / (math.exp(k) - 1.0)


class PumpModel:
    def __init__(self, config: SimConfig, device: SimDevice, calendar: CalendarModel) -> None:
        self.config = config
        self.device = device
        self.cal = calendar
        self.p = device.params
        self.key = device.device_id
        deg = config.degradation
        self.duration = deg.days_total * DAY
        self.t_start = config.require_bearing_installed_at(device).timestamp()
        self.k = deg.shape_k
        self._warned_end = False

    def progress(self, t: float) -> float:
        """Postęp degradacji w [0, 1]; powyżej końca krzywej obcięty do 1 (K2-U1)."""
        x = (t - self.t_start) / self.duration
        if x > 1.0:
            if not self._warned_end:
                LOG.warning("pompa %s: koniec krzywej degradacji (x = %.3f > 1); wartości jak dla x = 1, "
                            "wymiana łożyska = nowa bearing_installed_at", self.key, x)
                self._warned_end = True
            return 1.0
        return max(0.0, x)

    def wear(self, t: float) -> float:
        return curve(self.progress(t), self.k)

    def running_target_c(self, t: int) -> float:
        """Temperatura łożyska po pełnym nagrzaniu: rośnie z drganiami + odchylenie otoczenia od średniej."""
        p = self.p
        return (p["bearing_good_c"] + (p["bearing_end_c"] - p["bearing_good_c"]) * self.wear(t)
                + (self.cal.ambient_c(t) - self.config.ambient.mean_c))

    def bearing_temperature_model(self, t: int) -> float:
        """Temperatura łożyska bez szumu."""
        p = self.p
        shift = self.cal.shift_at(t)
        if shift is not None:
            ambient = self.cal.ambient_c(t)
            heating = 1.0 - math.exp(-(t - shift[0]) / (p["warmup_tau_min"] * 60.0))
            return ambient + (self.running_target_c(t) - ambient) * heating
        last = self.cal.last_shift_before(t)
        if last is None:
            return self.cal.ambient_c(t)
        start, end = last
        amb_end = self.cal.ambient_c(end)
        at_end = amb_end + (self.running_target_c(end) - amb_end) * (1.0 - math.exp(-(end - start) / (p["warmup_tau_min"] * 60.0)))
        return self.cal.ambient_c(t) + (at_end - amb_end) * math.exp(-(t - end) / (p["cooldown_tau_min"] * 60.0))

    def sample(self, t: int) -> dict[str, float]:
        p, seed = self.p, self.config.seed
        u = uniforms(seed, self.key, t)
        g1, g2 = normal_pair(u[0], u[1])
        g3, _ = normal_pair(u[2], u[3])
        temperature = self.bearing_temperature_model(t) + 0.1 * g3
        if self.cal.shift_at(t) is None:
            return {"vibration_rms": round(max(0.01, STANDSTILL_VIBRATION * (1.0 + 0.2 * g1)), 2),
                    "bearing_temperature": round(temperature, 1), "motor_current": 0.0, "flow": 0.0, "speed": 0.0}
        x = self.progress(t)
        f = curve(x, self.k)
        vibration = (p["vibration_good_mm_s"] + (p["vibration_end_mm_s"] - p["vibration_good_mm_s"]) * f) * \
            (1.0 + 0.03 * slow(seed, self.key + "|vibration", t, 6 * 3600.0) + 0.025 * g1)
        load = 0.9 + 0.05 * slow(seed, self.key + "|load", t, 1800.0)
        speed = p["speed_rpm"] * (1.0 + 0.003 * g2)
        current = p["current_a"] * (0.55 + 0.35 * load) * (1.0 + CURRENT_WEAR_GAIN * f) * (1.0 + 0.005 * g3)
        flow = p["flow_m3_h"] * load * (speed / p["speed_rpm"]) * (1.0 - FLOW_WEAR_LOSS * x)
        return {"vibration_rms": round(max(0.01, vibration), 2), "bearing_temperature": round(temperature, 1),
                "motor_current": round(current, 2), "flow": round(flow, 1), "speed": float(round(speed))}
