#!/bin/sh
# Entrypoint Mosquitto: generuje plik haseł i ACL z zmiennych środowiskowych, potem uruchamia broker.
# Uruchamiany przez `sh` (nie polegamy na bitach wykonywania z Windowsa). Hasła nie są wypisywane.
set -eu

for v in MQTT_COLLECTOR_USER MQTT_COLLECTOR_PASSWORD MQTT_INGEST_USER MQTT_INGEST_PASSWORD; do
  eval "val=\${$v:-}"
  if [ -z "$val" ]; then
    echo "entrypoint: brak zmiennej $v" >&2
    exit 1
  fi
done

# Nazwy kont trafiają do pliku ACL przez sed, więc dopuszczamy tylko bezpieczne znaki.
for u in "$MQTT_COLLECTOR_USER" "$MQTT_INGEST_USER"; do
  case "$u" in
    *[!A-Za-z0-9_-]*) echo "entrypoint: niedozwolone znaki w nazwie konta MQTT" >&2; exit 1 ;;
  esac
done
if [ "$MQTT_COLLECTOR_USER" = "$MQTT_INGEST_USER" ]; then
  echo "entrypoint: konta collector i ingest muszą się różnić" >&2
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

sed -e "s/__COLLECTOR_USER__/$MQTT_COLLECTOR_USER/" \
    -e "s/__INGEST_USER__/$MQTT_INGEST_USER/" \
    /mosquitto/config/acl.conf > "$ACL"

chown mosquitto:mosquitto "$PASSWD" "$ACL"
chmod 0600 "$PASSWD" "$ACL"
chown -R mosquitto:mosquitto /mosquitto/data 2>/dev/null || true

# Hasła zostają tylko w pliku haseł; broker nie potrzebuje ich w środowisku.
unset MQTT_COLLECTOR_PASSWORD MQTT_INGEST_PASSWORD

exec mosquitto -c /mosquitto/config/mosquitto.conf
