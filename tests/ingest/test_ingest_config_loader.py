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
    assert meter.meta == {"profile": "finder_7m24", "block_base": 10, "serial": "F0183363",
                          "poll_interval_s": 1.0, "energy_resolution_wh": 100.0, "reactive_resolution_varh": 100.0}
    assert plc.meta == {"map_versions": [1, 2]}


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


def test_meter_meta_has_no_sampling_values_when_config_lacks_them():
    """K6-d: brak poll_interval_s lub resolution_wh = brak klucza w meta (widoki dadzą NULL, nie domysł)."""
    import copy
    import yaml
    from ingest.config import load_config_dict

    raw = yaml.safe_load(open(REPO / "config" / "devices.yaml", encoding="utf-8"))
    raw = copy.deepcopy(raw)
    raw["plc"].pop("poll_interval_s")
    for item in raw["profiles"]["finder_7m24"]["energy"].values():
        item.pop("resolution_wh", None)
    meta = load_config_dict(raw).devices["finder_7m24_1"].meta
    assert "poll_interval_s" not in meta and "energy_resolution_wh" not in meta


def test_conflicting_resolutions_in_one_profile_are_rejected():
    import copy
    import yaml
    from ingest.config import ConfigError, load_config_dict

    raw = copy.deepcopy(yaml.safe_load(open(REPO / "config" / "devices.yaml", encoding="utf-8")))
    raw["profiles"]["finder_7m24"]["energy"]["energy_export_wh"]["resolution_wh"] = 10
    with pytest.raises(ConfigError, match="resolution_wh"):
        load_config_dict(raw)
