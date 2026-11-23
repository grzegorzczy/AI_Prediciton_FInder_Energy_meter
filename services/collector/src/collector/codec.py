"""Dekodowanie rejestrów Modbus zgodnie z docs/modbus-map.md.

Wartości 32-bitowe: starsze słowo pierwsze (big-endian), w słowie starszy bajt pierwszy.
Energia: stan licznika w Wh = mantysa (DINT) x 10^wykładnik (INT), nie REAL kWh.
"""
from __future__ import annotations

import struct
from collections.abc import Sequence

TYPE_LENGTH = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "real32": 2}


class RegisterError(Exception):
    """Adres poza odczytanym zakresem lub niepoprawne dane."""


class Registers:
    """Obraz rejestrów z jednego zapytania FC04: `start` to adres pierwszego rejestru."""

    def __init__(self, start: int, values: Sequence[int]) -> None:
        self.start = start
        self.values = list(values)

    def __len__(self) -> int:
        return len(self.values)

    def _word(self, address: int) -> int:
        index = address - self.start
        if not 0 <= index < len(self.values):
            raise RegisterError(f"rejestr {address} poza odczytanym zakresem")
        word = self.values[index]
        if not 0 <= word <= 0xFFFF:
            raise RegisterError(f"rejestr {address}: wartość {word} nie jest słowem 16-bitowym")
        return word

    def u16(self, address: int) -> int:
        return self._word(address)

    def i16(self, address: int) -> int:
        word = self._word(address)
        return word - 0x10000 if word >= 0x8000 else word

    def u32(self, address: int) -> int:
        return (self._word(address) << 16) | self._word(address + 1)

    def i32(self, address: int) -> int:
        value = self.u32(address)
        return value - 0x100000000 if value >= 0x80000000 else value

    def real32(self, address: int) -> float:
        raw = struct.pack(">HH", self._word(address), self._word(address + 1))
        return struct.unpack(">f", raw)[0]

    def ascii(self, address: int, registers: int) -> str:
        """Tekst ASCII: 2 znaki na rejestr, starszy bajt pierwszy; bajty zerowe i spacje na końcu usuwane."""
        data = b"".join(self._word(address + i).to_bytes(2, "big") for i in range(registers))
        return data.decode("ascii", errors="replace").rstrip("\x00 ")

    def read(self, kind: str, address: int) -> float | int:
        if kind == "uint16":
            return self.u16(address)
        if kind == "int16":
            return self.i16(address)
        if kind == "uint32":
            return self.u32(address)
        if kind == "int32":
            return self.i32(address)
        if kind == "real32":
            return self.real32(address)
        raise RegisterError(f"nieznany typ rejestru: {kind}")

    def energy_wh(self, mantissa_address: int, exponent_address: int) -> float:
        """Stan licznika w Wh = mantysa x 10^wykładnik (arytmetyka całkowita dla wykładnika >= 0)."""
        mantissa = self.i32(mantissa_address)
        exponent = self.i16(exponent_address)
        if exponent >= 0:
            return float(mantissa * 10**exponent)
        return mantissa / 10 ** (-exponent)


def round_real32(value: float) -> float:
    """float32 -> float64 daje szum (240.39999389648438); 7 cyfr znaczących oddaje wartość z PLC (240.4)."""
    return float("%.7g" % value)
