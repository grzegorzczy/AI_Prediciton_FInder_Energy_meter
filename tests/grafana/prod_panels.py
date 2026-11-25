#!/usr/bin/env python3
"""Sprawdzenie paneli na prawdziwej bazie (k7, G7-e): każdy cel każdego panelu każdego dashboardu przez API produkcyjnej Grafany.

Uruchamiane NA KOMPUTERZE (host z dockerem), bez hasła w poleceniu: transport `docker exec` (patrz grafana_support._api_via_docker).
Użycie:  python3 tests/grafana/prod_panels.py [device_id] [zakres ...]      zakresy: 15m 6h 24h 7d 30d (domyślnie 15m 6h 24h 7d)
Kod wyjścia 1, gdy którykolwiek panel zwróci błąd. Wypisuje tabelę: dashboard, panel, zakres, wiersze, czas.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("GRAFANA_DOCKER_CONTAINER", "aip-grafana")
os.environ.setdefault("REPO_DIR", str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from grafana_support import RANGES, dashboards, ds_query, effective_seconds, expand_vars, panel_targets  # noqa: E402


MAX_PROD_RANGE_S = 7 * 86400   # zakresy dłuższe niż 7 dni nie są uruchamiane na produkcyjnej Grafanie
PAUSE_S = float(os.environ.get("PROD_PANELS_PAUSE_S", "0.2"))   # przerwa między zapytaniami; zapytania idą pojedynczo (bez współbieżności)


def main(argv: list[str]) -> int:
    device = argv[0] if argv and argv[0] not in RANGES else "finder_7m24_1"
    ranges = [a for a in argv if a in RANGES] or ["15m", "6h", "24h", "7d"]
    # k8: produkcyjna Grafana ma limit pamięci; długie zakresy tylko na aip-test (tests/run-tests.sh), nie tutaj
    too_long = [r for r in ranges if RANGES[r] > MAX_PROD_RANGE_S]
    if too_long:
        print(f"Odmowa: zakres {too_long} jest za długi dla produkcji (max 7d); użyj środowiska aip-test.", file=sys.stderr)
        return 2
    failures, total = 0, 0
    print(f"{'dashboard':12} {'zakres':6} {'wiersze':>8} {'ms':>6}  panel")
    for name, dash in dashboards().items():
        for range_name in ranges:
            end = time.time()
            start = end - RANGES[range_name]
            rows_by_panel: dict[str, list] = {}
            for panel, target in panel_targets(dash):
                title = panel["title"]
                sql = expand_vars(target["rawSql"], device)
                # panel z własnym zakresem czasu (timeFrom) używa go zamiast zakresu pulpitu
                result = ds_query(sql, target["format"], end - effective_seconds(panel, RANGES[range_name]), end, target["refId"])
                total += 1
                time.sleep(PAUSE_S)
                if result["error"]:
                    failures += 1
                    print(f"BŁĄD {name}/{title}[{target['refId']}] {range_name}: {result['error']}")
                entry = rows_by_panel.setdefault(title, [0, 0.0])
                entry[0] += result["rows"]
                entry[1] = max(entry[1], result["elapsed"])
            for title, (rows, elapsed) in rows_by_panel.items():
                print(f"{name:12} {range_name:6} {rows:8d} {elapsed * 1000:6.0f}  {title}")
    print(f"\nzapytań: {total}, błędów: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
