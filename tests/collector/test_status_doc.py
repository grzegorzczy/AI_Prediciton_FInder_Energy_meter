"""docs/status-codes.md opisuje te same kody co enumy w status.py (jedno miejsce w kodzie, dokument zgodny)."""
from __future__ import annotations

import re

from collector.status import ERROR_CODE_NAMES, LinkStatus, MeterStatus
from dbtools import REPO

ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`(\w+)`\s*\|")


def documented(section_marker: str) -> dict[int, str]:
    text = (REPO / "docs" / "status-codes.md").read_text(encoding="utf-8")
    start = text.index(section_marker)
    end = text.find("\n## ", start + 1)
    block = text[start:end if end != -1 else None]
    return {int(m.group(1)): m.group(2) for line in block.splitlines() if (m := ROW.match(line))}


def test_link_status_codes_match_the_document():
    assert documented("## `link_status`") == {int(s): s.name for s in LinkStatus}


def test_meter_status_codes_match_the_document():
    assert documented("## `meter_status`") == {int(s): s.name for s in MeterStatus}


def test_documented_codes_are_the_expected_ones():
    assert [int(s) for s in LinkStatus] == [0, 1, 2, 3]
    assert [int(s) for s in MeterStatus] == [0, 1, 2, 10]


def test_document_describes_timing_behaviour():
    text = (REPO / "docs" / "status-codes.md").read_text(encoding="utf-8")
    for fragment in ("ok. 10 s", "3 s", "ok. 1 s", "NO_DATA"):
        assert fragment in text


def test_error_code_table_matches_the_document():
    text = (REPO / "docs" / "status-codes.md").read_text(encoding="utf-8")
    start = text.index("## `meter_error_code`")
    block = text[start:text.index("\n## ", start + 1)]
    row = re.compile(r"^\|\s*(\d+)\s*\|\s*`0x([0-9A-F]+)`\s*\|\s*`(\w+)`\s*\|")
    rows = [m.groups() for line in block.splitlines() if (m := row.match(line))]
    assert {int(code): name for code, _, name in rows} == ERROR_CODE_NAMES
    assert all(int(code) == int(hexa, 16) for code, hexa, _ in rows)
    assert "MB_ErrorCodes" in block and "helpme-codesys.com" in block      # cytowane źródło nazw


def test_document_states_the_row_model():
    text = (REPO / "docs" / "status-codes.md").read_text(encoding="utf-8")
    section = text[text.index("## Liczba wierszy na sekundę"):]
    for fragment in ("**13**", "**5**", "**1**"):
        assert fragment in section
