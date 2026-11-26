"""Fixtury testów symulatora (k2): config z prawdziwego devices.yaml z ustawionym t_zero (w pliku jest null do k7)."""
from __future__ import annotations

import copy

import pytest
import yaml

from dbtools import REPO
from simulator.config import load_config_dict
from simulator.samples import Simulator

@pytest.fixture(scope="session")
def raw_file() -> dict:
    with open(REPO / "config" / "devices.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def make_raw(raw_file):
    def _make(mutate=None, t_zero="2026-12-01T00:00:00Z") -> dict:
        raw = copy.deepcopy(raw_file)
        raw["simulator"]["t_zero"] = t_zero
        if mutate:
            mutate(raw)
        return raw

    return _make


@pytest.fixture(scope="session")
def sim_config(raw_file):
    raw = copy.deepcopy(raw_file)
    raw["simulator"]["t_zero"] = "2026-12-01T00:00:00Z"
    return load_config_dict(raw)


@pytest.fixture(scope="session")
def simulator(sim_config) -> Simulator:
    return Simulator(sim_config)
