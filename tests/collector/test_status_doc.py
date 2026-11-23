"""docs/status-codes.md opisuje te same kody co enumy w status.py (jedno miejsce w kodzie, dokument zgodny)."""
from __future__ import annotations

import re

from collector.status import LinkStatus, MeterStatus
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
