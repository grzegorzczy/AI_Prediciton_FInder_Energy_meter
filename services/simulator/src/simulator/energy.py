"""Licznik energii czynnej `energy_import_wh` licznika wirtualnego.

Stan licznika = `energy_start_wh` + Σ P(s) · 1 s / 3600 po pełnych sekundach od kotwicy `meter_anchor`
do chwili t (bez niej), kwantowany w dół do `energy_resolution_wh`. P to ta sama, opublikowana (zaokrąglona) moc, więc
całka z bazy i przyrost licznika różnią się najwyżej o rozdzielczość licznika. Licznik jest całką modelu: rośnie także
wtedy, gdy próbek nie publikowano (jak prawdziwy licznik przy przerwie komunikacji).

Bez stanu w sensie danych: wynik zależy tylko od t i configu. Sumy liczone są w liczbach całkowitych (W·s; moc publikowana
jest w pełnych watach), więc ścieżka „po kolei” i „sumy dobowe” dają dokładnie ten sam wynik. Pamięć sum dobowych i ostatniej
wartości to wyłącznie przyspieszenie (start po N dobach od kotwicy liczy N dób raz; koszt mierzy test, K2-U3).
"""
from __future__ import annotations

from .meters import MeterModel

DAY = 86400


class EnergyCounter:
    def __init__(self, meter: MeterModel, cache=None) -> None:
        config, device = meter.config, meter.device
        self.meter = meter
        self.device_id = device.device_id
        self.anchor = int(config.require_meter_anchor().timestamp())      # K2R-D1: stała kotwica, niezależna od pompy
        self.start_wh = float(device.energy_start_wh)
        self.resolution = float(device.energy_resolution_wh)
        self.cache = cache                                    # DayCache (plik) albo None
        self._day_sums: dict[int, int] = {}                   # W·s na dobę od kotwicy
        self._boundaries: dict[int, int] = {}                 # W·s od kotwicy do początku doby k (z odczytów po kolei)
        self._last: tuple[int, int] | None = None            # (t, W·s od kotwicy do t) – przyspieszenie odczytów po kolei

    def compute_day(self, index: int) -> int:
        """Suma W·s doby `index` liczona od zera (bez pamięci) – także do kontroli pliku przy starcie."""
        start = self.anchor + index * DAY
        return self._sum(start, start + DAY)

    def _remember(self, index: int, value: int) -> None:
        self._day_sums[index] = value
        if self.cache is not None:
            self.cache.put(self.device_id, index, value)

    def _sum(self, start: int, end: int) -> int:
        """Suma opublikowanej mocy [W·s] w sekundach [start, end) – liczby całkowite, bez błędu zaokrągleń."""
        power = self.meter.power
        total = 0
        for s in range(start, end):
            total += int(power(s)[0])
        return total

    def _day_sum(self, index: int) -> int:
        value = self._day_sums.get(index)
        if value is None and self.cache is not None:
            value = self.cache.get(self.device_id, index)
            if value is not None:
                self._day_sums[index] = value
        if value is None:
            value = self.compute_day(index)
            self._remember(index, value)
        return value

    def _boundary(self, t: int, value: int) -> None:
        """Na początku doby zapamiętuje całkę; z dwóch kolejnych początków powstaje suma doby bez liczenia od nowa."""
        days, rest = divmod(t - self.anchor, DAY)
        if rest:
            return
        self._boundaries[days] = value
        previous = self._boundaries.get(days - 1)
        if previous is not None and (days - 1) not in self._day_sums:
            self._remember(days - 1, value - previous)

    def integral_ws(self, t: int) -> int:
        """Całka mocy [W·s] od kotwicy do chwili t (bez sekundy t)."""
        if t < self.anchor:
            raise ValueError(f"chwila {t} przed kotwicą licznika {self.meter.device.device_id} ({self.anchor})")
        last = self._last
        incremental = last is not None and last[0] <= t <= last[0] + 3600
        if incremental:
            value = last[1] + self._sum(last[0], t)
        else:
            days, rest = divmod(t - self.anchor, DAY)
            base = sum(self._day_sum(i) for i in range(days))
            self._boundary(self.anchor + days * DAY, base)
            value = base + self._sum(self.anchor + days * DAY, self.anchor + days * DAY + rest)
        if incremental and last[0] < t:                    # (ścieżka dobowa zapisała już swoją granicę wyżej)
            crossing = self.anchor + ((t - self.anchor) // DAY) * DAY     # początek doby t, jeśli przeszliśmy przez niego
            if last[0] < crossing <= t:
                self._boundary(crossing, last[1] + self._sum(last[0], crossing))
        self._last = (t, value)
        return value

    def integral_wh(self, t: int) -> float:
        return self.integral_ws(t) / 3600.0

    def value_wh(self, t: int) -> float:
        """Stan licznika w chwili t, kwantowany w dół do rozdzielczości (arytmetyka całkowita na W·s)."""
        start_ws = round(self.start_wh * 3600)
        step_ws = round(self.resolution * 3600)
        return float((start_ws + self.integral_ws(t)) // step_ws * step_ws) / 3600.0
