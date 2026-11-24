"""Pomocnik testów Grafany: API przez urllib (bez dodatkowych zależności), harness zapytań paneli, podstawianie zmiennych."""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(os.environ.get("REPO_DIR", Path(__file__).resolve().parents[2]))
DASH_DIR = REPO / "grafana" / "dashboards"
BASE = os.environ.get("GRAFANA_URL", "http://grafana:3000")
DS = {"type": "grafana-postgresql-datasource", "uid": "aip-timescaledb"}

DEFAULT_VARS = {"u_nom": "230", "u_band_pct": "10", "f_nom": "50", "f_band_hz": "0.2", "stale_s": "10"}
RANGES = {"15m": 15 * 60, "6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 86400, "30d": 30 * 86400}


def load_generator():
    spec = importlib.util.spec_from_file_location("aip_grafana_generate", REPO / "grafana" / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _api_via_docker(container: str, method: str, path: str, body, auth: bool, timeout: float):
    """Transport przez `docker exec` (produkcja): hasło admina jest rozwijane przez powłokę KONTENERA ze zmiennych GF_SECURITY_*
    i nigdy nie trafia do tego procesu, polecenia ani wyjścia."""
    import subprocess

    credentials = '-u "$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD" ' if auth else ""
    command = (f'curl -s {credentials}-X {method} -H "Content-Type: application/json" --data-binary @- '
               f'-w "' + chr(92) + 'n%{http_code}" ' + f'http://127.0.0.1:3000{path}')
    done = subprocess.run(["docker", "exec", "-i", container, "sh", "-c", command],
                          input=(json.dumps(body) if body is not None else ""), capture_output=True, text=True, timeout=timeout)
    raw, _, code = done.stdout.rpartition(chr(10))
    try:
        return int(code), json.loads(raw)
    except ValueError:
        return int(code or 0), raw


def api(method: str, path: str, body=None, auth: bool = True, timeout: float = 60.0):
    """(status, odpowiedź JSON lub tekst); statusy błędów nie rzucają wyjątku."""
    if os.environ.get("GRAFANA_DOCKER_CONTAINER"):
        return _api_via_docker(os.environ["GRAFANA_DOCKER_CONTAINER"], method, path, body, auth, timeout)
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if auth:
        token = base64.b64encode(f"admin:{os.environ['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()
        request.add_header("Authorization", "Basic " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw.decode("utf-8", "replace")


def wait_until_healthy(seconds: float = 60.0) -> None:
    deadline = time.monotonic() + seconds
    while True:
        status, _ = api("GET", "/api/health", auth=False)
        if status == 200:
            return
        if time.monotonic() > deadline:
            raise RuntimeError("Grafana nie jest zdrowa")
        time.sleep(1)


def dashboards() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DASH_DIR.glob("*.json"))}


def targets(dash: dict):
    """(tytuł panelu, cel zapytania) dla każdego celu każdego panelu."""
    for panel in dash["panels"]:
        for target in panel.get("targets", []):
            yield panel["title"], target


def panel_targets(dash: dict):
    """(panel, cel zapytania) dla każdego celu każdego panelu."""
    for panel in dash["panels"]:
        for target in panel.get("targets", []):
            yield panel, target


def effective_seconds(panel: dict, default_s: float) -> float:
    """Zakres czasu panelu: własny `timeFrom` (np. "28d", "14d") albo zakres pulpitu."""
    own = panel.get("timeFrom")
    if not own:
        return default_s
    number, unit = int(own[:-1]), own[-1]
    return number * {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}[unit]


def expand_vars(sql: str, device: str, overrides: dict | None = None) -> str:
    values = {**DEFAULT_VARS, **(overrides or {})}
    for name in sorted(values, key=len, reverse=True):
        sql = sql.replace("$" + name, str(values[name]))
    return sql.replace("$device", device)


def ds_query(sql: str, fmt: str, start_s: float, end_s: float, ref: str = "A") -> dict:
    """Wynik jednego zapytania przez /api/ds/query: {"error": ..., "rows": liczba wierszy, "elapsed": s, "frames": [...]}."""
    span_ms = int((end_s - start_s) * 1000)
    body = {"queries": [{"refId": ref, "datasource": DS, "rawSql": sql, "format": fmt, "rawQuery": True, "editorMode": "code",
                         "intervalMs": max(1000, span_ms // 1000), "maxDataPoints": 1000}],
            "from": str(int(start_s * 1000)), "to": str(int(end_s * 1000))}
    t0 = time.perf_counter()
    status, payload = api("POST", "/api/ds/query", body)
    elapsed = time.perf_counter() - t0
    if status != 200 and not isinstance(payload, dict):
        return {"error": f"HTTP {status}: {payload}", "rows": 0, "elapsed": elapsed, "frames": []}
    result = (payload.get("results") or {}).get(ref, {}) if isinstance(payload, dict) else {}
    error = result.get("error") or (payload.get("message") if status != 200 and isinstance(payload, dict) else None)
    frames = result.get("frames") or []
    rows = max((len(f["data"]["values"][0]) for f in frames if f.get("data", {}).get("values")), default=0)
    return {"error": error, "rows": rows, "elapsed": elapsed, "frames": frames}


def column(result: dict, name: str | None = None, frame: int = 0) -> list:
    frame_data = result["frames"][frame]
    fields = frame_data["schema"]["fields"]
    index = 0 if name is None else [f["name"] for f in fields].index(name)
    return frame_data["data"]["values"][index]
