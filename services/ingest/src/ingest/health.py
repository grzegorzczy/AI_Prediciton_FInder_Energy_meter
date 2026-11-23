"""Znacznik żywotności: plik aktualizowany w każdym obrocie pętli głównej.

`healthy` oznacza „pętla żyje”, a nie „baza i broker działają”: niedostępna baza to stan zgłaszany w logu, a nie powód
do restartu kontenera (uwaga U4). `python -m ingest.health` kończy się kodem 0, gdy znacznik jest świeższy niż limit.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DEFAULT_PATH = "/tmp/ingest.health"
MAX_AGE_S = 15.0


def touch(path: str | Path = DEFAULT_PATH) -> None:
    path = Path(path)
    path.touch(exist_ok=True)
    os.utime(path, None)


def is_fresh(path: str | Path = DEFAULT_PATH, max_age_s: float = MAX_AGE_S) -> bool:
    try:
        return time.time() - os.path.getmtime(path) < max_age_s
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if is_fresh(os.environ.get("HEALTH_FILE", DEFAULT_PATH)) else 1)
