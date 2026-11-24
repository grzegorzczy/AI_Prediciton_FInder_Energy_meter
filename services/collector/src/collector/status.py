"""Kody statusów publikowane jako metryki `link_status` i `meter_status` (jedno miejsce w kodzie).

Opis i polskie komunikaty dla Grafany: docs/status-codes.md (test sprawdza zgodność z tymi enumami).
"""
from __future__ import annotations

from enum import IntEnum


class LinkStatus(IntEnum):
    """Stan łącza z PLC: metryka `link_status` urządzenia PLC (nazwa metryki i id urządzenia są w configu)."""

    OK = 0
    PLC_OFFLINE = 1          # brak połączenia, timeout, błąd Modbus, krótka odpowiedź
    PLC_STOPPED = 2          # heartbeat bez zmiany dłużej niż heartbeat_timeout_s
    MAP_VERSION_MISMATCH = 3  # rejestr map_version różny od oczekiwanego


# Kody błędów komunikacji PLC-licznik z rejestru error_code (metryka `meter_error_code`), nazwy z dokumentacji CODESYS
# `MB_ErrorCodes` biblioteki IoDrvModbus (helpme-codesys.com), zweryfikowane przez architekta 24.11.2026.
# Kod spoza tablicy jest logowany wyłącznie liczbowo. Opis: docs/status-codes.md (test sprawdza zgodność).
ERROR_CODE_NAMES: dict[int, str] = {
    161: "RESPONSE_TIMEOUT",       # 16#A1
    162: "RESPONSE_CRC_FAIL",      # 16#A2
    163: "RESPONSE_WRONG_SLAVE",   # 16#A3
}


def describe_error_code(code: int) -> str:
    """Postać do logu: `error_code=162, 0xA2, RESPONSE_CRC_FAIL` (nazwa tylko dla znanego kodu)."""
    text = f"error_code={code}, 0x{code:02X}"
    name = ERROR_CODE_NAMES.get(code)
    return f"{text}, {name}" if name else text


class MeterStatus(IntEnum):
    """Stan licznika: metryka `meter_status`. 0-2 wprost z rejestru PLC, 10 liczy collector."""

    OK = 0
    COMM_ERROR = 1           # błąd komunikacji PLC-licznik (RS485), PLC trzyma 3 s po ostatnim błędzie
    NO_DATA = 2              # licznik nie odpowiedział od startu PLC (do ok. 10 s po starcie)
    SERIAL_MISMATCH = 10     # pod blokiem jest inny licznik niż w config/devices.yaml
