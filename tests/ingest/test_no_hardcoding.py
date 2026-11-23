"""Reguły 1, 3 i 6 dla ingestu: brak danych urządzeń, haseł i destrukcyjnych poleceń SQL w kodzie."""
from __future__ import annotations

import re

from dbtools import REPO

SOURCE_DIR = REPO / "services" / "ingest"
IP_LITERAL = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def python_sources():
    return list(SOURCE_DIR.rglob("*.py"))


def test_there_are_sources_to_scan():
    assert len(python_sources()) >= 8


def test_no_ip_addresses_or_device_identifiers_in_code():
    offenders = []
    for path in python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if IP_LITERAL.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{number}: adres IP")
            for token in ("F0183363", "finder_7m24", "plc-01", "zaklad1", "linia1", "192.168"):
                if token in line:
                    offenders.append(f"{path.relative_to(REPO)}:{number}: {token}")
    assert offenders == []


def test_no_destructive_sql_in_code():
    """Ingest tylko zapisuje dane; rola app_writer nie ma DELETE ani DDL (k2), kod też ich nie zawiera."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in python_sources())
    for keyword in ("DELETE FROM", "DROP ", "TRUNCATE", "ALTER ", "CREATE TABLE", "GRANT "):
        assert keyword not in text, keyword


def test_only_expected_tables_are_written():
    text = "\n".join(p.read_text(encoding="utf-8") for p in python_sources())
    targets = set(re.findall(r"(?:INSERT INTO|(?<!DO )UPDATE)\s+(\w+)", text))   # "DO UPDATE SET" to część upsertu
    assert targets == {"measurements", "devices"}


def test_no_secret_values_in_code_or_dockerfile():
    for path in python_sources() + [SOURCE_DIR / "Dockerfile"]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"password\s*=\s*[\"'][^\"']+[\"']", text, re.IGNORECASE), path


def test_password_is_not_formatted_into_log_messages():
    """Hasła ze środowiska nie mogą trafić do logu: kod loguje streszczenia błędów, nie parametry połączenia."""
    for path in python_sources():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "LOG." in line:
                assert "password" not in line.lower() or "APP_WRITER_PASSWORD" in line, line
