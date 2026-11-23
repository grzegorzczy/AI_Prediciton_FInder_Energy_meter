"""Dostęp do bazy: połączenie, synchronizacja `devices`, zapis paczek, klasyfikacja błędów.

Rola `app_writer` zapisuje tylko do tabel measurements i devices (bez usuwania i bez zmian schematu). Hasło tylko
ze zmiennej środowiskowej. Treść zapytań ani hasła nigdy nie trafiają do logu: błędy są streszczane do klasy i pierwszej linii.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

import psycopg
from psycopg.types.json import Jsonb

from .config import IngestConfig
from .validate import Row

LOG = logging.getLogger("ingest.db")


class StoreUnavailable(Exception):
    """Błąd przejściowy lub konfiguracyjny po stronie bazy: nic nie tracimy, ponawiamy z cofaniem."""


class NeedsResync(Exception):
    """Naruszenie klucza obcego: brakuje wiersza w devices; synchronizacja i jedna ponowna próba."""


class ConstraintError(Exception):
    """Naruszenie ograniczenia (CHECK, typ danych) dla co najmniej jednego wiersza paczki."""


INSERT_BATCH = (
    "INSERT INTO measurements (time, device_id, metric, value, unit, source) "
    "SELECT * FROM unnest(%s::timestamptz[], %s::text[], %s::text[], %s::float8[], %s::text[], %s::text[]) "
    "ON CONFLICT DO NOTHING"
)
UPSERT_DEVICE = (
    "INSERT INTO devices (device_id, name, site, line, kind, source, enabled, meta) "
    "VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s) "
    "ON CONFLICT (device_id) DO UPDATE SET name = EXCLUDED.name, site = EXCLUDED.site, line = EXCLUDED.line, "
    "kind = EXCLUDED.kind, source = EXCLUDED.source, enabled = TRUE, meta = EXCLUDED.meta"
)
DISABLE_MISSING = "UPDATE devices SET enabled = FALSE WHERE enabled AND device_id <> ALL(%s)"


def summarize(exc: BaseException) -> str:
    """Klasa błędu i pierwsza linia komunikatu, bez treści zapytania."""
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0] if text else ''}".strip()


class Store:
    def __init__(self, host: str, port: int, dbname: str, user: str, password: str,
                 statement_timeout_ms: int = 30000) -> None:
        self._params = dict(
            host=host, port=port, dbname=dbname, user=user, password=password, autocommit=True,
            connect_timeout=5, application_name="aip-ingest", options=f"-c statement_timeout={statement_timeout_ms}",
        )
        self._conn: psycopg.Connection | None = None

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _connection(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg.connect(**self._params)
            except psycopg.Error as exc:
                self._conn = None
                reason = summarize(exc)
                if "password authentication failed" in reason or "does not exist" in reason:
                    reason += " (sprawdź APP_WRITER_PASSWORD i czy migrate utworzył rolę app_writer)"
                raise StoreUnavailable(reason) from None
        return self._conn

    def _run(self, action):
        """Wykonuje akcję na połączeniu i tłumaczy błędy bazy na wyjątki znaczące dla potoku."""
        conn = self._connection()
        try:
            return action(conn)
        except psycopg.errors.ForeignKeyViolation:
            raise NeedsResync() from None
        except (psycopg.errors.IntegrityError, psycopg.errors.DataError) as exc:
            raise ConstraintError(summarize(exc)) from None
        except psycopg.errors.UndefinedTable:
            raise StoreUnavailable("schemat bazy nie jest gotowy (brak tabel; czy migrate przebiegł?)") from None
        except psycopg.errors.InsufficientPrivilege as exc:
            raise StoreUnavailable(f"brak uprawnień: {summarize(exc)}") from None
        except psycopg.Error as exc:
            self.close()                                  # nieznany stan połączenia: łączymy od nowa
            raise StoreUnavailable(summarize(exc)) from None

    def sync_devices(self, config: IngestConfig) -> tuple[int, int]:
        """Upsert urządzeń z devices.yaml (w tym PLC); usunięte z configu dostają enabled = FALSE."""

        def action(conn: psycopg.Connection) -> tuple[int, int]:
            with conn.transaction():
                for spec in config.devices.values():
                    conn.execute(UPSERT_DEVICE, (spec.device_id, spec.name, config.site, config.line, spec.kind,
                                                 spec.source, Jsonb(spec.meta)))
                disabled = conn.execute(DISABLE_MISSING, (list(config.devices),)).rowcount
            return len(config.devices), disabled

        return self._run(action)

    def insert_rows(self, rows: Sequence[Row]) -> int:
        """Zapis paczki w jednym zapytaniu; zwraca liczbę nowych wierszy (reszta to duplikaty)."""
        arrays = (
            [r.time for r in rows], [r.device_id for r in rows], [r.metric for r in rows],
            [r.value for r in rows], [r.unit for r in rows], [r.source for r in rows],
        )

        def action(conn: psycopg.Connection) -> int:
            return conn.execute(INSERT_BATCH, arrays).rowcount

        return self._run(action)
