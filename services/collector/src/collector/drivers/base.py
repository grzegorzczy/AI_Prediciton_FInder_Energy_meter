"""Wspólny interfejs źródeł danych. Dziś Modbus TCP z PLC, później m.in. OPC UA (bez zmian w reszcie)."""
from __future__ import annotations

from typing import Protocol

from ..codec import Registers


class SourceError(Exception):
    """Odczyt się nie udał: brak połączenia, timeout, błąd protokołu, krótka odpowiedź."""


class SourceDriver(Protocol):
    async def read(self) -> Registers:
        """Zwraca świeży obraz rejestrów albo zgłasza SourceError. Nie blokuje dłużej niż timeout źródła."""
        ...

    async def close(self) -> None:
        ...
