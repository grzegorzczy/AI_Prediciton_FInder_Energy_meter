"""Kalendarz pracy (S2) i temperatura otoczenia w czasie lokalnym z czasem letnim (zoneinfo + pakiet tzdata, K2-U2).

Stan w chwili t (sekundy UTC od 1970): `off` (poza zmianą, święto), `work` (praca), `break` (przerwa planowa w czasie
zmiany). Plan doby lokalnej liczony raz i trzymany w pamięci (koszt na sekundę jest stały); wynik nie zależy od kolejności
wywołań. Zmiany przez północ nie są obsługiwane (walidacja configu).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .config import Ambient, Calendar

OFF, WORK, BREAK = "off", "work", "break"


@dataclass(frozen=True)
class DayPlan:
    day: date
    start: int                       # północ lokalna (epoch s)
    end: int                         # następna północ lokalna (23, 24 albo 25 h później)
    shift: tuple[int, int] | None     # [początek, koniec) zmiany
    breaks: tuple[tuple[int, int], ...]


class CalendarModel:
    def __init__(self, calendar: Calendar, ambient: Ambient) -> None:
        self.cal = calendar
        self.ambient_cfg = ambient
        self._plans: dict[date, DayPlan] = {}
        self._last: DayPlan | None = None

    # --- plan doby -------------------------------------------------------------------------------------------------

    def _epoch(self, day: date, minutes: int) -> int:
        local = datetime(day.year, day.month, day.day, tzinfo=self.cal.timezone) + timedelta(minutes=minutes)
        # dodanie minut do „świadomej” daty z zoneinfo liczy czas ścienny; dla 06:00, 14:00, 22:00 nie ma niejednoznaczności
        return int(local.timestamp())

    def _make_plan(self, day: date) -> DayPlan:
        start = int(datetime(day.year, day.month, day.day, tzinfo=self.cal.timezone).timestamp())
        nxt = day + timedelta(days=1)
        end = int(datetime(nxt.year, nxt.month, nxt.day, tzinfo=self.cal.timezone).timestamp())
        shift = None
        breaks: list[tuple[int, int]] = []
        if day not in self.cal.holidays:
            for item in self.cal.shifts:
                if day.isoweekday() in item.days:
                    s, e = self._epoch(day, item.start_min), self._epoch(day, item.end_min)
                    shift = (s, e)
                    for br in self.cal.breaks:
                        bs = self._epoch(day, br.start_min)
                        if s <= bs < e:
                            breaks.append((bs, min(e, bs + br.minutes * 60)))    # przerwa nie wychodzi poza zmianę
        return DayPlan(day, start, end, shift, tuple(breaks))

    def plan(self, t: int) -> DayPlan:
        last = self._last
        if last is not None and last.start <= t < last.end:
            return last
        day = datetime.fromtimestamp(t, self.cal.timezone).date()
        plan = self._plans.get(day)
        if plan is None:
            plan = self._plans[day] = self._make_plan(day)
        self._last = plan
        return plan

    # --- stan --------------------------------------------------------------------------------------------------------

    def state(self, t: int) -> str:
        plan = self.plan(t)
        if plan.shift is None or not plan.shift[0] <= t < plan.shift[1]:
            return OFF
        for bs, be in plan.breaks:
            if bs <= t < be:
                return BREAK
        return WORK

    def shift_at(self, t: int) -> tuple[int, int] | None:
        """Zmiana obejmująca chwilę t (z przerwami), albo None."""
        plan = self.plan(t)
        if plan.shift is not None and plan.shift[0] <= t < plan.shift[1]:
            return plan.shift
        return None

    def last_shift_before(self, t: int, max_days: int = 10) -> tuple[int, int] | None:
        """Ostatnia zmiana zakończona najpóźniej w chwili t (dla stygnięcia), w oknie max_days dób wstecz."""
        plan = self.plan(t)
        day = plan.day
        for back in range(max_days + 1):
            d = day - timedelta(days=back)
            p = self._plans.get(d) or self._plans.setdefault(d, self._make_plan(d))
            if p.shift is not None and p.shift[1] <= t:
                return p.shift
        return None

    # --- otoczenie ---------------------------------------------------------------------------------------------------

    def local_hour(self, t: int) -> float:
        moment = datetime.fromtimestamp(t, self.cal.timezone)
        return moment.hour + moment.minute / 60.0 + moment.second / 3600.0

    def ambient_c(self, t: int) -> float:
        """Temperatura otoczenia: średnia ± amplituda, najcieplej o warmest_hour czasu lokalnego (kosinus doby)."""
        a = self.ambient_cfg
        return a.mean_c + a.swing_c * math.cos(2.0 * math.pi * (self.local_hour(t) - a.warmest_hour) / 24.0)

    def ambient_anomaly(self, t: int) -> float:
        """Odchylenie otoczenia od średniej w [-1, 1] (0 przy zerowej amplitudzie)."""
        a = self.ambient_cfg
        return 0.0 if a.swing_c == 0 else (self.ambient_c(t) - a.mean_c) / a.swing_c
