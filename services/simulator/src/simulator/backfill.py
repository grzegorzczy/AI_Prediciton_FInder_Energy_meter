"""Wgrywanie historii symulatora (E3-k5) i uzupełnianie luk. Uruchamiane jednorazowo usługą `simulator-tools` (K5-D1):

    docker compose run --rm simulator-tools python -m simulator.backfill --from 2026-11-17T00:00:00Z --to 2026-12-01T00:00:00Z
    docker compose run --rm simulator-tools python -m simulator.backfill --from … --to … --fill-gaps

Zakres (pełne minuty): liczniki co 1 s od `meter_anchor`, pompa co `history.pump_step_s` (60 s) od `bearing_installed_at`.

Jedna ścieżka dla wgrania, wznowienia i uzupełniania luk: dla każdej doby zakresu zapytanie do `measurements` (konto tylko
do odczytu, K5-D1) o liczności w minutach każdej publikowanej metryki (liczniki 6, pompa 5; K5-U1); wysyłane są tylko minuty
urządzeń niepełne (w całości – duplikaty pomija baza). Wznowienie po przerwaniu = to samo polecenie; pełne minuty są pomijane.

Sterowanie przepływem end-to-end: QoS 1 z oknem w locie (`--inflight`, K5-D2) ogranicza tylko wiadomości do BROKERA (PUBACK
wysyła broker, nie ingest), a kolejka brokera dla ingestu jest wspólna z danymi prawdziwymi (limit 80 000; przy przepełnieniu
broker gubi najnowsze, także prawdziwe). Dlatego publikacja idzie porcjami (`--chunk-messages`, domyślnie 7 200) i przed
kolejną porcją narzędzie czeka, aż ostatnia wysłana minuta porcji jest w bazie kompletna – kolejka brokera dla ingestu nie
przekracza jednej porcji. Wartości są funkcją czasu, więc ponowne wysłanie daje dokładnie te same liczby. Liczniki korzystają
z pamięci sum dobowych (`SIM_CACHE`, wspólny wolumen z usługą, K5-U4).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import uuid
from collections import deque
from datetime import datetime

from . import health
from .config import ConfigError, load_config
from .live import iso_ms
from .samples import METER_METRICS, PUMP_METRICS, Simulator

LOG = logging.getLogger("simulator.backfill")
DAY = 86400
CHUNK_MIN, CHUNK_MAX = 100, 20000          # porcja wiadomości: górna granica dużo poniżej limitu kolejki brokera (80 000)


def parse_moment(text: str) -> int:
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        raise ValueError(f"{text}: wymagana strefa czasowa (np. Z)")
    return int(moment.timestamp())


class Plan:
    """Które urządzenia i chwile należą do historii w zakresie [start, end) (pełne minuty)."""

    def __init__(self, sim: Simulator, start: int, end: int, which: str = "all") -> None:
        if start % 60 or end % 60:
            raise ValueError("--from i --to muszą być pełnymi minutami (sekundy = 0)")
        cfg = sim.config
        self.sim, self.start, self.end = sim, start, end
        self.meters = set(sim.meters) if which in ("all", "meters") else set()
        self.pumps = set(sim.pumps) if which in ("all", "pump") else set()
        self.meter_from = max(start, int(cfg.require_meter_anchor().timestamp())) if self.meters else end
        self.pump_step = cfg.history.pump_step_s
        if self.pumps and self.pump_step != 60:
            raise ValueError("simulator.history.pump_step_s musi wynosić 60 (w historii 1 próbka pompy na minutę)")
        self.pump_from = {}
        for dev in self.pumps:
            installed = int(cfg.require_bearing_installed_at(cfg.device(dev)).timestamp())
            first = max(start, installed)
            self.pump_from[dev] = first + (-first) % self.pump_step          # wyrównanie do kroku (pełne minuty)

    def metrics(self, device: str) -> list[str]:
        return [m for m, _ in (METER_METRICS if device in self.meters else PUMP_METRICS)]

    def first(self, device: str) -> int:
        return self.meter_from if device in self.meters else self.pump_from[device]

    def per_minute(self, device: str) -> int:
        """Próbek jednej metryki w pełnej minucie historii."""
        return 60 if device in self.meters else 1

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

    def __init__(self, client, inflight: int = 100, rate: float | None = None, clock=time.monotonic, sleep=time.sleep,
                 timeout: float = 60.0):
        if inflight < 1:
            raise ValueError("inflight musi być >= 1")
        self.client, self.inflight, self.rate, self.timeout = client, inflight, rate, timeout
        self.clock, self.sleep = clock, sleep
        self.pending: deque = deque()
        self.sent = 0
        self._t0 = clock()

    def _wait(self, info) -> None:
        info.wait_for_publish(timeout=self.timeout)
        if not info.is_published():
            raise TimeoutError(f"broker nie potwierdził publikacji w {self.timeout:.0f} s (połączenie zerwane?)")

    def publish(self, topic: str, payload: bytes) -> None:
        while len(self.pending) >= self.inflight:
            self._wait(self.pending.popleft())
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
            self._wait(self.pending.popleft())


class Db:
    """Odczyt tylko do odczytu (konto app_reader, limit czasu zapytania): liczności w minutach."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def minute_counts(self, device: str, metric: str, start: int, end: int) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT extract(epoch FROM time_bucket('1 minute', time))::bigint, count(*) FROM measurements "
            "WHERE device_id = %s AND metric = %s AND time >= to_timestamp(%s) AND time < to_timestamp(%s) GROUP BY 1",
            (device, metric, start, end)).fetchall()
        return {int(m): int(n) for m, n in rows}

    def minute_rows(self, devices: list[str], minute: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT device_id, count(*) FROM measurements WHERE device_id = ANY(%s) "
            "AND time >= to_timestamp(%s) AND time < to_timestamp(%s) GROUP BY 1", (devices, minute, minute + 60)).fetchall()
        return {d: int(n) for d, n in rows}


def incomplete_minutes(plan: Plan, db: Db | None, start: int, end: int) -> dict[str, set[int]]:
    """Minuty (pełne, w zakresie) z brakiem którejkolwiek publikowanej metryki – per urządzenie (K5-U1). Zapytania dobami,
    tylko od początku historii urządzenia. Bez bazy: wszystkie minuty historii."""
    missing: dict[str, set[int]] = {}
    for device in sorted(plan.meters | plan.pumps):
        first, need = plan.first(device), plan.per_minute(device)
        for day in range(start, end, DAY):
            day_end = min(day + DAY, end)
            lo = max(day, first)
            if lo >= day_end:
                continue
            minutes = range(lo, day_end, 60)
            if db is None:
                missing.setdefault(device, set()).update(minutes)
                continue
            for metric in plan.metrics(device):
                counts = db.minute_counts(device, metric, lo, day_end)
                gaps = [m for m in minutes if counts.get(m, 0) < need]
                if gaps:
                    missing.setdefault(device, set()).update(gaps)
    return missing


def wait_minute_complete(plan: Plan, db: Db, minute: int, devices: set[str], timeout: float = 600.0,
                         clock=time.monotonic, sleep=time.sleep) -> float:
    """Sterowanie przepływem: czeka, aż minuta jest w bazie kompletna dla podanych urządzeń; zwraca czas oczekiwania."""
    t0 = clock()
    need = {d: plan.per_minute(d) * len(plan.metrics(d)) for d in devices}
    while True:
        rows = db.minute_rows(sorted(devices), minute)
        if all(rows.get(d, 0) >= n for d, n in need.items()):
            return clock() - t0
        if clock() - t0 > timeout:
            raise TimeoutError(f"ingest nie zapisał minuty {iso_ms(minute)} ({', '.join(sorted(devices))}) w {timeout:.0f} s")
        sleep(0.5)


def run(plan: Plan, window: Window, db: Db | None, start: int, end: int, chunk_messages: int = 7200,
        progress_s: float = 60.0, clock=time.monotonic, sleep=time.sleep, health_file: str | None = None,
        wait_timeout: float = 600.0) -> dict:
    """Wysyła niepełne minuty zakresu (bez bazy: wszystkie) porcjami; po każdej porcji czeka na bazę (gdy db podane)."""
    stats = {"messages": 0, "chunks": 0, "waited_s": 0.0, "device_minutes_sent": 0, "device_minutes_skipped": 0}
    t0 = last_log = clock()
    in_chunk, last = 0, None

    def close_chunk():
        nonlocal in_chunk
        window.drain()
        if db is not None and last is not None:
            stats["waited_s"] += wait_minute_complete(plan, db, last[0], last[1], wait_timeout, clock, sleep)
        stats["chunks"] += 1
        in_chunk = 0

    for day in range(start, end, DAY):
        day_end = min(day + DAY, end)
        missing = incomplete_minutes(plan, db, day, day_end)
        by_minute: dict[int, set[str]] = {}
        for device, minutes in missing.items():
            for minute in minutes:
                by_minute.setdefault(minute, set()).add(device)
        total = sum(len(range(max(day, plan.first(d)), day_end, 60)) for d in plan.meters | plan.pumps
                    if max(day, plan.first(d)) < day_end)
        stats["device_minutes_skipped"] += total - sum(len(v) for v in missing.values())
        for minute in sorted(by_minute):
            devices = by_minute[minute]
            for t, present in plan.moments(minute, minute + 60):
                chosen = present & devices
                if chosen:
                    for topic, payload in plan.messages(t, chosen):
                        window.publish(topic, payload)
                        stats["messages"] += 1
                        in_chunk += 1
            last = (minute, devices)
            stats["device_minutes_sent"] += len(devices)
            if in_chunk >= chunk_messages:
                close_chunk()
            if clock() - last_log >= progress_s:
                last_log = clock()
                rate = stats["messages"] / max(clock() - t0, 1e-6)
                eta = (end - minute) / max(minute - start, 1) * (clock() - t0)
                LOG.info("postęp: czas modelu %s, %d wiadomości, %.0f/s, do końca ok. %.0f min",
                         iso_ms(minute), stats["messages"], rate, eta / 60)
                if health_file:
                    health.touch(health_file)
    if in_chunk:
        close_chunk()
    stats["elapsed_s"] = clock() - t0
    stats["rate"] = stats["messages"] / max(stats["elapsed_s"], 1e-6)
    return stats


def fill_gaps(plan: Plan, window: Window, db: Db, start: int, end: int, chunk_messages: int = 7200,
              settle_s: float = 120.0, sleep=time.sleep) -> dict:
    """Uzupełnienie luk = ten sam przebieg co wgranie (tylko niepełne minuty, ze sterowaniem przepływem) plus kontrola
    końcowa: brakujące minuty urządzeń przed i po (cel 0)."""
    before = sum(len(v) for v in incomplete_minutes(plan, db, start, end).values())
    stats = run(plan, window, db, start, end, chunk_messages, sleep=sleep)
    deadline = time.monotonic() + settle_s
    after = incomplete_minutes(plan, db, start, end)
    while after and time.monotonic() < deadline:
        sleep(2)
        after = incomplete_minutes(plan, db, start, end)
    return {"missing_before": before, "messages": stats["messages"], "chunks": stats["chunks"],
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


def mqtt_client(inflight: int, timeout: float = 15.0):
    """Klient QoS 1: okno w locie paho = --inflight; start dopiero po potwierdzonym połączeniu (CONNACK sukces)."""
    import threading

    import paho.mqtt.client as mqtt

    client_id = f"{os.environ.get('SIM_CLIENT_ID', 'aip-simulator-backfill')}-{uuid.uuid4().hex[:6]}"   # równoległe przebiegi
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
    client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
    client.max_inflight_messages_set(inflight)
    result = {}
    connected = threading.Event()

    def on_connect(_client, _userdata, _flags, reason_code, _properties):
        result["rc"] = reason_code
        connected.set()

    client.on_connect = on_connect
    client.connect(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", "1883")))
    client.loop_start()
    if not connected.wait(timeout) or result["rc"].is_failure:
        client.loop_stop()
        raise RuntimeError(f"broker MQTT odrzucił połączenie lub nie odpowiedział ({result.get('rc', 'brak odpowiedzi')}); "
                           "sprawdź MQTT_SIM_USER/MQTT_SIM_PASSWORD")
    return client


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="simulator.backfill", description="Historia symulatora i uzupełnianie luk (E3-k5)")
    parser.add_argument("--from", dest="start", required=True, help="początek zakresu ISO 8601 ze strefą, pełna minuta")
    parser.add_argument("--to", dest="end", required=True, help="koniec zakresu (bez niego) ISO 8601 ze strefą, pełna minuta")
    parser.add_argument("--devices", choices=("all", "meters", "pump"), default="all")
    parser.add_argument("--inflight", type=int, default=100)
    parser.add_argument("--rate", type=float, default=None, help="sufit wiadomości/s (domyślnie brak, K5-D2)")
    parser.add_argument("--chunk-messages", type=int, default=7200,
                        help=f"wiadomości w porcji między kontrolami bazy ({CHUNK_MIN}–{CHUNK_MAX})")
    parser.add_argument("--fill-gaps", action="store_true", help="po przebiegu kontrola końcowa; kod 1, gdy zostały luki")
    args = parser.parse_args(argv)
    try:
        start, end = parse_moment(args.start), parse_moment(args.end)
        if end <= start:
            raise ValueError("--to musi być po --from")
        if not CHUNK_MIN <= args.chunk_messages <= CHUNK_MAX:
            raise ValueError(f"--chunk-messages poza zakresem {CHUNK_MIN}–{CHUNK_MAX}")
        if not 1 <= args.inflight <= 1000:
            raise ValueError("--inflight poza zakresem 1–1000")
        config = load_config(os.environ.get("DEVICES_CONFIG", "/config/devices.yaml"))
        sim = Simulator(config, os.environ.get("SIM_CACHE") or None)
        plan = Plan(sim, start, end, args.devices)
    except (ConfigError, ValueError) as exc:
        LOG.error("błąd: %s", exc)
        return 2
    try:
        db = Db(connect_db())
        client = mqtt_client(args.inflight)
    except Exception as exc:                          # noqa: BLE001 – jasny komunikat zamiast śladu stosu
        LOG.error("błąd połączenia: %s", exc)
        return 1
    window = Window(client, args.inflight, args.rate)
    try:
        LOG.info("%s %s – %s (%s): start; okno w locie %d, porcja %d wiadomości, sufit tempa %s",
                 "uzupełnianie luk" if args.fill_gaps else "historia", iso_ms(start), iso_ms(end), args.devices,
                 args.inflight, args.chunk_messages, args.rate or "brak")
        if args.fill_gaps:
            result = fill_gaps(plan, window, db, start, end, args.chunk_messages)
            LOG.info("uzupełnianie luk %s – %s: brakujących minut urządzeń przed %d, wysłano %d wiadomości, po %d %s",
                     iso_ms(start), iso_ms(end), result["missing_before"], result["messages"], result["missing_after"],
                     result["missing_after_detail"] or "")
            code = 0 if result["missing_after"] == 0 else 1
        else:
            stats = run(plan, window, db, start, end, args.chunk_messages)
            LOG.info("historia gotowa: %d wiadomości w %.0f s (%.0f/s), porcji %d, oczekiwanie na bazę %.0f s, pominięte pełne "
                     "minuty urządzeń %d; okno sim_backfill: %s – %s", stats["messages"], stats["elapsed_s"], stats["rate"],
                     stats["chunks"], stats["waited_s"], stats["device_minutes_skipped"], iso_ms(start), iso_ms(end))
            code = 0
        sim.cache.flush()
        LOG.info("odśwież agregaty kontem administratora (psql), w tej kolejności:\n%s", "\n".join(refresh_statements(start, end)))
        return code
    except (TimeoutError, RuntimeError) as exc:
        LOG.error("przerwane: %s; wznowienie tym samym poleceniem (pełne minuty są pomijane)", exc)
        return 1
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    sys.exit(main())
