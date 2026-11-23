"""Fixtury testów collectora: konfiguracja z prawdziwego config/devices.yaml, zegar wstrzykiwany."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
import yaml

from collector.config import Config, load_config_dict
from dbtools import REPO


@pytest.fixture(scope="session")
def raw_config() -> dict:
    with open(REPO / "config" / "devices.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def make_config(raw_config):
    """Zwraca funkcję budującą Config z prawdziwego pliku z nadpisaniami (modyfikacja kopii słownika)."""

    def _make(mutate=None) -> Config:
        raw = copy.deepcopy(raw_config)
        if mutate:
            mutate(raw)
        return load_config_dict(raw)

    return _make


@pytest.fixture
def config(make_config) -> Config:
    return make_config()


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
