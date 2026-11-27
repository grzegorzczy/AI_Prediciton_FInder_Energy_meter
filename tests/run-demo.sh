#!/bin/sh
# Stos demonstracyjny do zrzutów Grafany (E3-k6, K6-D3): projekt Compose `aip-demo` (osobny od testów aip-test i od produkcji),
# baza na dysku, dane Findera syntetyczne, historia symulatora z narzędzia historii, potem ingest i symulator na żywo.
# Grafana tylko na 127.0.0.1:3300 komputera; z laptopa tunelem: ssh -L 3300:127.0.0.1:3300 jumo@<IPC>.
# Hasła losowe w ~/.aip-demo.env (0600); login Grafany: admin, hasło: TEST_GRAFANA_ADMIN_PASSWORD z tego pliku.
# Użycie: sh tests/run-demo.sh [up|status|down]   (AIP_DEMO_METER_HOURS=24: godziny historii liczników)
set -eu
cd "$(dirname "$0")/.."

SECRETS="$HOME/.aip-demo.env"
COMPOSE="docker compose -p aip-demo -f docker-compose.test.yml -f docker-compose.perf.yml -f docker-compose.demo.yml"
VARS="TEST_POSTGRES_PASSWORD TEST_MQTT_COLLECTOR_PASSWORD TEST_MQTT_INGEST_PASSWORD TEST_MQTT_SIM_PASSWORD TEST_APP_READER_PASSWORD TEST_GRAFANA_ADMIN_PASSWORD TEST_GRAFANA_SECRET_KEY"

load_secrets() {
    umask 077
    if [ ! -f "$SECRETS" ]; then
        for v in $VARS; do echo "$v=$(openssl rand -hex 16)"; done > "$SECRETS"
    fi
    set -a; . "$SECRETS"; set +a
}

case "${1:-up}" in
    up)
        load_secrets
        $COMPOSE build pytest
        $COMPOSE up -d db mosquitto grafana
        docker rm -f aip-demo-loader >/dev/null 2>&1 || true
        $COMPOSE run -d --name aip-demo-loader -e AIP_DEMO_METER_HOURS="${AIP_DEMO_METER_HOURS:-24}" pytest \
            python /repo/tests/grafana/demo.py >/dev/null
        echo "Stos aip-demo startuje. Postęp ładowania: docker logs -f aip-demo-loader (gotowe: „stos gotowy do zrzutów”)."
        echo "Grafana na komputerze: http://127.0.0.1:3300  login: admin  hasło: grep TEST_GRAFANA_ADMIN_PASSWORD $SECRETS"
        ;;
    status)
        docker ps --filter name=aip-demo --format "{{.Names}} {{.Status}}"
        docker logs --tail 5 aip-demo-loader 2>&1 || true
        ;;
    down)
        load_secrets
        docker rm -f aip-demo-loader >/dev/null 2>&1 || true
        $COMPOSE down -v --remove-orphans
        rm -f "$SECRETS"
        echo "Stos aip-demo usunięty (kontenery, sieć, wolumen bazy, plik haseł)."
        ;;
    *)
        echo "użycie: sh tests/run-demo.sh [up|status|down]" >&2
        exit 2
        ;;
esac
