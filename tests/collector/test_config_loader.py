"""Parser konfiguracji collectora: prawdziwy config/devices.yaml i błędy, które mają zatrzymać start (K3-i)."""
from __future__ import annotations

import pytest

from collector.config import ConfigError, load_config

from dbtools import REPO


def test_real_config_loads():
    config = load_config(REPO / "config" / "devices.yaml")
    assert (config.site, config.line) == ("zaklad1", "linia1")
    assert config.plc.device_id == "plc-01" and config.plc.read_count == 44 and config.plc.map_version == 1
    assert config.plc.timeout_s == 2.0 and config.plc.reconnect_max_s == 10 and config.plc.link_metric == "link_status"
    [meter] = config.meters
    assert meter.device_id == "finder_7m24_1" and meter.serial == "F0183363" and meter.block_base == 10
    assert meter.profile.status.metric == "meter_status"
    assert meter.profile.data_age.omit_value == 0xFFFFFFFF


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r["plc"].update(function=3), "FC04"),
        (lambda r: r["plc"].pop("timeout_s"), "timeout_s"),
        (lambda r: r.update(site="strefa 1"), "segment tematu"),
        (lambda r: r.update(line="łączka"), "segment tematu"),
        (lambda r: r["devices"][0].update(profile="nieznany"), "nieznany profil"),
        (lambda r: r["devices"][0].update(source="inne"), "real lub sim"),
        (lambda r: r["devices"][0].update(id="plc-01"), "powtórzone id"),
        (lambda r: r["devices"][0].update(block_base=40), "poza zapytaniem"),
        (lambda r: r["plc"]["read"].update(count=30), "poza zapytaniem"),
        (lambda r: r["devices"][0].update(block_base=0), "nakładanie"),
        (lambda r: r["profiles"]["finder_7m24"]["metrics"]["voltage"].update(type="float99"), "nieznany typ"),
        (lambda r: r["profiles"]["finder_7m24"]["status"].pop("metric"), "metric"),
        (lambda r: r["profiles"]["finder_7m24"]["metrics"].update({"Zła Nazwa": {"offset": 30, "type": "uint16"}}),
         "niedozwolona nazwa metryki"),
    ],
)
def test_invalid_configuration_is_rejected(make_config, mutate, fragment):
    with pytest.raises(ConfigError) as error:
        make_config(mutate)
    assert fragment in str(error.value)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nie-ma.yaml")
