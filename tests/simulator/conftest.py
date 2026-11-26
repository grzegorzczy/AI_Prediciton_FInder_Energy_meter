"""Fixtury testów symulatora: config z prawdziwego devices.yaml z ustawionymi datami (w pliku są null do k7) i wspólna
pamięć sum dobowych na sesję testów (K2R-U5: nowe instancje nie liczą dób od zera)."""
from __future__ import annotations

import copy

import pytest
import yaml

from dbtools import REPO
from sim_support import set_dates
from simulator.config import load_config_dict
from simulator.daycache import cache_key
from simulator.samples import Simulator


@pytest.fixture(scope="session")
def raw_file() -> dict:
    with open(REPO / "config" / "devices.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def make_raw(raw_file):
    def _make(mutate=None, **dates) -> dict:
        raw = set_dates(copy.deepcopy(raw_file), **dates)
        if mutate:
            mutate(raw)
        return raw

    return _make


@pytest.fixture(scope="session")
def sim_config(raw_file):
    return load_config_dict(set_dates(copy.deepcopy(raw_file)))


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("sim-cache")


_CREATED: list[Simulator] = []


@pytest.fixture(scope="session")
def make_sim(sim_config, cache_dir):
    """Simulator z pamięcią sum w katalogu sesji (osobny plik na klucz configu); zapis pamięci po każdym teście."""
    def _make(config=None) -> Simulator:
        config = config or sim_config
        sim = Simulator(config, str(cache_dir / f"{cache_key(config)}.json"))
        _CREATED.append(sim)
        return sim

    return _make


@pytest.fixture(autouse=True)
def _flush_day_caches():
    yield
    for sim in _CREATED:
        sim.cache.flush()


@pytest.fixture(scope="session")
def simulator(make_sim) -> Simulator:
    return make_sim()
