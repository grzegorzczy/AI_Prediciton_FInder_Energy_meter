#!/bin/sh
# Test strażnika nocnego wgrywania (docs/ops/backfill-guard.sh, K7-U1) na projekcie Compose aip-test, na komputerze (bez sudo).
# Każdy próg wymuszony prawdziwym stanem (dane real w bazie testowej, pamięć kontenera, prognoza dysku, opóźnienie danych real)
# → strażnik zatrzymuje „wgrywanie” (kontener z Pythonem jako PID 1, jak narzędzie historii) i wznawia kompresję measurements.
# Kontrole: koniec wgrywania kodem 0 → kompresja zostaje wstrzymana; kodem 1 → wznowiona; krótka przerwa danych real (15 s)
# i zawieszona baza (12 s) → bez zatrzymania (przegląd k7b: kolejka tylko przy napływających danych, zapytania z limitem czasu).
# Sprząta tylko projekt aip-test i własne kontenery aip-test-guard-*. Użycie: sh tests/ops/guard-test.sh
set -eu
cd "$(dirname "$0")/../.."
REPO=$(pwd)

for v in TEST_POSTGRES_PASSWORD TEST_MQTT_COLLECTOR_PASSWORD TEST_MQTT_INGEST_PASSWORD TEST_MQTT_SIM_PASSWORD \
         TEST_APP_READER_PASSWORD TEST_GRAFANA_ADMIN_PASSWORD TEST_GRAFANA_SECRET_KEY; do
    eval "export $v=$(openssl rand -hex 16)"
done
COMPOSE="docker compose -p aip-test -f docker-compose.test.yml"
DB=aip-test-db-1
LOAD=aip-test-guard-load
INGEST=aip-test-guard-ingest
WORK=$(mktemp -d)
FAILS=0

cleanup() {
    touch "$WORK/stop-feeder"
    docker rm -f "$LOAD" "$INGEST" >/dev/null 2>&1 || true
    $COMPOSE down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

sql() { docker exec "$DB" psql -U postgres -d energy -tA -v ON_ERROR_STOP=1 -c "$1" </dev/null; }

$COMPOSE build -q pytest
$COMPOSE up -d --wait db >/dev/null
$COMPOSE run --rm -T --no-deps -e POSTGRES_DB=energy -e POSTGRES_USER=postgres -e MIGRATIONS_DIR=/repo/db/migrations \
    -e APP_WRITER_PASSWORD="$(openssl rand -hex 16)" -e APP_READER_PASSWORD="$TEST_APP_READER_PASSWORD" \
    pytest python /repo/db/migrate.py 2>&1 | tail -1
sql "INSERT INTO devices (device_id, name, site, line, kind, source, meta)
     VALUES ('plc-01', 'PLC', 'zaklad1', 'linia1', 'plc', 'real', '{}')" >/dev/null

# Dane real do bazy testowej: $1 wierszy/s, czas „teraz − $2 s” (opóźnienie), bieżąca i poprzednia sekunda (bez dziur).
feeder() {
    rm -f "$WORK/stop-feeder"
    (set +e; while [ ! -e "$WORK/stop-feeder" ]; do
        timeout 5 docker exec "$DB" psql -U postgres -d energy -q -c "INSERT INTO measurements (time, device_id, metric, value, unit, source)
            SELECT date_trunc('second', now()) - make_interval(secs => $2 + s) + make_interval(secs => i * (1.0 / $1)),
                   'plc-01', 'guard_test', 0, '', 'real'
            FROM generate_series(0, 1) s, generate_series(0, $1 - 1) i ON CONFLICT DO NOTHING" </dev/null >/dev/null 2>>"$WORK/feeder.err"
        sleep 1
    done) &
}
feeder_stop() { touch "$WORK/stop-feeder"; sleep 2; }

compression() { sql "SELECT alter_job(job_id, scheduled => $1) FROM timescaledb_information.jobs
                     WHERE proc_name = 'policy_compression' AND hypertable_name = 'measurements'" >/dev/null; }
compression_state() { sql "SELECT scheduled FROM timescaledb_information.jobs
                           WHERE proc_name = 'policy_compression' AND hypertable_name = 'measurements'"; }

# scenario NAZWA OCZEKIWANY_KOD WZORZEC_W_LOGU KOMPRESJA_PO MB_INGESTU POLECENIE_WGRYWANIA [zmienne strażnika...]
scenario() {
    name=$1 expect=$2 pattern=$3 comp_after=$4 mb=$5 load_cmd=$6; shift 6
    if [ -n "${GUARD_TEST_ONLY:-}" ] && [ "$name" != "$GUARD_TEST_ONLY" ]; then feeder_stop; PROGRESS="" ACTION=""; return; fi
    log="$WORK/$name-guard.log" load_log="$WORK/$name-load.log"
    compression false
    docker run -d --name "$INGEST" --memory 128m aip-pytest:local \
        python -c "import time; b = b'x' * ($mb * 1048576); time.sleep(3600)" >/dev/null
    sleep 3
    (set +e; docker run --rm --name "$LOAD" aip-pytest:local python -c "$load_cmd" > "$load_log" 2>&1; echo "EXIT=$?" >> "$load_log") &
    load_pid=$!
    [ -n "${PROGRESS:-}" ] && { sleep 2; echo "$PROGRESS" >> "$load_log"; }
    [ -n "${ACTION:-}" ] && { (eval "$ACTION") & }
    t0=$(date +%s)
    set +e
    env GUARD_LOAD_CONTAINER="$LOAD" GUARD_LOAD_LOG="$load_log" GUARD_DB_CONTAINER="$DB" GUARD_INGEST_CONTAINER="$INGEST" \
        GUARD_LOG="$log" GUARD_INTERVAL_S=5 GUARD_FROM=2026-11-13T23:00:00Z GUARD_TO=2026-11-27T12:42:00Z "$@" \
        timeout 600 sh "$REPO/docs/ops/backfill-guard.sh"
    code=$?
    set -e
    took=$(( $(date +%s) - t0 ))
    state=$(compression_state)
    gone=$(docker inspect "$LOAD" >/dev/null 2>&1 && echo "działa" || echo "zatrzymany")
    line=$(grep -E "$pattern" "$log" | head -1 | cut -c1-200)
    if [ "$code" = "$expect" ] && [ -n "$line" ] && [ "$state" = "$comp_after" ] && [ "$gone" = "zatrzymany" ]; then
        result=OK
    else
        result=BŁĄD; FAILS=$((FAILS + 1))
    fi
    echo "[$result] $name: kod $code (oczekiwany $expect), ${took} s, kompresja scheduled=$state (oczekiwane $comp_after), wgrywanie $gone, $(tail -1 "$load_log")"
    echo "        $line"
    docker rm -f "$INGEST" "$LOAD" >/dev/null 2>&1 || true
    wait "$load_pid" 2>/dev/null || true
    feeder_stop
    PROGRESS="" ACTION=""
}

SLEEP="import time; time.sleep(3600)"
free=$(df -P -B1 / | awk 'NR == 2 { print $4 }')

feeder 10 0
scenario real 3 "STOP: dane real" t 20 "$SLEEP"

feeder 20 0
scenario ingest 3 "STOP: pamięć anonimowa" t 110 "$SLEEP"

feeder 20 0
PROGRESS="2026-11-28 13:57:56,869 INFO simulator.backfill postęp: czas modelu 2026-11-17T12:42:00.000Z, 1324800 wiadomości, 1532/s, do końca ok. 300 min"
scenario dysk 3 "STOP: wolne miejsce" t 20 "$SLEEP" GUARD_BYTES_PER_DAY=$((free / 20))

feeder 20 20
scenario kolejka 3 "STOP: szacowana kolejka" t 20 "$SLEEP"

feeder 20 0
scenario koniec_0 0 "zakończone kodem 0" f 20 "import time; time.sleep(40)"

feeder 20 0
scenario koniec_1 4 "zakończone kodem 1" t 20 "import sys, time; time.sleep(20); sys.exit(1)"

feeder 20 0
ACTION="sleep 20; touch $WORK/stop-feeder; sleep 15; feeder 20 0"
scenario pauza_real_15s 0 "zakończone kodem 0" f 20 "import time; time.sleep(75)"

feeder 20 0
ACTION="sleep 20; docker pause $DB >/dev/null; sleep 12; docker unpause $DB >/dev/null"
scenario baza_wstrzymana_12s 0 "zakończone kodem 0" f 20 "import time; time.sleep(75)"

echo "błędów: $FAILS"
[ "$FAILS" -eq 0 ]
