"""Sterownik Modbus TCP do PLC. Wyłącznie odczyt: funkcja 04 (Read Input Registers).

Reguła 1: do PLC nigdy nie piszemy. Klient biblioteki jest zamknięty w ReadOnlyModbusClient, który wystawia
tylko połączenie, rozłączenie i odczyt rejestrów wejściowych. Testy sprawdzają to na trzech poziomach: interfejs
klasy, brak nazw metod zapisu w źródłach oraz kody funkcji, które faktycznie docierają do serwera atrapy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from ..codec import Registers
from ..config import PlcConfig
from .base import SourceError

LOG = logging.getLogger("collector.driver")


class ReadOnlyModbusClient:
    """Cienka nakładka na klienta pymodbus: connect, close, read_input_registers. Nic więcej."""

    def __init__(self, host: str, port: int, timeout_s: float) -> None:
        # retries=0 i reconnect_delay=0: ponawianiem i łączeniem zarządza sterownik, a nie biblioteka
        # (domyślnie 3 ponowienia po 3 s zablokowałyby cykl na kilkanaście sekund).
        self.__client = AsyncModbusTcpClient(
            host, port=port, timeout=timeout_s, retries=0, reconnect_delay=0
        )

    @property
    def connected(self) -> bool:
        return bool(self.__client.connected)

    async def connect(self) -> bool:
        await self.__client.connect()
        return self.connected

    def close(self) -> None:
        self.__client.close()

    async def read_input_registers(self, address: int, count: int, unit_id: int) -> list[int]:
        response = await self.__client.read_input_registers(address, count=count, device_id=unit_id)
        if response.isError():
            raise ModbusException(f"odpowiedź z błędem: {response}")
        return list(response.registers)


class ModbusPlcDriver:
    def __init__(
        self,
        plc: PlcConfig,
        client_factory: Callable[[PlcConfig], ReadOnlyModbusClient] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._plc = plc
        self._factory = client_factory or (lambda p: ReadOnlyModbusClient(p.host, p.port, p.timeout_s))
        self._clock = clock
        self._client: ReadOnlyModbusClient | None = None
        self._failures = 0
        self._next_attempt = 0.0

    @property
    def failures(self) -> int:
        return self._failures

    def _backoff_delay(self) -> float:
        plc = self._plc
        return min(plc.reconnect_initial_s * (2 ** max(self._failures - 1, 0)), plc.reconnect_max_s)

    def _record_failure(self) -> None:
        self._failures += 1
        self._next_attempt = self._clock() + self._backoff_delay()

    async def _drop(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # zamykanie zerwanego połączenia nie może zatrzymać cyklu
                pass
            self._client = None

    async def read(self) -> Registers:
        plc = self._plc
        if self._client is None or not self._client.connected:
            if self._clock() < self._next_attempt:
                raise SourceError("oczekiwanie na kolejną próbę połączenia (cofanie)")
            await self._drop()
            client = self._factory(plc)
            try:
                connected = await asyncio.wait_for(client.connect(), plc.timeout_s + 1.0)
            except (OSError, ModbusException, asyncio.TimeoutError) as exc:
                client.close()
                self._record_failure()
                raise SourceError(f"nie można połączyć z {plc.host}:{plc.port}: {exc!r}") from exc
            except asyncio.CancelledError:
                client.close()                      # zadanie porzucone w trakcie łączenia: nie zostawiamy otwartego gniazda
                raise
            if not connected:
                client.close()
                self._record_failure()
                raise SourceError(f"nie można połączyć z {plc.host}:{plc.port}")
            self._client = client

        try:
            words = await asyncio.wait_for(
                self._client.read_input_registers(plc.read_start, plc.read_count, plc.unit_id),
                plc.timeout_s + 1.0,
            )
        except (OSError, ModbusException, asyncio.TimeoutError) as exc:
            await self._drop()
            self._record_failure()
            raise SourceError(f"odczyt FC04 nie powiódł się: {exc!r}") from exc
        except asyncio.CancelledError:
            await self._drop()                      # zadanie porzucone w trakcie odczytu
            raise

        if len(words) != plc.read_count:
            await self._drop()
            self._record_failure()
            raise SourceError(f"krótka odpowiedź: {len(words)} z {plc.read_count} rejestrów")

        self._failures = 0
        self._next_attempt = 0.0
        return Registers(plc.read_start, words)

    async def reset(self) -> None:
        """Po porzuceniu zawieszonego odczytu: nowy klient i brak cofania przed następną próbą (K6-U2)."""
        await self._drop()
        self._failures = 0
        self._next_attempt = 0.0

    async def close(self) -> None:
        await self._drop()
