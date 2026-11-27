"""Potok: walidacja -> paczka -> zapis -> potwierdzenie. Nie zależy od paho ani od prawdziwej bazy (wstrzykiwane).

Gwarancje:
- wiadomość poprawna jest potwierdzana brokerowi dopiero PO udanym zapisie paczki (ack po commit);
- wiadomość wadliwa jest potwierdzana od razu po zapisaniu powodu w liczniku i logu (nie blokuje sesji);
- przy niedostępnej bazie paczka zostaje w pamięci bez potwierdzenia, ponawianie z cofaniem 1 s -> 10 s;
- dane symulatora mają limit w pamięci (E3-k4, K4-D1): wiersz urządzenia `source = sim` dostarczony z QoS 0 jest odrzucany,
  gdy baza jest niedostępna albo w pamięci czeka już `sim_pending_max` wierszy sim (także przy wolnej, ale dostępnej bazie).
  Broker nie ogranicza liczby wiadomości QoS 0 w locie (`max_inflight_messages` dotyczy tylko QoS 1), więc bez limitu pamięć
  ingestu rosłaby aż do OOM; dane sim to funkcja czasu, lukę uzupełnia historia symulatora. Dane real NIGDY nie są odrzucane
  (także gdyby przyszły z QoS 0), a wiersze sim z QoS 1 (np. wgrywanie historii, K4-U1) też nie;
- duplikaty (ponowne dostarczenie) usuwa ON CONFLICT DO NOTHING po stronie bazy.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import IngestConfig
from .store import ConstraintError, NeedsResync, StoreUnavailable
from .validate import Rejection, Row, validate

LOG = logging.getLogger("ingest")

BACKOFF_INITIAL_S = 1.0
BACKOFF_MAX_S = 10.0
REMIND_S = 60.0


@dataclass
class Incoming:
    topic: str
    payload: bytes
    token: Any                      # np. (mid, qos) z paho; przekazywany do ack()
    qos: int = 1                    # QoS dostarczenia; 0 = dane symulatora (odrzucane przy niedostępnej bazie)


@dataclass
class Pending:
    row: Row
    token: Any


class Stats:
    def __init__(self) -> None:
        self.received = 0
        self.written = 0
        self.duplicates = 0
        self.rejected: Counter[str] = Counter()
        self.batches = 0
        self.batch_ms_total = 0.0
        self.batch_ms_max = 0.0
        self.dropped_sim = 0

    def reset_interval(self) -> None:
        self.received = self.written = self.duplicates = self.batches = self.dropped_sim = 0
        self.batch_ms_total = self.batch_ms_max = 0.0
        self.rejected = Counter()


class Pipeline:
    def __init__(
        self,
        config: IngestConfig,
        store,
        ack: Callable[[Any], None],
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        batch_max: int = 100,
        flush_s: float = 1.0,
        max_future_s: float = 300.0,
        max_past_days: float = 400.0,
        sim_pending_max: int = 3000,
    ) -> None:
        self._config, self._store, self._ack = config, store, ack
        self._clock, self._wall = clock, wall
        self._batch_max, self._flush_s = batch_max, flush_s
        self._max_future_s, self._max_past_days = max_future_s, max_past_days
        self._pending: list[Pending] = []
        self._pending_since = 0.0
        self._failures = 0
        self._retry_at = 0.0
        self._db_down_since: float | None = None
        self._last_down_log = 0.0
        self._sim_pending_max = sim_pending_max
        self._pending_sim = 0                     # wiersze sim w self._pending
        self._sim_drop_episode = 0                # odrzucone w bieżącym epizodzie (0 = brak epizodu)
        self._sim_drop_since = 0.0
        self._seen_reject: set[tuple[str, str]] = set()
        self._known_pairs: set[tuple[str, str]] = set()
        self.stats = Stats()
        self.total = Stats()                      # sumy od startu (do testów i raportów)

    # --- wejście ---------------------------------------------------------------------------------
    @property
    def pending(self) -> int:
        return len(self._pending)

    @property
    def batch_full(self) -> bool:
        return len(self._pending) >= self._batch_max

    @property
    def db_down(self) -> bool:
        return self._db_down_since is not None

    def feed(self, item: Incoming) -> None:
        self.stats.received += 1
        self.total.received += 1
        result = validate(item.topic, item.payload, self._config, self._wall(),
                          self._max_future_s, self._max_past_days)
        if isinstance(result, Rejection):
            self._reject(result, item.topic, item.payload)
            self._safe_ack(item.token)
            return
        if result.source == "sim" and item.qos == 0 and (self.db_down or self._pending_sim >= self._sim_pending_max):
            self._drop_sim(item.token)
            return
        pair = (result.device_id, result.metric)
        if pair not in self._known_pairs:
            self._known_pairs.add(pair)
            LOG.info("nowa metryka: %s/%s", *pair)
        if not self._pending:
            self._pending_since = self._clock()
        self._pending.append(Pending(result, item.token))
        if result.source == "sim":
            self._pending_sim += 1

    def _drop_sim(self, token: Any) -> None:
        self.stats.dropped_sim += 1
        self.total.dropped_sim += 1
        if self._sim_drop_episode == 0:
            self._sim_drop_since = self._clock()
            reason = "baza niedostępna" if self.db_down else f"w pamięci {self._pending_sim} wierszy sim (limit INGEST_SIM_PENDING_MAX)"
            LOG.warning("odrzucam dane symulatora (QoS 0): %s; dane prawdziwe bez zmian, lukę uzupełni historia symulatora",
                        reason)
        self._sim_drop_episode += 1
        self._safe_ack(token)

    def _end_sim_drop_episode(self) -> None:
        if self._sim_drop_episode and not self.db_down and self._pending_sim < self._sim_pending_max:
            LOG.warning("koniec odrzucania danych symulatora: odrzucono %d wiadomości w %.0f s", self._sim_drop_episode,
                        self._clock() - self._sim_drop_since)
            self._sim_drop_episode = 0

    def _reject(self, rejection: Rejection, topic: str, payload: bytes) -> None:
        self.stats.rejected[rejection.reason] += 1
        self.total.rejected[rejection.reason] += 1
        key = (rejection.reason, rejection.device_id or topic)
        if key not in self._seen_reject:
            self._seen_reject.add(key)
            LOG.warning("odrzucono (%s): %s; temat=%s ładunek=%r", rejection.reason, rejection.detail, topic[:120],
                        payload[:80])

    def _safe_ack(self, token: Any) -> None:
        try:
            self._ack(token)
        except Exception as exc:                    # błąd potwierdzenia nie może zatrzymać potoku
            LOG.warning("nie udało się potwierdzić wiadomości: %s", exc)

    # --- zapis -----------------------------------------------------------------------------------
    def tick(self) -> None:
        if not self._pending:
            return
        now = self._clock()
        if now < self._retry_at:
            return
        if len(self._pending) >= self._batch_max or now - self._pending_since >= self._flush_s:
            self.flush()

    def flush(self) -> bool:
        """Zapisuje oczekujące wiersze; True, gdy paczka została zapisana i potwierdzona."""
        if not self._pending:
            return True
        started = time.perf_counter()
        rows = [p.row for p in self._pending]
        try:
            try:
                inserted = self._store.insert_rows(rows)
            except NeedsResync:
                self._store.sync_devices(self._config)          # brakuje wiersza devices: jedna ponowna próba
                inserted = self._store.insert_rows(rows)
        except (NeedsResync, ConstraintError):
            try:
                inserted = self._insert_isolated()
            except StoreUnavailable as exc:
                self._on_unavailable(exc)
                return False
        except StoreUnavailable as exc:
            self._on_unavailable(exc)
            return False

        elapsed = (time.perf_counter() - started) * 1000
        self.stats.written += inserted
        self.total.written += inserted
        duplicates = len(rows) - inserted
        if duplicates > 0:
            self.stats.duplicates += duplicates
            self.total.duplicates += duplicates
        for pending in self._pending:
            self._safe_ack(pending.token)
        self._pending = []
        self._pending_sim = 0
        for stats in (self.stats, self.total):
            stats.batches += 1
            stats.batch_ms_total += elapsed
            stats.batch_ms_max = max(stats.batch_ms_max, elapsed)
        self._on_recovered()
        self._end_sim_drop_episode()
        return True

    def _insert_isolated(self) -> int:
        """Zapis po jednym wierszu: dobre trafiają do bazy, złe są odrzucone (db_constraint) i potwierdzone."""
        inserted = 0
        index = 0
        try:
            while index < len(self._pending):
                pending = self._pending[index]
                try:
                    try:
                        inserted += self._store.insert_rows([pending.row])
                    except NeedsResync:
                        self._store.sync_devices(self._config)
                        inserted += self._store.insert_rows([pending.row])
                except (NeedsResync, ConstraintError) as exc:
                    self._reject(Rejection("db_constraint", f"baza odrzuciła wiersz: {exc}", pending.row.device_id),
                                 f"{pending.row.device_id}/{pending.row.metric}", b"")
                self._safe_ack(pending.token)
                index += 1
        except StoreUnavailable:
            # Wiersze do indeksu `index` są już zapisane lub odrzucone i potwierdzone; reszta czeka.
            self._pending = self._pending[index:]
            self._pending_sim = sum(1 for p in self._pending if p.row.source == "sim")
            raise
        self._pending = []                       # wszystkie przetworzone i potwierdzone (bez drugiego potwierdzania)
        self._pending_sim = 0
        return inserted

    def _on_unavailable(self, exc: StoreUnavailable) -> None:
        now = self._clock()
        self._failures += 1
        delay = min(BACKOFF_INITIAL_S * 2 ** (self._failures - 1), BACKOFF_MAX_S)
        self._retry_at = now + delay
        if self._db_down_since is None:
            self._db_down_since = now
            self._last_down_log = now
            LOG.warning("baza niedostępna: %s; wiadomości czekają bez potwierdzenia (oczekujących: %d)",
                        exc, len(self._pending))
        elif now - self._last_down_log >= REMIND_S:
            self._last_down_log = now
            LOG.warning("baza nadal niedostępna od %.0f s: %s (oczekujących: %d)",
                        now - self._db_down_since, exc, len(self._pending))

    def _on_recovered(self) -> None:
        if self._db_down_since is not None:
            LOG.info("baza dostępna po %.0f s", self._clock() - self._db_down_since)
        self._db_down_since = None
        self._failures = 0
        self._retry_at = 0.0

    # --- podsumowanie ----------------------------------------------------------------------------
    def summary(self) -> str:
        s = self.stats
        avg = s.batch_ms_total / s.batches if s.batches else 0.0
        rejected = sum(s.rejected.values())
        by_reason = ", ".join(f"{k}={v}" for k, v in sorted(s.rejected.items())) or "-"
        text = (f"podsumowanie: odebrane={s.received} zapisane={s.written} duplikaty={s.duplicates} "
                f"rejected={rejected} ({by_reason}) paczki={s.batches} zapis_ms_sr={avg:.1f} "
                f"zapis_ms_maks={s.batch_ms_max:.1f} oczekujące={len(self._pending)} "
                f"baza={'NIEDOSTEPNA' if self.db_down else 'OK'}")
        if s.dropped_sim:
            text += f" odrzucone_sim={s.dropped_sim}"
        s.reset_interval()
        return text
