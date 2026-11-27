"""Wgrywanie historii symulatora (E3-k5) i uzupełnianie luk. Uruchamiane jednorazowo usługą `simulator-tools` (K5-D1):

    docker compose run --rm simulator-tools python -m simulator.backfill --from 2026-11-17T00:00:00Z --to 2026-12-01T00:00:00Z
    docker compose run --rm simulator-tools python -m simulator.backfill --from … --to … --fill-gaps

Zakres: liczniki co 1 s od `meter_anchor`, pompa co `history.pump_step_s` od `bearing_installed_at` (ograniczone do --from/--to).
Publikacja QoS 1 z oknem w locie (`--inflight`, K5-D2). PUBACK przychodzi jednak od BROKERA, nie od ingestu, więc samo okno nie
ogranicza kolejki brokera dla ingestu (wspólnej z danymi prawdziwymi, limit 80 000 – przy przepełnieniu broker gubi najnowsze,
także prawdziwe). Dlatego sterowanie przepływem end-to-end: historia idzie porcjami (`--chunk-minutes` czasu modelu) i przed
kolejną porcją narzędzie czeka, aż ostatnia minuta poprzedniej porcji będzie w bazie (odczyt kontem tylko do odczytu).
Kolejka brokera dla ingestu nie przekracza więc jednej porcji (domyślnie 5 min = ok. 7 200 wiadomości).

--fill-gaps: dla każdej publikowanej metryki (liczniki 6, pompa 5; K5-U1) zapytanie do `measurements` dobami o liczności
w minutach; minuta urządzenia z brakiem którejkolwiek metryki jest wysyłana ponownie w całości (duplikaty pomija baza).
Wartości są funkcją czasu, więc uzupełnienie daje dokładnie te same liczby. Liczniki korzystają z pamięci sum dobowych
(`SIM_CACHE`, wspólny wolumen z usługą, K5-U4).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from . import health
from .config import ConfigError, load_config
from .live import iso_ms
from .samples import METER_METRICS, PUMP_METRICS, Simulator

LOG = logging.getLogger("simulator.backfill")
DAY = 86400


def parse_moment(text: str) -> int:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"{text}: wymagana strefa czasowa (np. Z)")
    return int(moment.timestamp())


class Plan:
    """Które urządzenia i chwile należą do historii w zakresie [start, end)."""

    def __init__(self, sim: Simulator, start: int, end: int, which: str = "all") -> None:
        cfg = sim.config
        self.sim, self.start, self.end = sim, start, end
        self.meters = set(sim.meters) if which in ("all", "meters") else set()
        self.pumps = set(sim.pumps) if which in ("all", "pump") else set()
        self.meter_from = max(start, int(cfg.require_meter_anchor().timestamp()))
        self.pump_step = cfg.history.pump_step_s
        self.pump_from = {}
        for dev in self.pumps:
            installed = int(cfg.require_bearing_installed_at(cfg.device(dev)).timestamp())
            first = max(start, installed)
            self.pump_from[dev] = first + (-first) % self.pump_step          # wyrównanie do kroku (pełne minuty)

    def devices_at(self, t: int) -> set[str]:
        devices = set()
        if self.meters and t >= self.meter_from:
            devices |= self.meters
        for dev, first in self.pump_from.items():
            if t >= first and (t - first) % self.pump_step == 0:
                devices.add(dev)
        return devices

    def moments(self, start: int, end: int):
        """Chwile (rosnąco) z co najmniej jednym urządzeniem: liczniki co 1 s od kotwicy, pompa co krok od montażu łożyska.
        Przed kotwicą liczników (sama pompa) pętla przeskakuje od kroku do kroku pompy."""
        starts = ([self.meter_from] if self.meters else []) + list(self.pump_from.values())
        if not starts:
            return
        base = min(self.pump_from.values()) if self.pump_from else None
        t = max(start, min(starts))
        while t < end:
            devices = self.devices_at(t)
            if devices:
                yield t, devices
            if self.meters and t + 1 >= self.meter_from:
                t += 1
            elif base is not None:
                nxt = base if t < base else base + ((t - base) // self.pump_step + 1) * self.pump_step
                t = min(nxt, self.meter_from) if self.meters else nxt
            else:
                t += 1

    def messages(self, t: int, devices: set[str]) -> list[tuple[str, bytes]]:
        import json

        cfg = self.sim.config
        ts = iso_ms(t)
        return [(f"{cfg.site}/{cfg.line}/{dev}/{metric}",
                 json.dumps({"ts": ts, "value": value, "unit": unit, "source": "sim"}, ensure_ascii=False).encode())
                for dev, metric, value, unit in self.sim.samples_at(t, devices=devices)]


class Window:
    """QoS 1 z ograniczoną liczbą wiadomości w locie (do brokera) i opcjonalnym sufitem tempa."""

    def __init__(self, client, inflight: int = 100, rate: float | None = None, clock=time.monotonic, sleep=time.sleep):
        if inflight < 1:
            raise ValueError("inflight musi być >= 1")
        self.client, self.inflight, self.rate = client, inflight, rate
        self.clock, self.sleep = clock, sleep
        self.pending: deque = deque()
        self.sent = 0
        self._t0 = clock()

    def publish(self, topic: str, payload: bytes) -> None:
        while len(self.pending) >= self.inflight:
            self.pending.popleft().wait_for_publish(timeout=60)
        while self.pending and self.pending[0].is_published():
            self.pending.popleft()
        info = self.client.publish(topic, payload, qos=1)
        if info.rc != 0:
            raise RuntimeError(f"publikacja odrzucona przez klienta MQTT (rc={info.rc}); sprawdź połączenie i konto")
        self.pending.append(info)
        self.sent += 1
        if self.rate:
            ahead = self.sent / self.rate - (self.clock() - self._t0)
            if ahead > 0:
                self.sleep(ahead)

    def drain(self) -> None:
        while self.pending:
            self.pending.popleft().wait_for_publish(timeout=60)


class Db:
    """Odczyt tylko do odczytu (konto app_reader, limit czasu zapytania): liczności w minutach i postęp wgrywania."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def minute_counts(self, device: str, metric: str, start: int, end: int) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT extract(epoch FROM time_bucket('1 minute', time))::bigint, count(*) FROM measurements "
            "WHERE device_id = %s AND metric = %s AND time >= to_timestamp(%s) AND time < to_timestamp(%s) GROUP BY 1",
            (device, metric, start, end)).fetchall()
        return {int(m): int(n) for m, n in rows}

    def has_row(self, device: str, metric: str, t: int) -> bool:
        return self.conn.execute("SELECT EXISTS (SELECT 1 FROM measurements WHERE device_id = %s AND metric = %s "
                                 "AND time = to_timestamp(%s))", (device, metric, t)).fetchone()[0]


def expected_per_minute(plan: Plan, device: str, minute: int) -> int:
    """Oczekiwana liczba próbek jednej metryki w pełnej minucie zakresu."""
    if device in plan.meters:
        return 60 if minute >= plan.meter_from else 0
    first = plan.pump_from[device]
    return 1 if minute >= first else 0


def incomplete_minutes(plan: Plan, db: Db, start: int, end: int) -> dict[str, set[int]]:
    """Minuty (pełne, w zakresie) z brakiem którejkolwiek publikowanej metryki – per urządzenie (K5-U1). Zapytania dobami."""
    start_m, end_m = start + (-start) % 60, end - end % 60
    missing: dict[str, set[int]] = {}
    for device in sorted(plan.meters | plan.pumps):
        metrics = [m for m, _ in (METER_METRICS if device in plan.meters else PUMP_METRICS)]
        for day in range(start_m, end_m, DAY):
            day_end = min(day + DAY, end_m)
            for metric in metrics:
                counts = db.minute_counts(device, metric, day, day_end)
                for minute in range(day, day_end, 60):
                    need = expected_per_minute(plan, device, minute)
                    if need and counts.get(minute, 0) < need:
                        missing.setdefault(device, set()).add(minute)
    return missing


def wait_for_db(db: Db, device: str, metric: str, t: int, timeout: float = 600.0, clock=time.monotonic, sleep=time.sleep) -> float:
    """Sterowanie przepływem: czeka, aż wiersz (device, metric, t) będzie w bazie; zwraca czas oczekiwania."""
    t0 = clock()
    while not db.has_row(device, metric, t):
        if clock() - t0 > timeout:
            raise TimeoutError(f"ingest nie zapisał {device}/{metric} {iso_ms(t)} w {timeout:.0f} s")
        sleep(0.5)
    return clock() - t0


def run(plan: Plan, window: Window, db: Db | None, start: int, end: int, chunk_s: int = 300, progress_s: float = 60.0,
        clock=time.monotonic, health_file: str | None = None) -> dict:
    """Wysyła historię porcjami czasu modelu; po każdej porcji czeka na bazę (gdy db podane)."""
    stats = {"messages": 0, "chunks": 0, "waited_s": 0.0}
    t0 = last_log = clock()
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + chunk_s, end)
        last = None
        for t, devices in plan.moments(chunk_start, chunk_end):
            for topic, payload in plan.messages(t, devices):
                window.publish(topic, payload)
                stats["messages"] += 1
            last = (t, devices)
            if clock() - last_log >= progress_s:
                last_log = clock()
                rate = stats["messages"] / max(clock() - t0, 1e-6)
                eta = (end - t) / max(t - start, 1) * (clock() - t0)
                LOG.info("postęp: czas modelu %s, %d wiadomości, %.0f/s, do końca ok. %.0f min",
                         iso_ms(t), stats["messages"], rate, eta / 60)
                if health_file:
                    health.touch(health_file)
        window.drain()
        if db is not None and last is not None:
            t_last, devices = last
            device = sorted(devices)[0]
            metric = (METER_METRICS if device in plan.meters else PUMP_METRICS)[0][0]
            stats["waited_s"] += wait_for_db(db, device, metric, t_last)
        stats["chunks"] += 1
        chunk_start = chunk_end
    stats["elapsed_s"] = clock() - t0
    stats["rate"] = stats["messages"] / max(stats["elapsed_s"], 1e-6)
    return stats


def fill_gaps(plan: Plan, window: Window, db: Db, start: int, end: int) -> dict:
    before = incomplete_minutes(plan, db, start, end)
    sent = 0
    for device, minutes in sorted(before.items()):
        for minute in sorted(minutes):
            for t, devices in plan.moments(minute, minute + 60):
                if device in devices:
                    for topic, payload in plan.messages(t, {device}):
                        window.publish(topic, payload)
                        sent += 1
    window.drain()
    deadline = time.monotonic() + 120
    after = incomplete_minutes(plan, db, start, end)
    while after and time.monotonic() < deadline:
        time.sleep(2)
        after = incomplete_minutes(plan, db, start, end)
    return {"missing_before": sum(len(v) for v in before.values()), "messages": sent,
            "missing_after": sum(len(v) for v in after.values()), "missing_after_detail": {k: len(v) for k, v in after.items()}}


# Kolejność hierarchii agregatów: najpierw minutowe, potem godzinowe (z minutowych), na końcu pump_1m (K4).
REFRESH_VIEWS = ("energy_1m", "energy_ext_1m", "energy_1h", "energy_ext_1h", "pump_1m")


def refresh_statements(start: int, end: int) -> list[str]:
    """Ręczne odświeżenie agregatów dla zakresu historii (starszego niż okna polityk). Wykonuje administrator (psql),
    nie narzędzie: konto app_reader nie może odświeżać. Granice rozszerzone do pełnych godzin."""
    lo, hi = iso_ms(start - start % 3600), iso_ms(end + (-end) % 3600)
    return [f"CALL refresh_continuous_aggregate('{view}', '{lo}', '{hi}');" for view in REFRESH_VIEWS]


def connect_db():
    import psycopg

    return psycopg.connect(host=os.environ.get("DB_HOST", "timescaledb"), port=int(os.environ.get("DB_PORT", "5432")),
                           dbname=os.environ["DB_NAME"], user=os.environ.get("DB_USER", "app_reader"),
                           password=os.environ["DB_PASSWORD"], autocommit=True, connect_timeout=10,
                           options="-c statement_timeout=10000")


def mqtt_client():
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=os.environ.get("SIM_CLIENT_ID", "aip-simulator-backfill"),
                         protocol=mqtt.MQTTv5)
    client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    client.connect(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    return client


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="simulator.backfill", description="Historia symulatora i uzupełnianie luk (E3-k5)")
    parser.add_argument("--from", dest="start", required=True, help="początek zakresu ISO 8601 ze strefą")
    parser.add_argument("--to", dest="end", required=True, help="koniec zakresu (bez niego) ISO 8601 ze strefą")
    parser.add_argument("--devices", choices=("all", "meters", "pump"), default="all")
    parser.add_argument("--inflight", type=int, default=100)
    parser.add_argument("--rate", type=float, default=None, help="sufit wiadomości/s (domyślnie brak, K5-D2)")
    parser.add_argument("--chunk-minutes", type=int, default=5, help="porcja czasu modelu między kontrolami bazy")
    parser.add_argument("--fill-gaps", action="store_true", help="wyślij tylko niepełne minuty (wymaga bazy)")
    args = parser.parse_args(argv)
    try:
        start, end = parse_moment(args.start), parse_moment(args.end)
        if end <= start:
            raise ValueError("--to musi być po --from")
        config = load_config(os.environ.get("DEVICES_CONFIG", "/config/devices.yaml"))
        sim = Simulator(config, os.environ.get("SIM_CACHE") or None)
        plan = Plan(sim, start, end, args.devices)
    except (ConfigError, ValueError) as exc:
        LOG.error("błąd: %s", exc)
        return 2
    db = Db(connect_db())
    client = mqtt_client()
    window = Window(client, args.inflight, args.rate)
    try:
        if args.fill_gaps:
            result = fill_gaps(plan, window, db, start, end)
            LOG.info("uzupełnianie luk %s – %s: brakujących minut przed %d, wysłano %d wiadomości, po %d %s",
                     iso_ms(start), iso_ms(end), result["missing_before"], result["messages"], result["missing_after"],
                     result["missing_after_detail"] or "")
            return 0 if result["missing_after"] == 0 else 1
        LOG.info("historia %s – %s (%s): start; okno w locie %d, porcja %d min, sufit tempa %s", iso_ms(start), iso_ms(end),
                 args.devices, args.inflight, args.chunk_minutes, args.rate or "brak")
        stats = run(plan, window, db, start, end, chunk_s=args.chunk_minutes * 60)
        sim.cache.flush()
        LOG.info("historia gotowa: %d wiadomości w %.0f s (%.0f/s), oczekiwanie na bazę %.0f s; okno sim_backfill: %s – %s",
                 stats["messages"], stats["elapsed_s"], stats["rate"], stats["waited_s"], iso_ms(start), iso_ms(end))
        LOG.info("odśwież agregaty kontem administratora (psql), w tej kolejności:\n%s", "\n".join(refresh_statements(start, end)))
        return 0
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    sys.exit(main())
