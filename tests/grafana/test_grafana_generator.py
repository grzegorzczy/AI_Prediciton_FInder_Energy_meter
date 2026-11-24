"""Generator dashboardów (G7-b): zgodność JSON w repo, kody statusów z dokumentu, zasada 8, opisy paneli."""
from __future__ import annotations

import re

from collector.status import ERROR_CODE_NAMES, LinkStatus, MeterStatus
from grafana_support import dashboards, load_generator, targets

FORBIDDEN = re.compile(r"przewidywani\w* awari|predykcj\w* awari|predict", re.IGNORECASE)


def test_json_in_repo_equals_generator_output():
    generator = load_generator()
    for name, text in generator.render().items():
        assert (generator.OUT / f"{name}.json").read_text(encoding="utf-8") == text, f"{name}.json różni się od generatora"


def test_five_dashboards_with_stable_uids_and_a_device_variable():
    dashes = dashboards()
    assert {d["uid"] for d in dashes.values()} == {"aip-przeglad", "aip-na-zywo", "aip-jakosc", "aip-energia", "aip-diagnostyka"}
    for dash in dashes.values():
        names = [v["name"] for v in dash["templating"]["list"]]
        assert names[0] == "device"
        assert dash["timezone"] == "Europe/Warsaw"
        assert dash["annotations"]["list"], "brak adnotacji okien testów i przerw"


def test_status_mappings_equal_the_documented_codes():
    generator = load_generator()
    assert set(generator.CODES["link"]) == {int(s) for s in LinkStatus}
    assert set(generator.CODES["meter"]) == {int(s) for s in MeterStatus}
    assert generator.CODES["errors"] == ERROR_CODE_NAMES
    states = {p["title"]: p for d in dashboards().values() for p in d["panels"] if p["type"] == "state-timeline"}
    link = states["Łącze z PLC (link_status)"]["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert {k: v["text"] for k, v in link.items() if k != "100"} == {str(k): v for k, v in generator.CODES["link"].items()}
    error = states["Kod błędu komunikacji PLC–licznik (meter_error_code)"]["fieldConfig"]["defaults"]["mappings"][0]["options"]
    for code, name in ERROR_CODE_NAMES.items():
        assert error[str(code)]["text"] == f"{code} {name}"


def test_no_failure_prediction_wording_and_every_panel_is_described():
    for name, dash in dashboards().items():
        assert not FORBIDDEN.search(dash["title"] + dash["description"]), name
        for panel in dash["panels"]:
            assert panel["description"].strip(), f"{name}: panel bez opisu: {panel['title']}"
            assert not FORBIDDEN.search(panel["title"] + panel["description"]), panel["title"]


def test_queries_use_only_allowed_sources_and_never_write():
    forbidden = re.compile(r"\b(insert|update|delete|drop|create|alter|truncate)\b", re.IGNORECASE)
    for name, dash in dashboards().items():
        for title, target in targets(dash):
            sql = target["rawSql"]
            assert not forbidden.search(sql), f"{name}/{title}: zapytanie zmieniające dane"
            assert target["datasource"]["uid"] == "aip-timescaledb"


def test_long_ranges_use_aggregates_not_raw_measurements():
    """Panele zakresów dłuższych niż doba nie czytają `measurements` bez ograniczenia zakresu (K6-U4, plan k7)."""
    for name, dash in dashboards().items():
        if name in ("jakosc", "energia"):
            for title, target in targets(dash):
                assert "FROM measurements" not in target["rawSql"], f"{name}/{title}"
