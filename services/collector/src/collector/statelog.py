"""Logowanie zmian stanu bez zalewania: wpis przy zmianie i przypomnienie co REMIND_S dla stanu nieprawidłowego.

Szczegół stanu (np. kod błędu licznika) jest częścią etykiety: zmiana kodu w trakcie błędu to zmiana stanu, więc dostaje wpis.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

LOG = logging.getLogger("collector.state")

REMIND_S = 60.0
OK_STATES = {"OK"}


class StateLogger:
    def __init__(self, clock: Callable[[], float] = time.monotonic, remind_s: float = REMIND_S) -> None:
        self._clock = clock
        self._remind_s = remind_s
        self._label: dict[str, str] = {}
        self._logged_at: dict[str, float] = {}

    def update(self, states: dict[str, str], details: dict[str, str] | None = None) -> None:
        now = self._clock()
        details = details or {}
        for key, state in states.items():
            label = f"{state} ({details[key]})" if details.get(key) else state
            previous = self._label.get(key)
            if previous != label:
                level = logging.INFO if state in OK_STATES else logging.WARNING
                LOG.log(level, "%s: %s -> %s", key, previous or "(start)", label)
                self._logged_at[key] = now
            elif state not in OK_STATES and now - self._logged_at.get(key, now) >= self._remind_s:
                LOG.warning("%s: nadal %s", key, label)
                self._logged_at[key] = now
            self._label[key] = label
