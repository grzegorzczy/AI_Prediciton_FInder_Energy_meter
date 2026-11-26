"""Pamięć sum dobowych liczników energii w pliku (K2R-D3): przyspieszenie startu, nie stan danych.

Plik JSON w wolumenie symulatora: {"format": 1, "key": "<sha256>", "devices": {"<id>": {"<doba>": <W·s>, …}}}.
Doba = blok 86 400 s od `meter_anchor` (UTC; czas letni nie zmienia klucza). Klucz = sha256 z MODEL_VERSION, ziarna,
kotwicy, kalendarza, otoczenia, elektryki i parametrów modeli liczników – zmiana czegokolwiek z tego (także kodu modelu
z podbitą MODEL_VERSION) unieważnia plik. Przy starcie ostatnia zapisana doba każdego licznika jest przeliczana i
porównywana co do W·s; niezgodność = WARNING, odrzucenie pliku i pełne przeliczenie. Brak, uszkodzenie lub brak praw
zapisu = przeliczenie i WARNING, nigdy błąd. Zapis atomowy: plik tymczasowy w tym samym katalogu + os.replace.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from . import MODEL_VERSION
from .config import SimConfig

LOG = logging.getLogger("simulator.daycache")
FORMAT = 1


def cache_key(config: SimConfig) -> str:
    cal = config.calendar
    meters = {d.device_id: {"type": d.model_type, "schedule": d.schedule, "params": d.params}
              for d in config.devices if d.kind == "energy_meter"}
    material = {
        "model_version": MODEL_VERSION,
        "seed": config.seed,
        "meter_anchor": config.require_meter_anchor().isoformat(),
        "calendar": {"timezone": str(cal.timezone),
                     "shifts": [[sorted(s.days), s.start_min, s.end_min] for s in cal.shifts],
                     "breaks": [[b.start_min, b.minutes] for b in cal.breaks],
                     "holidays": sorted(d.isoformat() for d in cal.holidays)},
        "ambient": [config.ambient.mean_c, config.ambient.swing_c, config.ambient.warmest_hour],
        "electrical": [config.electrical.voltage_v, config.electrical.voltage_slow_v, config.electrical.voltage_noise_v],
        "meters": meters,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


class DayCache:
    def __init__(self, path: str | Path | None, key: str) -> None:
        self.path = Path(path) if path else None
        self.key = key
        self.days: dict[str, dict[int, int]] = {}
        self.dirty = False
        self.source = "brak pliku"
        self._load()

    def _load(self) -> None:
        if self.path is None:
            self.source = "wyłączona"
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.source = "brak pliku"
            return
        except (OSError, ValueError) as exc:
            LOG.warning("pamięć sum dobowych %s nieczytelna (%s): przeliczam od zera", self.path, type(exc).__name__)
            self.source = "plik uszkodzony"
            return
        if not isinstance(raw, dict) or raw.get("format") != FORMAT or raw.get("key") != self.key:
            LOG.info("pamięć sum dobowych %s z innym kluczem (zmiana modelu lub parametrów): przeliczam od zera", self.path)
            self.source = "inny klucz"
            return
        try:
            self.days = {dev: {int(k): int(v) for k, v in days.items()} for dev, days in raw["devices"].items()}
        except (AttributeError, KeyError, TypeError, ValueError):
            LOG.warning("pamięć sum dobowych %s ma złą strukturę: przeliczam od zera", self.path)
            self.days, self.source = {}, "plik uszkodzony"
            return
        self.source = "plik"

    def get(self, device: str, day: int) -> int | None:
        return self.days.get(device, {}).get(day)

    def put(self, device: str, day: int, ws: int) -> None:
        if self.days.setdefault(device, {}).get(day) != ws:
            self.days[device][day] = ws
            self.dirty = True

    def verify(self, recompute) -> bool:
        """Ostatnia zapisana doba każdego urządzenia przeliczona od zera (recompute(device, day) -> W·s) i porównana."""
        for device, days in self.days.items():
            if not days:
                continue
            last = max(days)
            fresh = recompute(device, last)
            if fresh is None or fresh != days[last]:
                LOG.warning("pamięć sum dobowych: doba %d urządzenia %s niezgodna z modelem (%s != %s) – odrzucam plik",
                            last, device, days[last], fresh)
                self.days, self.dirty, self.source = {}, True, "niezgodna – odrzucona"
                return False
        return True

    def flush(self) -> bool:
        """Zapis atomowy, gdy są zmiany; błąd zapisu = WARNING (symulator działa dalej)."""
        if self.path is None or not self.dirty:
            return False
        payload = json.dumps({"format": FORMAT, "key": self.key,
                              "devices": {dev: {str(k): v for k, v in sorted(days.items())} for dev, days in sorted(self.days.items())}},
                             separators=(",", ":"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".energy-days-", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as exc:
            LOG.warning("nie mogę zapisać pamięci sum dobowych %s (%s): następny start policzy od zera; "
                        "kolejna próba przy następnej pełnej dobie", self.path, exc)
            self.dirty = False                   # bez ponawiania co sekundę: put() nowej doby znowu ustawi dirty
            return False
        self.dirty = False
        return True
