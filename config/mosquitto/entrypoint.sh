#!/bin/sh
# Entrypoint Mosquitto: generuje plik haseł i ACL z zmiennych środowiskowych, potem uruchamia broker.
# Uruchamiany przez `sh` (nie polegamy na bitach wykonywania z Windowsa). Hasła nie są wypisywane.
# Konto symulatora (E3-k3, K3-D1) jest OPCJONALNE: bez MQTT_SIM_USER/MQTT_SIM_PASSWORD broker startuje bez niego
# (WARNING w logu), żeby dane prawdziwe płynęły także wtedy, gdy repo jest nowsze niż .env.
set -eu

for v in MQTT_COLLECTOR_USER MQTT_COLLECTOR_PASSWORD MQTT_INGEST_USER MQTT_INGEST_PASSWORD; do
  eval "val=\${$v:-}"
  if [ -z "$val" ]; then
    echo "entrypoint: brak zmiennej $v" >&2
    exit 1
  fi
done

SIM_USER="${MQTT_SIM_USER:-}"
SIM_PASSWORD="${MQTT_SIM_PASSWORD:-}"
if [ -n "$SIM_USER" ] && [ -z "$SIM_PASSWORD" ]; then
  echo "entrypoint: WARNING: MQTT_SIM_USER bez MQTT_SIM_PASSWORD – konto symulatora pominięte" >&2
  SIM_USER=""
fi
if [ -z "$SIM_USER" ]; then
  echo "entrypoint: WARNING: brak konta symulatora (MQTT_SIM_USER/MQTT_SIM_PASSWORD w .env) – broker bez konta symulatora" >&2
fi

# Nazwy kont trafiają do pliku ACL przez sed, więc dopuszczamy tylko bezpieczne znaki.
for u in "$MQTT_COLLECTOR_USER" "$MQTT_INGEST_USER" ${SIM_USER:+"$SIM_USER"}; do
  case "$u" in
    *[!A-Za-z0-9_-]*) echo "entrypoint: niedozwolone znaki w nazwie konta MQTT" >&2; exit 1 ;;
  esac
done
if [ "$MQTT_COLLECTOR_USER" = "$MQTT_INGEST_USER" ]; then
  echo "entrypoint: konta collector i ingest muszą się różnić" >&2
  exit 1
fi
if [ -n "$SIM_USER" ] && { [ "$SIM_USER" = "$MQTT_COLLECTOR_USER" ] || [ "$SIM_USER" = "$MQTT_INGEST_USER" ]; }; then
  echo "entrypoint: konto symulatora musi być inne niż collector i ingest" >&2
  exit 1
fi

umask 077
RUN_DIR=/run/mosquitto
PASSWD="$RUN_DIR/passwd"
ACL="$RUN_DIR/acl"
mkdir -p "$RUN_DIR"
rm -f "$PASSWD" "$ACL"

mosquitto_passwd -b -c "$PASSWD" "$MQTT_COLLECTOR_USER" "$MQTT_COLLECTOR_PASSWORD" >/dev/null
mosquitto_passwd -b "$PASSWD" "$MQTT_INGEST_USER" "$MQTT_INGEST_PASSWORD" >/dev/null
if [ -n "$SIM_USER" ]; then
  mosquitto_passwd -b "$PASSWD" "$SIM_USER" "$SIM_PASSWORD" >/dev/null
fi

# Bez konta symulatora jego blok ACL dostaje nazwę, której nie ma w pliku haseł (reguła bez skutku, K3-D1).
sed -e "s/__COLLECTOR_USER__/$MQTT_COLLECTOR_USER/" \
    -e "s/__INGEST_USER__/$MQTT_INGEST_USER/" \
    -e "s/__SIM_USER__/${SIM_USER:-__brak_konta_symulatora__}/" \
    /mosquitto/config/acl.conf > "$ACL"

chown mosquitto:mosquitto "$PASSWD" "$ACL"
chmod 0600 "$PASSWD" "$ACL"
chown -R mosquitto:mosquitto /mosquitto/data 2>/dev/null || true

# Hasła zostają tylko w pliku haseł; broker nie potrzebuje ich w środowisku.
unset MQTT_COLLECTOR_PASSWORD MQTT_INGEST_PASSWORD MQTT_SIM_PASSWORD SIM_PASSWORD

exec mosquitto -c /mosquitto/config/mosquitto.conf
