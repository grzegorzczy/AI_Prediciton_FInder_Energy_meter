#!/bin/sh
# Pomiar wydajnosci na roku danych syntetycznych (K6-U4, k7): projekt Compose `aip-test` z baza poza tmpfs.
# Sprzata tylko projekt aip-test (wraz z wolumenem aip_perf_data). Uzycie: sh tests/run-perf.sh [argumenty pytest]
set -eu
cd "$(dirname "$0")/.."

TEST_POSTGRES_PASSWORD="$(openssl rand -hex 16)"
TEST_MQTT_COLLECTOR_PASSWORD="$(openssl rand -hex 16)"
TEST_MQTT_INGEST_PASSWORD="$(openssl rand -hex 16)"
export TEST_POSTGRES_PASSWORD TEST_MQTT_COLLECTOR_PASSWORD TEST_MQTT_INGEST_PASSWORD

COMPOSE="docker compose -p aip-test -f docker-compose.test.yml -f docker-compose.perf.yml"
cleanup() { $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true; }
# AIP_PERF_KEEP=1: baza z rokiem danych zostaje do ręcznych eksperymentów (sprzątanie: docker compose -p aip-test ... down -v)
[ -n "${AIP_PERF_KEEP:-}" ] || trap cleanup EXIT

$COMPOSE build pytest
$COMPOSE run --rm -T -e AIP_PERF_KEEP="${AIP_PERF_KEEP:-}" pytest pytest -c /repo/pytest.ini -s -m perf "$@"
