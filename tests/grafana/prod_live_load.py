#!/usr/bin/env python3
"""Symulacja otwartego dashboardu „Licznik na żywo” (odświeżanie 5 s) na produkcyjnej Grafanie, do pomiaru pamięci (k7).
Uruchamiane na komputerze: python3 tests/grafana/prod_live_load.py [minuty]. Co 5 s wykonuje wszystkie zapytania dashboardu
(zakres ostatnich 15 min) i co minutę zapisuje `docker stats` Grafany. Hasło admina nie opuszcza kontenera (docker exec)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("GRAFANA_DOCKER_CONTAINER", "aip-grafana")
os.environ.setdefault("REPO_DIR", str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grafana_support import dashboards, ds_query, expand_vars, targets  # noqa: E402


def memory() -> str:
    out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}} {{.CPUPerc}}", "aip-grafana"],
                         capture_output=True, text=True).stdout.strip()
    return out


def main(minutes: int) -> int:
    dash = dashboards()["na-zywo"]
    deadline = time.time() + minutes * 60
    next_report = time.time()
    cycles = errors = 0
    slowest = 0.0
    print(f"start: {memory()}", flush=True)
    while time.time() < deadline:
        cycle_start = time.time()
        for title, target in targets(dash):
            result = ds_query(expand_vars(target["rawSql"], "finder_7m24_1"), target["format"], cycle_start - 900, cycle_start, target["refId"])
            errors += bool(result["error"])
            slowest = max(slowest, result["elapsed"])
        cycles += 1
        if time.time() >= next_report:
            print(f"{time.strftime('%H:%M:%S')} cykle={cycles} błędy={errors} najwolniejsze={slowest * 1000:.0f} ms pamięć/CPU: {memory()}", flush=True)
            next_report += 60
        time.sleep(max(0.0, 5 - (time.time() - cycle_start)))
    print(f"koniec: cykle={cycles} błędy={errors} najwolniejsze={slowest * 1000:.0f} ms, {memory()}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 10))
