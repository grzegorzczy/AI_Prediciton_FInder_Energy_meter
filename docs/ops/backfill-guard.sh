#!/bin/sh
# Strażnik nocnego wgrywania historii symulatora (E3-k7, K7-U1). Działa na komputerze (bez sudo, w tle, nohup),
# obok wgrywania uruchomionego jako kontener o stałej nazwie, np.:
#   docker compose run --rm -T --name aip-backfill-night simulator-tools python -m simulator.backfill ... > LOG 2>&1; echo EXIT=$? >> LOG
# Co GUARD_INTERVAL_S sekund mierzy i zatrzymuje wgrywanie (docker stop), gdy:
#   1. dane real < GUARD_REAL_MIN wierszy/s dłużej niż GUARD_REAL_HOLD_S s (okno 20 s, 5 s za „teraz”);
#   2. pamięć anonimowa aip-ingest > GUARD_INGEST_PCT % limitu kontenera (K7B-D2: anon, nie cache);
#   3. wolne miejsce < GUARD_DISK_FACTOR × pozostała prognoza (doby do --to × GUARD_BYTES_PER_DAY + GUARD_EXTRA_BYTES);
#   4. szacowana kolejka brokera dla ingestu > GUARD_QUEUE_MAX wiadomości w GUARD_QUEUE_CHECKS pomiarach z rzędu Broker nie podaje kolejki klienta ($SYS wyłączone,
#      sys_interval 0), więc szacunek z prawa Little'a: opóźnienie danych real w bazie × (tempo narzędzia + dane na żywo).
#      Dane real stoją w tej samej kolejce FIFO co historia, więc ich opóźnienie to czas przejścia kolejki.
# Po zatrzymaniu albo po zakończeniu wgrywania kodem ≠ 0: wznowienie kompresji measurements (K7-U2) i wpis z przyczyną.
# Po kodzie 0 kompresja zostaje wstrzymana (rano: pompa, odświeżenie agregatów, --fill-gaps, potem wznowienie).
# Kody wyjścia: 0 wgrywanie skończone kodem 0; 3 zatrzymane przez strażnika; 4 wgrywanie skończone błędem;
#               5 kontener wgrywania się nie pojawił; 2 błąd parametrów.
# Tylko odczyty z bazy (konto administratora w kontenerze bazy, bez haseł) poza alter_job kompresji.
set -u
export LC_ALL=C                                      # kropka dziesiętna w awk i w logu

LOAD=${GUARD_LOAD_CONTAINER:-aip-backfill-night}
LOAD_LOG=${GUARD_LOAD_LOG:-}
FROM=${GUARD_FROM:-}
TO=${GUARD_TO:-}
DB=${GUARD_DB_CONTAINER:-aip-timescaledb}
INGEST=${GUARD_INGEST_CONTAINER:-aip-ingest}
LOG=${GUARD_LOG:-$HOME/aip-k7/guard.log}
INTERVAL=${GUARD_INTERVAL_S:-10}
REAL_MIN=${GUARD_REAL_MIN:-18}
REAL_HOLD=${GUARD_REAL_HOLD_S:-60}
INGEST_PCT=${GUARD_INGEST_PCT:-80}
DISK_FACTOR=${GUARD_DISK_FACTOR:-3}
BYTES_PER_DAY=${GUARD_BYTES_PER_DAY:-419430400}     # 400 MiB na dobę liczników (pilotaż k7b)
EXTRA_BYTES=${GUARD_EXTRA_BYTES:-107374182}         # pompa ok. 0,1 GiB
DISK_PATH=${GUARD_DISK_PATH:-/}
QUEUE_MAX=${GUARD_QUEUE_MAX:-20000}
LIVE_RATE=${GUARD_LIVE_RATE:-49}                    # 20 real + 29 sim na żywo
TOOL_RATE=${GUARD_TOOL_RATE:-1536}                  # do pierwszej linii „postęp” narzędzia (pilotaż k7b)
APPEAR_S=${GUARD_APPEAR_S:-300}
QUEUE_CHECKS=${GUARD_QUEUE_CHECKS:-3}               # kolejne pomiary powyżej progu kolejki (przegląd k7b)
STOP_TIMEOUT=${GUARD_STOP_TIMEOUT_S:-10}

log() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

if [ -z "$LOAD_LOG" ] || [ -z "$FROM" ] || [ -z "$TO" ]; then
    echo "ustaw GUARD_LOAD_LOG, GUARD_FROM i GUARD_TO (jak --from/--to wgrywania)" >&2
    exit 2
fi
FROM_S=$(date -u -d "$FROM" +%s) && TO_S=$(date -u -d "$TO" +%s) || { echo "zły GUARD_FROM/GUARD_TO" >&2; exit 2; }
mkdir -p "$(dirname "$LOG")"

trap 'log "strażnik zakończony (kod $?)"' EXIT

# Zapytania z limitem: statement_timeout w bazie i timeout procesu (zawieszona baza nie zatrzymuje strażnika).
sql() { timeout 15 docker exec -e PGOPTIONS='-c statement_timeout=5000' "$DB" psql -U postgres -d energy -tA -v ON_ERROR_STOP=1 \
        -c "$1" </dev/null 2>/dev/null; }

# Linie EXIT= sprzed startu strażnika (poprzedni przebieg w tym samym logu) są pomijane.
exit_lines() { grep -c '^EXIT=' "$LOAD_LOG" 2>/dev/null || true; }
EXIT_BASE=$(exit_lines); EXIT_BASE=${EXIT_BASE:-0}
load_exit() { sed -n 's/^EXIT=\([0-9]*\)$/\1/p' "$LOAD_LOG" 2>/dev/null | tail -n +"$((EXIT_BASE + 1))" | tail -1; }

compression_on() {
    for _ in 1 2 3 4 5; do
        sql "SELECT alter_job(job_id, scheduled => true) FROM timescaledb_information.jobs
             WHERE proc_name = 'policy_compression' AND hypertable_name = 'measurements'" >/dev/null
        state=$(sql "SELECT scheduled FROM timescaledb_information.jobs
                     WHERE proc_name = 'policy_compression' AND hypertable_name = 'measurements'")
        if [ "$state" = "t" ]; then log "kompresja measurements: wznowiona (scheduled = t)"; return 0; fi
        sleep 10
    done
    log "BŁĄD: nie udało się wznowić kompresji measurements – wznowić ręcznie (docs/ops/jumo-ipc-setup.md)"
    return 1
}

finish_after_exit() {
    code=$1
    if [ "$code" = "0" ]; then
        log "wgrywanie zakończone kodem 0; kompresja zostaje wstrzymana (rano: pompa, odświeżenie, --fill-gaps, wznowienie)"
        exit 0
    fi
    log "wgrywanie zakończone kodem $code (przerwane) – wznawiam kompresję (K7-U2)"
    compression_on
    exit 4
}

log "start strażnika: wgrywanie=$LOAD log=$LOAD_LOG zakres=$FROM..$TO progi: real<$REAL_MIN/s >${REAL_HOLD}s, ingest>${INGEST_PCT}%, dysk<${DISK_FACTOR}x prognozy, kolejka>$QUEUE_MAX"

waited=0
until docker inspect "$LOAD" >/dev/null 2>&1; do
    code=$(load_exit)
    [ -n "$code" ] && finish_after_exit "$code"
    if [ "$waited" -ge "$APPEAR_S" ]; then
        log "kontener $LOAD nie pojawił się w ciągu $APPEAR_S s – koniec strażnika"
        exit 5
    fi
    sleep 5; waited=$((waited + 5))
done
log "kontener $LOAD działa"

low_since=""
queue_over=0
while :; do
    if ! docker inspect "$LOAD" >/dev/null 2>&1; then
        code=""
        for _ in $(seq 1 24); do code=$(load_exit); [ -n "$code" ] && break; sleep 5; done
        if [ -z "$code" ] && docker inspect "$LOAD" >/dev/null 2>&1; then
            log "uwaga: chwilowy błąd docker inspect – kontener $LOAD nadal działa, pilnuję dalej"
            continue
        fi
        finish_after_exit "${code:-brak}"
    fi
    now=$(date +%s)

    rows=$(sql "SELECT count(*) FROM measurements WHERE source = 'real'
                AND time > now() - interval '25 s' AND time <= now() - interval '5 s'")
    real=$(awk -v r="${rows:-0}" 'BEGIN { printf "%.1f", r / 20 }')
    lag=$(sql "SELECT round(extract(epoch FROM now() - max(time))::numeric, 1)
               FROM measurements WHERE source = 'real' AND time > now() - interval '5 min'")

    progress=$(sed -n 's/.*postęp: czas modelu \([^,]*\), [0-9]* wiadomości, \([0-9]*\)\/s.*/\1 \2/p' "$LOAD_LOG" 2>/dev/null | tail -1)
    if [ -n "$progress" ]; then
        model_s=$(date -u -d "${progress% *}" +%s 2>/dev/null || echo "$FROM_S")
        rate=${progress#* }
    else
        model_s=$FROM_S; rate=$TOOL_RATE
    fi
    # Kolejka liczona tylko, gdy dane real napływają (wiersze w oknie) i opóźnienie jest znane: przerwa w danych real
    # (PLC, collector) albo błąd zapytania to sprawa progu danych real z 60 s, nie kolejki (przegląd k7b).
    if [ -n "$lag" ] && [ "${rows:-0}" -gt 0 ]; then
        queue=$(awk -v l="$lag" -v r="$rate" -v live="$LIVE_RATE" 'BEGIN { printf "%d", l * (r + live) }')
    else
        queue=-1
    fi

    id=$(docker inspect -f '{{.Id}}' "$INGEST" 2>/dev/null)
    cg=/sys/fs/cgroup/system.slice/docker-$id.scope
    if [ -n "$id" ] && [ -r "$cg/memory.stat" ]; then
        ingest=$(awk -v max="$(cat "$cg/memory.max" 2>/dev/null)" \
                 '$1 == "anon" { if (max == "max") print 0; else if (max + 0 > 0) printf "%.0f", 100 * $2 / max }' "$cg/memory.stat")
    fi
    ingest=${ingest:--1}

    free=$(df -P -B1 "$DISK_PATH" 2>/dev/null | awk 'NR == 2 { print $4 }')
    need=$(awk -v to="$TO_S" -v m="$model_s" -v b="$BYTES_PER_DAY" -v e="$EXTRA_BYTES" -v f="$DISK_FACTOR" \
           'BEGIN { d = (to - m) / 86400; if (d < 0) d = 0; printf "%.0f", f * (d * b + e) }')

    log "real=$real/s opóźnienie=${lag:-?}s kolejka~$queue ingest=${ingest}% wolne=$(( ${free:-0} / 1073741824 ))G potrzeba=$((need / 1073741824))G model=$(date -u -d "@$model_s" +%FT%TZ) tempo=$rate/s"

    reason=""
    if awk -v r="$real" -v m="$REAL_MIN" 'BEGIN { exit !(r < m) }'; then
        [ -z "$low_since" ] && low_since=$now
        if [ $((now - low_since)) -gt "$REAL_HOLD" ]; then
            reason="dane real $real/s < $REAL_MIN/s od $((now - low_since)) s"
        fi
    else
        low_since=""
    fi
    if [ -z "$reason" ] && [ "$ingest" -gt "$INGEST_PCT" ]; then
        reason="pamięć anonimowa $INGEST ${ingest}% > ${INGEST_PCT}% limitu"
    fi
    if [ -z "$free" ]; then
        log "uwaga: df nie podał wolnego miejsca – próg dysku pominięty w tym pomiarze"
    elif [ -z "$reason" ] && [ "$free" -lt "$need" ]; then
        reason="wolne miejsce $((free / 1048576)) MiB < ${DISK_FACTOR}× prognozy ($((need / 1048576)) MiB)"
    fi
    if [ "$queue" -gt "$QUEUE_MAX" ]; then queue_over=$((queue_over + 1)); else queue_over=0; fi
    if [ -z "$reason" ] && [ "$queue_over" -ge "$QUEUE_CHECKS" ]; then
        reason="szacowana kolejka brokera $queue > $QUEUE_MAX w $queue_over pomiarach z rzędu (opóźnienie real ${lag} s × $((rate + LIVE_RATE))/s)"
    fi
    if [ -z "$reason" ] && [ "$ingest" -lt 0 ]; then
        log "uwaga: brak kontenera $INGEST albo jego cgroup – próg pamięci nieaktywny"
    fi

    if [ -n "$reason" ]; then
        log "STOP: $reason – zatrzymuję $LOAD"
        docker stop -t "$STOP_TIMEOUT" "$LOAD" >/dev/null 2>&1   # narzędzie (PID 1 bez obsługi SIGTERM): SIGKILL po czasie
        compression_on
        for _ in $(seq 1 24); do code=$(load_exit); [ -n "$code" ] && break; sleep 5; done
        log "wgrywanie zatrzymane (kod ${code:-brak}); wznowienie tym samym poleceniem po usunięciu przyczyny"
        exit 3
    fi
    sleep "$INTERVAL"
done
