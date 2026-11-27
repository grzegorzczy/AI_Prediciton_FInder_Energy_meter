#!/bin/sh
# Monitor sieci IPC (E3-k7a, K7-D1): jedna próbka na wywołanie, z crona co minutę. Bez sudo, bez połączeń do Modbus PLC (K7-D2):
# tylko ping do bramy i PLC, stan łącza z /sys, adres IPv4, MAC bramy (zmiana = podejrzenie konfliktu/innego routera),
# zdarzenia „Link is Down/Up” z dziennika jądra z ostatniej minuty.
# Log: ~/aip-net/net-YYYYMMDD.log, jedna linia na minutę (ok. 200 B → ok. 0,3 MB/dobę); pliki starsze niż 14 dni usuwane.
# Instalacja (raz): mkdir -p ~/aip-net && cp docs/ops/net-monitor.sh ~/aip-net/ && chmod 755 ~/aip-net/net-monitor.sh
#   && (crontab -l; echo '* * * * * /home/jumo/aip-net/net-monitor.sh >/dev/null 2>&1') | crontab -
# Adresy: argumenty albo zmienne NET_IFACE / NET_GW / NET_PLC (domyślnie wg docs/ops/jumo-ipc-setup.md).
set -u
IFACE="${NET_IFACE:-enp2s0}"
GW="${NET_GW:-192.168.0.1}"
PLC="${NET_PLC:-192.168.0.246}"
DIR="${NET_DIR:-$HOME/aip-net}"
mkdir -p "$DIR"

probe() {   # 3 pingi co 0,5 s, timeout 1 s: "utracone/3 rtt_ms" albo "3/3 -"
    out=$(ping -n -q -c 3 -i 0.5 -W 1 "$1" 2>/dev/null)
    recv=$(printf '%s\n' "$out" | sed -n 's/.* \([0-9]*\) received.*/\1/p')
    rtt=$(printf '%s\n' "$out" | sed -n 's#.*= [0-9.]*/\([0-9.]*\)/.*#\1#p')
    echo "$((3 - ${recv:-0}))/3 ${rtt:--}"
}

ts=$(date '+%Y-%m-%dT%H:%M:%S%z')
carrier=$(cat "/sys/class/net/$IFACE/carrier" 2>/dev/null || echo "?")
speed=$(cat "/sys/class/net/$IFACE/speed" 2>/dev/null || echo "?")
addr=$(ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{print $4}' | head -1)
gw_route=$(ip -4 route show default 2>/dev/null | awk '{print $3 "@" $5}' | head -1)
gw_p=$(probe "$GW")
plc_p=$(probe "$PLC")
gw_mac=$(ip neigh show "$GW" dev "$IFACE" 2>/dev/null | awk '{print $3}')
links=$(journalctl -k --since "-65s" --no-pager -q 2>/dev/null | grep -c "Link is ")

echo "$ts if=$IFACE carrier=$carrier speed=$speed addr=${addr:--} route=${gw_route:--} gw=$gw_p gw_mac=${gw_mac:--} plc=$plc_p link_events=$links" \
    >> "$DIR/net-$(date +%Y%m%d).log"
find "$DIR" -name 'net-*.log' -mtime +14 -delete 2>/dev/null
