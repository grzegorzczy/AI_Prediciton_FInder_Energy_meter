"""Fixtury testów ingestu: konfiguracja z prawdziwego devices.yaml, zegar, atrapa bazy, klient MQTT, prawdziwy zapis."""
from __future__ import annotations

import copy

import pytest
import yaml

from dbtools import REPO
from ingest.config import IngestConfig, load_config_dict
from ingest_support import FakeClock, FakeStore, Publisher, make_store


@pytest.fixture(scope="session")
def raw_config() -> dict:
    with open(REPO / "config" / "devices.yaml", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture
def make_config(raw_config):
    def _make(mutate=None) -> IngestConfig:
        raw = copy.deepcopy(raw_config)
        if mutate:
            mutate(raw)
        return load_config_dict(raw)

    return _make


@pytest.fixture
def config(make_config) -> IngestConfig:
    return make_config()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def pub():
    publisher = Publisher()
    yield publisher
    publisher.close()


@pytest.fixture
def writer_store(pg, migrated_db, role_passwords):
    store = make_store(pg, migrated_db, role_passwords["app_writer"])
    yield store
    store.close()
