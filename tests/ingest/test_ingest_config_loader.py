"""Parser configu ingestu: prawdziwy plik, zgodność z parserem collectora, błędy zatrzymujące start."""
from __future__ import annotations

import pytest

from ingest.config import ConfigError, load_config

from dbtools import REPO

# Metadane Findera sprzed E3-k1 (wiersz w `devices` na produkcji): po k1 różnią się wyłącznie kluczem `phases`.
FINDER_META_BEFORE_K1 = {"profile": "finder_7m24", "block_base": 10, "serial": "F0183363",
                         "poll_interval_s": 1.0, "energy_resolution_wh": 100.0, "reactive_resolution_varh": 100.0}
SIM_IDS = {"sim_pasteryzator", "sim_chlodnia", "sim_mieszalnik", "sim_pakowaczka", "sim_pump_p101"}


def test_real_config_loads_with_plc_and_meter():
    config = load_config(REPO / "config" / "devices.yaml")
    assert (config.site, config.line) == ("zaklad1", "linia1")
    assert set(config.devices) == {"plc-01", "finder_7m24_1"} | SIM_IDS
    plc, meter = config.devices["plc-01"], config.devices["finder_7m24_1"]
    assert (plc.kind, plc.source, plc.site, plc.line) == ("plc", "real", "zaklad1", "linia1")
    assert (meter.kind, meter.source, meter.site, meter.line) == ("energy_meter", "real", "zaklad1", "linia1")
    assert meter.meta == {**FINDER_META_BEFORE_K1, "phases": 1}
    assert plc.meta == {"map_versions": [1, 2]}


def test_finder_meta_differs_from_before_k1_only_by_phases():
    """Review k1, decyzja 4: w metadanych Findera dochodzi wyłącznie `phases: 1`, reszta identyczna."""
    meta = load_config(REPO / "config" / "devices.yaml").devices["finder_7m24_1"].meta
    assert set(meta) - set(FINDER_META_BEFORE_K1) == {"phases"} and meta["phases"] == 1
    assert {k: v for k, v in meta.items() if k != "phases"} == FINDER_META_BEFORE_K1


def test_simulator_devices_have_their_own_line_and_source_sim():
    config = load_config(REPO / "config" / "devices.yaml")
    sims = {k: v for k, v in config.devices.items() if k in SIM_IDS}
    assert all((d.site, d.line, d.source) == ("zaklad1", "linia2", "sim") for d in sims.values())
    assert config.site_lines() == [("zaklad1", "linia1"), ("zaklad1", "linia2")]
    meters = {k for k, d in sims.items() if d.kind == "energy_meter"}
    assert meters == SIM_IDS - {"sim_pump_p101"} and sims["sim_pump_p101"].kind == "pump"
    assert sims["sim_pasteryzator"].meta == {"poll_interval_s": 1.0, "energy_resolution_wh": 100.0, "phases": 3, "rated_kw": 18.0}
    assert {d.meta["rated_kw"] for d in sims.values()} == {18.0, 11.0, 7.5, 4.0}
    assert all(d.meta["phases"] == 3 and d.meta["energy_resolution_wh"] == 100.0 for k, d in sims.items() if k in meters)
    assert sims["sim_pump_p101"].meta == {"poll_interval_s": 1.0, "rated_kw": 11.0}       # pompa bez energii (K0-D9)
    assert [d.name for d in sims.values()] == ["Pasteryzator", "Agregat chłodniczy", "Mieszalnik", "Pakowaczka", "Pompa P-101"]


def test_config_without_simulator_section_gives_the_pre_stage3_devices(make_config):
    config = make_config(lambda raw: raw.pop("simulator"))
    assert set(config.devices) == {"plc-01", "finder_7m24_1"}
    assert config.site_lines() == [("zaklad1", "linia1")]


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda r: r["simulator"]["devices"][0].update(source="real"), "musi mieć source: sim"),
        (lambda r: r["simulator"]["devices"][0].update(kind="plc"), "niedozwolony dla symulatora"),
        (lambda r: r["simulator"]["devices"][0].update(id="finder_7m24_1"), "powtórzone id"),
        (lambda r: r["simulator"]["devices"][0].update(id="sim pasteryzator"), "niedozwolone znaki"),
        (lambda r: r["simulator"].update(line="linia 2"), "ASCII"),
        (lambda r: r["simulator"].pop("line"), "line"),
        (lambda r: r["simulator"]["devices"][0].update(phases=2), "phases"),
        (lambda r: r["devices"][0].update(phases=2), "phases"),
        (lambda r: r.update(simulator=["x"]), "słownika"),
        # przegląd k1: linia sim = linia sprzętu, złe typy i zakresy, liczba faz jako bool/float, wymagane pola liczników
        (lambda r: r["simulator"].update(line="linia1"), "muszą być inne"),
        (lambda r: r["simulator"]["devices"][0].update(rated_kw="abc"), "nie jest liczbą"),
        (lambda r: r["simulator"]["devices"][0].update(rated_kw=-5), "dodatnia"),
        (lambda r: r["simulator"]["devices"][0].update(rated_kw=float("nan")), "dodatnia"),
        (lambda r: r["simulator"]["devices"][0].update(rated_kw=True), "nie jest liczbą"),
        (lambda r: r["simulator"].update(poll_interval_s=0), "dodatnia"),
        (lambda r: r["simulator"].update(poll_interval_s="x"), "nie jest liczbą"),
        (lambda r: r["simulator"]["devices"][0].update(phases=True), "phases"),
        (lambda r: r["simulator"]["devices"][0].update(phases=3.0), "phases"),
        (lambda r: r["simulator"]["devices"][0].pop("phases"), "phases"),
        (lambda r: r["simulator"]["devices"][0].pop("energy_resolution_wh"), "energy_resolution_wh"),
        (lambda r: r["simulator"]["devices"][0].update(energy_resolution_wh=0), "dodatnia"),
        (lambda r: r["simulator"]["devices"][4].update(phases=3), "nie dotyczy pompy"),
    ],
)
def test_invalid_simulator_configuration_is_rejected(make_config, mutate, fragment):
    with pytest.raises(ConfigError) as error:
        make_config(mutate)
    assert fragment in str(error.value)


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
    real_line = {k: v.source for k, v in ingest.devices.items() if (v.site, v.line) == (ingest.site, ingest.line)}
    assert real_line == expected                         # urządzenia sim (linia2) zna tylko ingest, collector ich nie czyta


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
