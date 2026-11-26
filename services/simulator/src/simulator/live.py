"""Tryb na żywo: co pełną sekundę zegara ściennego 29 wiadomości z `samples_at(t)`.

Zegar jest jedynym źródłem „teraz”; wartości nadal są funkcją chwili t. Małe opóźnienie (do `max_lag_s`) jest nadrabiane
sekunda po sekundzie; większe = przeskok do „teraz” i jeden wpis w logu (luki uzupełnia historia, k5). Cofnięcie zegara
(np. korekta NTP, K3-U3): do `max_lag_s` pętla czeka, aż zegar dogoni ostatnią wysłaną sekundę (nic nie wysyła dwa razy);
większe = pętla zaczyna od bieżącej sekundy (powtórzone sekundy mają te same wartości, baza ignoruje duplikaty).
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timezone
from typing import Callable

from .publisher import Publisher
from .samples import Simulator

LOG = logging.getLogger("simulator.live")


def iso_ms(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def messages_for(sim: Simulator, site: str, line: str, t: int) -> list[tuple[str, bytes]]:
    ts = iso_ms(t)
    return [(f"{site}/{line}/{device}/{metric}",
             json.dumps({"ts": ts, "value": value, "unit": unit, "source": "sim"}, ensure_ascii=False).encode())
            for device, metric, value, unit in sim.samples_at(t)]


class LiveLoop:
    def __init__(self, sim: Simulator, publisher: Publisher, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, max_lag_s: int = 5,
                 on_tick: Callable[[int], None] | None = None) -> None:
        self.sim = sim
        self.publisher = publisher
        self.site, self.line = sim.config.site, sim.config.line
        self.clock, self.sleep = clock, sleep
        self.max_lag_s = max_lag_s
        self.on_tick = on_tick
        self.last: int | None = None
        self.skipped_total = 0

    def step(self) -> int:
        """Wysyła wszystkie należne sekundy (zwykle jedną) i zwraca ich liczbę; nie śpi."""
        now = int(math.floor(self.clock()))
        if self.last is None:
            due = [now]
        elif now <= self.last:
            if self.last - now > self.max_lag_s:
                LOG.warning("zegar cofnięty o %d s: zaczynam od bieżącej sekundy (wartości te same, baza pomija duplikaty)",
                            self.last - now)
                due = [now]
            else:
                due = []                                   # małe cofnięcie albo ta sama sekunda: czekamy
        elif now - self.last > self.max_lag_s:
            LOG.warning("opóźnienie %d s: przeskakuję do bieżącej sekundy (luka %s – %s uzupełni historia)",
                        now - self.last, iso_ms(self.last + 1), iso_ms(now - 1))
            self.skipped_total += now - self.last - 1
            due = [now]
        else:
            due = list(range(self.last + 1, now + 1))
        for t in due:
            self.publisher.publish_batch(messages_for(self.sim, self.site, self.line, t))
            self.last = t
        if due:
            self.sim.cache.flush()                         # zapis tylko, gdy przybyła pełna doba (no-op w pozostałych)
        self.publisher.drain()
        if self.on_tick is not None:
            self.on_tick(len(due))
        return len(due)

    def run(self, stop) -> None:
        while not stop.is_set():
            self.step()
            now = self.clock()
            self.sleep(max(0.0, math.floor(now) + 1.0 - now + 0.002))
