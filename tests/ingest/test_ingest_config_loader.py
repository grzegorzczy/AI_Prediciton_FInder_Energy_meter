"""Parser configu ingestu: prawdziwy plik, zgodność z parserem collectora, błędy zatrzymujące start."""
from __future__ import annotations

import pytest

from ingest.config import ConfigError, load_config

from dbtools import REPO


def test_real_config_loads_with_plc_and_meter():
    config = load_config(REPO / "config" / "devices.yaml")
    assert (config.site, config.line) == ("zaklad1", "linia1")
    assert set(config.devices) == {"plc-01", "finder_7m24_1"}
    plc, meter = config.devices["plc-01"], config.devices["finder_7m24_1"]
    assert (plc.kind, plc.source) == ("plc", "real")
    assert (meter.kind, meter.source) == ("energy_meter", "real")
    assert meter.meta == {"profile": "finder_7m24", "block_base": 10, "serial": "F0183363"}
    assert plc.meta == {"map_version": 1}


def test_ip_address_never_enters_device_metadata():
    config = load_config(REPO / "config" / "devices.yaml")
    assert "192.168" not in repr(config)


def test_both_services_agree_on_the_same_file():
    """Collector i ingest czytają jeden plik: te same identyfikatory, site, line i źródła."""
    from collector.config import load_config as load_collector

    path = REPO / "config" / "devices.yaml"
    ingest, collector = load_config(path), load_collector(path)
    assert (ingest.site, ingest.line) == (collector.site, collector.line)
    expected = {collector.plc.device_id: collector.plc.source,
                **{m.device_id: m.source for m in collector.meters}}
    assert {k: v.source for k, v in ingest.devices.items()} == expected


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r.update(site="strefa 1"), "ASCII"),
        (lambda r: r["devices"][0].update(id="plc-01"), "powtórzone id"),
        (lambda r: r["devices"][0].update(kind="inny"), "rodzaj"),
        (lambda r: r["devices"][0].update(source="x"), "real lub sim"),
        (lambda r: r["devices"][0].pop("serial"), "serial"),
        (lambda r: r["plc"].update(source="x"), "real lub sim"),
        (lambda r: r.pop("plc"), "plc"),
    ],
)
def test_invalid_configuration_is_rejected(make_config, mutate, fragment):
    with pytest.raises(ConfigError) as error:
        make_config(mutate)
    assert fragment in str(error.value)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nie-ma.yaml")
