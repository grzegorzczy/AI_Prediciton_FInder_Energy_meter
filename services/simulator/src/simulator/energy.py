"""Licznik energii czynnej `energy_import_wh` licznika wirtualnego.

Stan licznika = `energy_start_wh` + Σ P(s) · 1 s / 3600 po pełnych sekundach od kotwicy (t_zero − history.meter_days)
do chwili t (bez niej), kwantowany w dół do `energy_resolution_wh`. P to ta sama, opublikowana (zaokrąglona) moc, więc
całka z bazy i przyrost licznika różnią się najwyżej o rozdzielczość licznika. Licznik jest całką modelu: rośnie także
wtedy, gdy próbek nie publikowano (jak prawdziwy licznik przy przerwie komunikacji).

Bez stanu w sensie danych: wynik zależy tylko od t i configu. Sumy liczone są w liczbach całkowitych (W·s; moc publikowana
jest w pełnych watach), więc ścieżka „po kolei” i „sumy dobowe” dają dokładnie ten sam wynik. Pamięć sum dobowych i ostatniej
wartości to wyłącznie przyspieszenie (start po N dobach od kotwicy liczy N dób raz; koszt mierzy test, K2-U3).
"""
from __future__ import annotations

import math

from .meters import MeterModel

DAY = 86400


class EnergyCounter:
    def __init__(self, meter: MeterModel) -> None:
        config, device = meter.config, meter.device
        self.meter = meter
        self.anchor = int(config.require_t_zero().timestamp()) - config.history.meter_days * DAY
        self.start_wh = float(device.energy_start_wh)
        self.resolution = float(device.energy_resolution_wh)
        self._day_sums: dict[int, int] = {}                   # W·s na dobę od kotwicy
        self._last: tuple[int, int] | None = None            # (t, W·s od kotwicy do t) – przyspieszenie odczytów po kolei

    def _sum(self, start: int, end: int) -> int:
        """Suma opublikowanej mocy [W·s] w sekundach [start, end) – liczby całkowite, bez błędu zaokrągleń."""
        power = self.meter.power
        total = 0
        for s in range(start, end):
            total += int(power(s)[0])
        return total

    def _day_sum(self, index: int) -> int:
        value = self._day_sums.get(index)
        if value is None:
            start = self.anchor + index * DAY
            value = self._day_sums[index] = self._sum(start, start + DAY)
        return value

    def integral_ws(self, t: int) -> int:
        """Całka mocy [W·s] od kotwicy do chwili t (bez sekundy t)."""
        if t < self.anchor:
            raise ValueError(f"chwila {t} przed kotwicą licznika {self.meter.device.device_id} ({self.anchor})")
        last = self._last
        if last is not None and last[0] <= t <= last[0] + 3600:
            value = last[1] + self._sum(last[0], t)
        else:
            days, rest = divmod(t - self.anchor, DAY)
            value = sum(self._day_sum(i) for i in range(days)) + self._sum(self.anchor + days * DAY, self.anchor + days * DAY + rest)
        self._last = (t, value)
        return value

    def integral_wh(self, t: int) -> float:
        return self.integral_ws(t) / 3600.0

    def value_wh(self, t: int) -> float:
        """Stan licznika w chwili t, kwantowany w dół do rozdzielczości (arytmetyka całkowita na W·s)."""
        start_ws = round(self.start_wh * 3600)
        step_ws = round(self.resolution * 3600)
        return float((start_ws + self.integral_ws(t)) // step_ws * step_ws) / 3600.0
