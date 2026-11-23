"""Atrapa PLC: serwer Modbus TCP (pymodbus) z rejestrami zbudowanymi wg docs/modbus-map.md.

Kodowanie rejestrów jest tu napisane niezależnie od kodu collectora (struct wprost wg mapy), żeby test nie
sprawdzał dekodera jego własnym koderem. Serwer rejestruje kody funkcji każdego żądania: test wymaga, by do atrapy
docierała wyłącznie funkcja 04 (collector nigdy nie pisze do PLC).
"""
from __future__ import annotations

import asyncio
import socket
import struct

from pymodbus.constants import ExcCodes
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

REGISTER_COUNT = 100

# Wartości z odczytu na żywym liczniku 23.11.2026 (docs/modbus-map.md).
SAMPLE_METER = {
    "status": 0, "error_code": 0, "error_count": 0, "data_age_ms": 0,
    "active_power": 7.0, "reactive_power": -8.7, "apparent_power": 19.1, "power_factor": 0.365,
    "frequency": 50.02, "voltage": 240.4, "current": 0.08,
    "energy_import_kwh": 3.5, "energy_export_kwh": 0.0,
    "import_mant": 35, "import_exp": 2, "export_mant": 0, "export_exp": 2,
    "serial": "F0183363",
}


def words_u32(value: int) -> list[int]:
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


def words_i32(value: int) -> list[int]:
    return words_u32(value & 0xFFFFFFFF)


def words_f32(value: float) -> list[int]:
    return list(struct.unpack(">HH", struct.pack(">f", value)))


def words_ascii(text: str, registers: int) -> list[int]:
    return list(struct.unpack(f">{registers}H", text.encode("ascii").ljust(2 * registers, b"\x00")))


def meter_block(**overrides) -> list[int]:
    """Blok licznika (offsety 0-33 wg mapy), 34 rejestry."""
    m = {**SAMPLE_METER, **overrides}
    block = [0] * 34
    block[0], block[1], block[2] = m["status"], m["error_code"], m["error_count"]
    block[4:6] = words_u32(m["data_age_ms"])
    for offset, key in ((6, "active_power"), (8, "reactive_power"), (10, "apparent_power"), (12, "power_factor"),
                        (14, "frequency"), (16, "voltage"), (18, "current"), (20, "energy_import_kwh"),
                        (22, "energy_export_kwh")):
        block[offset:offset + 2] = words_f32(m[key])
    block[24:26] = words_i32(m["import_mant"])
    block[26] = m["import_exp"] & 0xFFFF
    block[27:29] = words_i32(m["export_mant"])
    block[29] = m["export_exp"] & 0xFFFF
    block[30:34] = words_ascii(m["serial"], 4)
    return block


def build_image(heartbeat: int = 1, map_version: int = 1, meters=((10, {}),)) -> list[int]:
    """Cały obraz 100 rejestrów: nagłówek (heartbeat, map_version) i bloki liczników (baza, nadpisania)."""
    image = [0] * REGISTER_COUNT
    image[0:2] = words_u32(heartbeat)
    image[2] = map_version
    for base, overrides in meters:
        image[base:base + 34] = meter_block(**overrides)
    return image


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakePlc:
    """Serwer Modbus TCP z obrazem rejestrów, heartbeatem w tle i rejestrem kodów funkcji."""

    def __init__(self, port: int | None = None, host: str = "127.0.0.1") -> None:
        self.host = host
        self.port = port or free_port()
        self.function_codes: list[int] = []
        self.image = [0] * REGISTER_COUNT          # aktualny obraz rejestrów (zmieniany w trakcie testu)
        self._device = SimDevice(
            id=1,
            simdata=[SimData(0, values=[0] * REGISTER_COUNT, datatype=DataType.REGISTERS)],
            action=self._action,
        )
        self._server: ModbusTcpServer | None = None
        self._serve_task: asyncio.Task | None = None
        self._hb_task: asyncio.Task | None = None
        self._hb_running = True
        self.heartbeat = 1
        self.set_registers(2, [1])                 # map_version = 1
        self.set_meter()                           # licznik 1 w bazie 10, wartości z próbki

    # --- obraz rejestrów -------------------------------------------------------------------------------
    async def _action(self, function_code, start_address, address, count, current_registers, set_values):
        """Wywoływana przy każdym dostępie: odczyt dostaje aktualny obraz, zapis jest odrzucany."""
        if set_values is not None:
            return ExcCodes.ILLEGAL_FUNCTION
        for offset in range(count):
            current_registers[address - start_address + offset] = self.image[address + offset]
        return None

    def set_registers(self, address: int, words: list[int]) -> None:
        self.image[address:address + len(words)] = words

    def get_registers(self, address: int, count: int) -> list[int]:
        return list(self.image[address:address + count])

    def set_meter(self, base: int = 10, **overrides) -> None:
        self.set_registers(base, meter_block(**overrides))

    def set_map_version(self, version: int) -> None:
        self.set_registers(2, [version])

    def freeze_heartbeat(self, frozen: bool = True) -> None:
        self._hb_running = not frozen

    # --- cykl życia serwera ---------------------------------------------------------------------------
    def _trace(self, sending: bool, pdu):
        if not sending:                            # żądania przychodzące od klienta
            self.function_codes.append(pdu.function_code)
        return pdu

    async def _heartbeat(self) -> None:
        while True:
            if self._hb_running:
                self.heartbeat = (self.heartbeat + 1) & 0xFFFFFFFF
                self.set_registers(0, words_u32(self.heartbeat))
            await asyncio.sleep(0.05)

    async def start(self) -> None:
        self._server = ModbusTcpServer(self._device, address=(self.host, self.port), trace_pdu=self._trace)
        self._serve_task = asyncio.create_task(self._server.serve_forever())
        if self._hb_task is None:
            self._hb_task = asyncio.create_task(self._heartbeat())
        for _ in range(100):                       # czekamy, aż port zacznie słuchać
            try:
                _, writer = await asyncio.open_connection(self.host, self.port)
                writer.close()
                return
            except OSError:
                await asyncio.sleep(0.05)
        raise RuntimeError("atrapa PLC nie wystartowała")

    async def stop(self) -> None:
        """Wyłącza serwer (jak odłączenie PLC od sieci); stan rejestrów zostaje."""
        if self._server is not None:
            await self._server.shutdown()
            self._server = None
        if self._serve_task is not None:
            self._serve_task.cancel()
            try:
                await self._serve_task
            except (asyncio.CancelledError, Exception):
                pass
            self._serve_task = None

    async def close(self) -> None:
        await self.stop()
        if self._hb_task is not None:
            self._hb_task.cancel()
            try:
                await self._hb_task
            except asyncio.CancelledError:
                pass
            self._hb_task = None


class SilentServer:
    """Przyjmuje połączenia TCP i nigdy nie odpowiada: symulacja zawieszonego PLC (test timeoutu)."""

    def __init__(self) -> None:
        self.port = free_port()
        self._server: asyncio.AbstractServer | None = None
        self._writers: list[asyncio.StreamWriter] = []

    async def start(self) -> None:
        async def handle(reader, writer):
            self._writers.append(writer)
            try:
                await reader.read()
            except Exception:
                pass

        self._server = await asyncio.start_server(handle, "127.0.0.1", self.port)

    async def close(self) -> None:
        for writer in self._writers:
            writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
