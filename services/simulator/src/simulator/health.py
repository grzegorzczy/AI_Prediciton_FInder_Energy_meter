"""Healthcheck kontenera: „pętla żyje” (plik odświeżany przez pętlę), a nie „broker działa” – jak w collectorze.

Użycie: python -m simulator.health  → kod 0, gdy plik był odświeżony w ciągu MAX_AGE_S sekund, inaczej 1.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEFAULT_PATH = "/tmp/simulator-health"
MAX_AGE_S = 15.0


def touch(path: str = DEFAULT_PATH) -> None:
    Path(path).write_text(f"{time.time():.0f}\n", encoding="ascii")


def check(path: str = DEFAULT_PATH, max_age_s: float = MAX_AGE_S) -> bool:
    try:
        return time.time() - os.path.getmtime(path) <= max_age_s
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if check(os.environ.get("HEALTH_FILE", DEFAULT_PATH)) else 1)
