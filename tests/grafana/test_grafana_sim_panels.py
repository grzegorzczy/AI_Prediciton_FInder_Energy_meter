"""Panele „Flota” i „Pompa” (E3-k6) przez API Grafany na danych z narzędzia historii (K6-D4: `slow`, dane ładowane raz na sesję,
ok. 10 min). Uruchamianie: AIP_SLOW_PANELS=1 sh tests/run-tests.sh tests/grafana  (w k6, k8 i przy zmianach Grafany lub agregatów).
Czasy wszystkich paneli (K6-U1) wypisywane jako [czasy]; próg twardy 3 s."""
from __future__ import annotations

import os
import time
import pytest

from grafana_support import RANGES, dashboards, ds_query, effective_seconds, expand_vars, load_generator, panel_targets

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("AIP_SLOW_PANELS") != "1", reason="panele na danych z historii: AIP_SLOW_PANELS=1"),
]

DASHES = dashboards()
NEW = ("flota", "pompa")
PUMP = "sim_pump_p101"           # identyfikator z config/devices.yaml (dane testowe, nie kod produkcyjny)
SIM_METERS = {"sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka"}
ALL_RANGES = {**RANGES, "90d": 90 * 86400}
MAX_QUERY_S = 3.0
# Kafelki „teraz” (ostatnie 10 min): w teście nie ma danych na żywo, tylko historia kończąca się przy ładowaniu.
MAY_BE_EMPTY = {"Temperatura łożyska teraz", "Obroty teraz"}
TIMES: dict[tuple[str, str], float] = {}


@pytest.fixture(scope="session")
def sim_history(grafana_data, pg, role_passwords):
    from sim_history import load_history

    t0 = time.monotonic()
    info = load_history(pg, "energy", role_passwords["app_reader"], role_passwords["app_writer"], meter_hours=2, pump_days=84)
    print(f"\n[historia] {info['stats']['messages']} wiadomości w {time.monotonic() - t0:.0f} s "
          f"({info['stats']['rate']:.0f}/s, porcji {info['stats']['chunks']})")
    yield info
    if TIMES:
        slowest = sorted(TIMES.items(), key=lambda kv: -kv[1])
        print("\n[czasy] najwolniejsze cele (dashboard/panel, s): " +
              "; ".join(f"{name}/{title} {s:.2f}" for (name, title), s in slowest[:12]))
        print(f"[czasy] wszystkie {len(TIMES)} paneli: maks. {slowest[0][1]:.2f} s, > 1 s: "
              f"{[f'{n}/{t}' for (n, t), s in slowest if s > 1.0]}")


def query(name, title, start, end, overrides=None, ref=0):
    panel = next(p for p in DASHES[name]["panels"] if p["title"] == title)
    target = panel["targets"][ref]
    sql = expand_vars(target["rawSql"], "finder_7m24_1", overrides).replace("$pump", PUMP)
    result = ds_query(sql, target["format"], start, end, target["refId"])
    assert not result["error"], f"{name}/{title}: {result['error']}\n{sql}"
    return result


def series(result) -> dict[str, tuple[list, list]]:
    """{nazwa serii: (czasy ms, wartości)} ze wszystkich ramek wyniku (Grafana dzieli serie na ramki; nazwa z displayNameFromDS,
    etykiety `metric` albo nazwy pola)."""
    out = {}
    for f in result["frames"]:
        fields, values = f["schema"]["fields"], f["data"]["values"]
        times = next((values[i] for i, fl in enumerate(fields) if fl.get("type") == "time"), None)
        for i, fl in enumerate(fields):
            if fl.get("type") == "time":
                continue
            name = ((fl.get("config") or {}).get("displayNameFromDS") or (fl.get("labels") or {}).get("metric") or fl["name"])
            out[name] = (times, values[i])
    return out


def describe(result) -> str:
    return str([[(fl["name"], fl.get("type"), fl.get("labels"), (fl.get("config") or {}).get("displayNameFromDS"))
                 for fl in f["schema"]["fields"]] for f in result["frames"]])[:1500]


def columns(result, frame=0):
    f = result["frames"][frame]
    return {field["name"]: values for field, values in zip(f["schema"]["fields"], f["data"]["values"])}


@pytest.mark.parametrize("range_name", list(ALL_RANGES))
@pytest.mark.parametrize("name", NEW)
def test_every_panel_runs_fast_without_error(sim_history, name, range_name):
    end = time.time()
    for panel, target in panel_targets(DASHES[name]):
        start = end - effective_seconds(panel, ALL_RANGES[range_name])
        sql = expand_vars(target["rawSql"], "finder_7m24_1").replace("$pump", PUMP)
        result = ds_query(sql, target["format"], start, end, target["refId"])
        assert not result["error"], f"{name}/{panel['title']} {range_name}: {result['error']}\n{sql}"
        TIMES[(name, panel["title"])] = max(TIMES.get((name, panel["title"]), 0.0), result["elapsed"])
        assert result["elapsed"] < MAX_QUERY_S, f"{name}/{panel['title']} {range_name}: {result['elapsed']:.2f} s"
        if range_name in ("24h", "7d", "30d") and panel["title"] not in MAY_BE_EMPTY:
            assert result["rows"] > 0, f"{name}/{panel['title']} {range_name}: brak danych"


def test_fleet_table_marks_simulated_meters_from_the_source_column(sim_history):
    now = time.time()
    rows = columns(query("flota", "Liczniki floty", now - 3600, now, {"stale_s": str(int(now - sim_history["end"]) + 120)}))
    by_name = dict(zip(rows["Urządzenie"], zip(rows["Źródło"], rows["Stan"], rows["Moc teraz"])))
    sim = {k: v for k, v in by_name.items() if k.endswith("(SYMULACJA)")}
    assert len(sim) == 4 and all(src == "SYMULACJA" and state == "Aktualne" and power is not None for src, state, power in sim.values())
    real = {k: v for k, v in by_name.items() if not k.endswith("(SYMULACJA)")}
    assert real and all(src == "pomiar" for src, _, _ in real.values()) and "SYMULACJA" not in " ".join(real)
    assert rows["Źródło"][: len(real)] == ["pomiar"] * len(real)                       # prawdziwe na górze
    stale = columns(query("flota", "Liczniki floty", now - 3600, now, {"stale_s": "1"}))
    assert all(p is None for p, s in zip(stale["Moc teraz"], stale["Stan"]) if s == "Brak danych")   # brak danych to nie zero


def test_device_variables_label_only_simulated_devices_and_keep_values(sim_history):
    """K6-U2: wartość zmiennej $device to nadal device_id (zapytania paneli etapu 2 bez zmian), zmienia się tylko etykieta."""
    generator = load_generator()
    now = time.time()
    for name, var in (("na-zywo", "device"), ("pompa", "pump")):
        sql = next(v for v in DASHES[name]["templating"]["list"] if v["name"] == var)["query"]
        rows = columns(ds_query(sql, "table", now - 60, now))
        pairs = dict(zip(rows["__value"], rows["__text"]))
        for value, text in pairs.items():
            assert text.endswith(f"({generator.SIM_MARK})") == value.startswith("sim_"), (value, text)
    pairs = dict(zip(*columns(ds_query(next(v for v in DASHES["przeglad"]["templating"]["list"] if v["name"] == "device")["query"],
                                       "table", now - 60, now)).values()))
    assert pairs["finder_7m24_1"] == "Licznik 1" and pairs["finder_7m24_2"] == "Licznik 2"      # Finder bez zmian


@pytest.mark.parametrize("range_name", ["6h", "24h", "7d", "absolute"])
def test_vibration_trend_uses_only_running_minutes_and_rises(sim_history, range_name):
    """K6R-V1: zawsze 90 dni od teraz. Względny zakres pulpitu: Grafana podstawia `timeFrom` (90 d); bezwzględny (np. sprzed
    30 dni, 1 h): `timeFrom` pominięty, zakres pulpitu trafia do zapytania, a SQL i tak liczy 90 dni od teraz."""
    now = time.time()
    panel = next(p for p in DASHES["pompa"]["panels"] if p["title"].startswith("Trend drgań"))
    if range_name == "absolute":
        start, end = now - 30 * 86400, now - 30 * 86400 + 3600
    else:
        start, end = now - effective_seconds(panel, ALL_RANGES[range_name]), now
        assert end - start == 90 * 86400
    result = query("pompa", panel["title"], start, end)
    found = series(result)
    assert {"Drgania (średnia doby pracy)", "Minuty pracy"} <= set(found), describe(result)
    days, vib = found["Drgania (średnia doby pracy)"]
    minutes = found["Minuty pracy"][1]
    assert 65 <= len(days) <= 74, len(days)                                                # 84 doby historii bez 12 niedziel
    assert all(m <= 16 * 60 for m in minutes)                                               # najdłuższa zmiana 06–22
    first, last = sum(vib[:6]) / 6, sum(vib[-6:]) / 6
    assert last > first * 1.3, (first, last)                                                # model: x od 0 do 0,70


def test_minute_vibration_is_empty_when_the_pump_stands(sim_history):
    end = sim_history["end"]
    start = end - 2 * 86400
    vib_result, speed_result = query("pompa", "Drgania – minuty pracy", start, end), query("pompa", "Obroty", start, end)
    vib, speed = series(vib_result), series(speed_result)
    assert len(vib) == 1 and len(speed) == 1, (describe(vib_result), describe(speed_result))
    (vt, vv), (st, sv) = next(iter(vib.values())), next(iter(speed.values()))
    by_time = dict(zip(st, sv))
    pairs = [(v, by_time.get(t)) for t, v in zip(vt, vv)]
    assert any(s == 0 for _, s in pairs) and any(s and s > 0 for _, s in pairs)
    assert all(v is None for v, s in pairs if s == 0), "w postoju drgania muszą być puste, nie zero"
    assert all(v is not None and v > 0 for v, s in pairs if s and s > 2000)


def test_fleet_freshness_axis_is_empty_before_the_first_reading(sim_history):
    """Liczniki sim mają dane tylko z ostatnich 2 h: wcześniej oś jest pusta (NULL, K6R-V2: przed pierwszym odczytem to nie
    awaria), w ostatnich 2 h „Dane” (2)."""
    end = sim_history["end"]
    result = query("flota", "Świeżość danych w czasie", end - 6 * 3600, end)
    sim = {k: v for k, v in series(result).items() if "SYMULACJA" in k}
    assert len(sim) == 4, describe(result)
    for label, (times, values) in sim.items():
        before = [v for t, v in zip(times, values) if t / 1000 < sim_history["anchor"] - 120]
        after = [v for t, v in zip(times, values) if sim_history["anchor"] + 120 <= t / 1000 < end - 120]
        assert before and set(before) == {None}, label
        assert after and set(after) == {2}, label
