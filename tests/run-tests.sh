#!/bin/sh
# Uruchamia testy w izolowanym projekcie Compose `aip-test` (dane w tmpfs, losowe hasła testowe).
# Nie dotyka stosu produkcyjnego ani smartWARE; sprząta tylko projekt aip-test.
# Użycie: sh tests/run-tests.sh [argumenty pytest]   np.  sh tests/run-tests.sh -m "not slow"
set -eu
cd "$(dirname "$0")/.."

TEST_POSTGRES_PASSWORD="$(openssl rand -hex 16)"
TEST_MQTT_COLLECTOR_PASSWORD="$(openssl rand -hex 16)"
TEST_MQTT_INGEST_PASSWORD="$(openssl rand -hex 16)"
export TEST_POSTGRES_PASSWORD TEST_MQTT_COLLECTOR_PASSWORD TEST_MQTT_INGEST_PASSWORD

COMPOSE="docker compose -p aip-test -f docker-compose.test.yml"
cleanup() { $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

$COMPOSE build pytest
$COMPOSE run --rm -T pytest pytest -c /repo/pytest.ini "$@"
