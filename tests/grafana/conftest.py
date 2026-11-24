"""Fixtury testów Grafany: baza `energy` (tę widzi źródło danych Grafany) z migracjami i danymi syntetycznymi."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from dbtools import MIGRATE, MIGRATIONS, admin_connect, build_panel_data

from grafana_support import wait_until_healthy


@pytest.fixture(scope="session")
def grafana_data(pg, role_passwords):
    """Migracje i dane w bazie `energy`; hasło app_reader zgodne z provisioningiem Grafany (TEST_APP_READER_PASSWORD)."""
    assert os.environ.get("TEST_APP_READER_PASSWORD"), "uruchamiaj przez tests/run-tests.sh"
    env = {**os.environ, "DB_HOST": pg["host"], "DB_PORT": str(pg["port"]), "POSTGRES_DB": "energy",
           "POSTGRES_USER": pg["user"], "POSTGRES_PASSWORD": pg["password"],
           "APP_WRITER_PASSWORD": role_passwords["app_writer"], "APP_READER_PASSWORD": role_passwords["app_reader"],
           "MIGRATIONS_DIR": str(MIGRATIONS), "DB_WAIT_S": "5"}
    result = subprocess.run([sys.executable, str(MIGRATE)], env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    with admin_connect(pg, "energy") as conn:
        info = build_panel_data(conn)
    wait_until_healthy()
    return info
