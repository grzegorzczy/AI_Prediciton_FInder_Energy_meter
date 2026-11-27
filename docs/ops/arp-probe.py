"""Sprawdzenie, czy inne urządzenie używa adresu IPv4 komputera (E3-k7a, K7-D1). Wymaga sudo (gniazdo AF_PACKET).

Wysyła zapytania ARP o podany adres z pustym adresem nadawcy (sonda RFC 5227, nie zmienia tablic ARP innych urządzeń) i wypisuje
każdą odpowiedź. Odpowiedź z MAC innym niż własny = konflikt adresu. Tylko biblioteka standardowa, nic nie instaluje.

Użycie: sudo python3 docs/ops/arp-probe.py enp2s0 192.168.0.215
"""
from __future__ import annotations

import socket
import struct
import sys
import time


def mac_of(iface: str) -> bytes:
    with open(f"/sys/class/net/{iface}/address") as f:
        return bytes.fromhex(f.read().strip().replace(":", ""))


def main(iface: str, target: str, tries: int = 3, wait_s: float = 2.0) -> int:
    own = mac_of(iface)
    ip = socket.inet_aton(target)
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
    s.bind((iface, 0))
    s.settimeout(0.2)
    frame = (b"\xff" * 6 + own + b"\x08\x06"                              # Ethernet: broadcast, ARP
             + struct.pack("!HHBBH", 1, 0x0800, 6, 4, 1)                   # ARP request
             + own + b"\x00" * 4 + b"\x00" * 6 + ip)                       # nadawca 0.0.0.0 (sonda)
    seen: dict[str, int] = {}
    for _ in range(tries):
        s.send(frame)
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            try:
                data = s.recv(128)
            except socket.timeout:
                continue
            if len(data) < 42 or data[12:14] != b"\x08\x06" or struct.unpack("!H", data[20:22])[0] != 2:
                continue
            if data[28:32] == ip:
                mac = data[22:28].hex(":")
                seen[mac] = seen.get(mac, 0) + 1
    print(f"interfejs {iface}, własny MAC {own.hex(':')}, adres {target}")
    if not seen:
        print("brak odpowiedzi: żadne inne urządzenie nie używa tego adresu")
        return 0
    for mac, n in seen.items():
        print(f"ODPOWIEDŹ z {mac} ({n}×){' – własny MAC' if mac == own.hex(':') else ' – INNE URZĄDZENIE: konflikt adresu'}")
    return 1 if any(m != own.hex(":") for m in seen) else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
