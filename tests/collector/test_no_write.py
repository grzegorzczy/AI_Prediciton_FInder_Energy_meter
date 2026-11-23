"""Reguła 1: do PLC nigdy nie piszemy. Trzy warstwy: interfejs klasy, źródła, kody funkcji na serwerze atrapy.
Czwarty test (kody funkcji w scenariuszach) jest w test_e2e.py. Dodatkowo reguła 3: brak adresów i rejestrów w kodzie."""
from __future__ import annotations

import re

from collector.drivers.modbus_plc import ReadOnlyModbusClient
from dbtools import REPO

SOURCE_DIR = REPO / "services" / "collector"

FORBIDDEN = re.compile(r"write_|mask_write|readwrite|WriteSingle|WriteMulti|WriteCoil|WriteRegister", re.IGNORECASE)
IP_LITERAL = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def python_sources():
    return [p for p in SOURCE_DIR.rglob("*.py")]


def test_there_are_sources_to_scan():
    assert len(python_sources()) >= 8


def test_public_interface_of_the_client_is_read_only():
    public = sorted(n for n in dir(ReadOnlyModbusClient) if not n.startswith("_"))
    assert public == ["close", "connect", "connected", "read_input_registers"]


def test_no_write_function_names_in_collector_sources():
    offenders = [f"{p.relative_to(REPO)}: {m.group(0)}"
                 for p in python_sources() for m in FORBIDDEN.finditer(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_only_fc04_is_requested_in_sources():
    text = "\n".join(p.read_text(encoding="utf-8") for p in python_sources())
    assert text.count("read_input_registers(") >= 1
    assert not re.search(r"\.read_(holding_registers|coils|discrete_inputs)\(", text)


def test_no_ip_addresses_or_port_in_code():
    """Reguła 3: adres PLC i inne dane urządzeń tylko w config/devices.yaml."""
    offenders = []
    for path in python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if IP_LITERAL.search(line) or re.search(r"\b502\b", line):
                offenders.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
    assert offenders == []


def test_no_device_identifiers_or_register_numbers_in_code():
    offenders = []
    for path in python_sources():
        text = path.read_text(encoding="utf-8")
        for token in ("F0183363", "finder_7m24", "plc-01", "zaklad1", "linia1"):
            if token in text:
                offenders.append(f"{path.relative_to(REPO)}: {token}")
    assert offenders == []
