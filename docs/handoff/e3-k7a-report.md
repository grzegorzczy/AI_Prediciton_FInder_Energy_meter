# E3-k7a – raport (krótki): diagnoza sieci IPC (E3-NET)

Data: 2026-11-28. Review planu: `5a4be24`. Zmiany: `3466e57` (adres .215 w dokumentach, monitor, sonda ARP), raport.
Bez `sudo`, bez `.env`, produkcja bez zmian (c299eaa). Odpowiedzi Grzegorza: kabel przełożony 27.11 ok. 20:49 do `enp2s0`
i tam zostaje; 100 Mb/s zaakceptowane; adresy zostają: IPC **192.168.0.215**, PLC **192.168.0.246**.

## Wynik: IPC nie stracił sieci 27.11 17:00–20:49

| Dowód | Wynik |
| --- | --- |
| Dane real w bazie 27.11 16:00–21:30 (co 10 min) | **11 880–12 000 wierszy na każde 10 min (20/s; braki do 1 % to znane błędy RS485 Findera)**, jedynie 20:40–20:50: 11 770 – PLC czytany bez przerwy, więc IPC miał LAN przez cały czas „przerwy” |
| Jądro i NetworkManager 12:00–20:49 | żadnego zdarzenia łącza na `enp1s0` ani `enp2s0` |
| Logowania ssh na IPC | z **192.168.0.203** do **17:46:00**, potem żadnego do 20:53; 20:53–21:17 z **192.168.0.214** (urządzenie w sieci zakładu), od 23:30 znów z .203 |
| Droga laptop → IPC (dziś) | laptop **nie jest w sieci zakładu**: hotspot telefonu + Tailscale; trasa 192.168.0.0/24 przez węzeł Tailscale **desktop-buej0av** (komputer w zakładzie, .203 w LAN) |
| Jedyna luka danych real 27.11 | **19:49:22.160 → 19:49:35.155 UTC (13 s)** = przełożenie kabla (PLC offline 19:49:25, powrót po DHCP na `enp2s0`) |

**Wniosek:** od ok. 17:46 przerwała się **droga dostępu** laptop → hotspot → Tailscale → desktop-buej0av → IPC, a nie sieć IPC.
Najbardziej prawdopodobnie desktop-buej0av (uśpienie, Tailscale) albo hotspot; z IPC nie da się tego rozstrzygnąć (log Tailscale
na laptopie wymaga uprawnień administratora). Przełożenie kabla o 20:49 zmieniło adres na .215 – stąd po powrocie drogi połączenia
z .213 dalej nie szły. Resety ssh 27/28.11 („Connection reset”) szły tą samą drogą; liczniki karty IPC: 0 błędów.

**Znaczenie dla wgrywania (część B):** wgrywanie i strażnik (K7-U1) działają na IPC w tle (`nohup`/cron), więc zerwanie mojej
drogi dostępu ich nie przerywa – tracę tylko podgląd. Ryzykiem dla danych jest sieć IPC, a ta była stabilna.

## K7-U3: aktualizacje automatyczne

- `unattended-upgrades` włączone (`jammy` + `jammy-security`), **bez automatycznego restartu komputera**; pakiety Dockera
  trzymane (`apt-mark hold`, 6 pakietów) – Dockera nie zaktualizuje.
- **26.11 06:43:19 aktualizacja `network-manager` zrestartowała NetworkManager** (stąd jego start 26.11 06:43). Połączenie
  zostało przejęte bez zerwania łącza (`assume`); dane real 06:42–06:45: 3 600 wierszy w 180 s – **bez luki**.
- Czyli: aktualizacje mogą restartować usługi sieciowe; dotąd bez skutku dla danych. Decyzja o wyłączeniu – Grzegorz w k8.

## K7-U4: okno w `data_windows`

Luka 19:49:22.160–19:49:35.155 UTC (`network_outage`, kabel) trafi do migracji razem z wdrożeniem (część B, wzór migracji 011);
nie wdrażam teraz osobno, bo migracja wymaga R-1.

## Monitor sieci (K7-D1, K7-D2)

`docs/ops/net-monitor.sh`, cron co minutę od **28.11 00:54** (koniec doby pomiaru: 29.11 ok. 01:00). Bez `sudo`, ping do bramy
i PLC (3 pakiety, bez Modbus), stan i prędkość łącza, adres, MAC bramy, zdarzenia łącza; log `~/aip-net/`, 14 dni, ok. 0,3 MB/dobę.
Pierwsza próbka: `speed=100`, adres .215, brama i PLC 0/3 utraconych (1,0 i 1,4 ms). Wynik doby podam przed częścią B.
Wykrycie innego urządzenia na adresie IPC bez `sudo` jest niemożliwe (brak `arping`, gniazda surowe tylko dla roota) – stąd
sonda ręczna niżej.

## Dokumenty z adresem

`.213` → `.215` w `docs/grafana.md`, `docs/ops/jumo-ipc-setup.md` (nowa sekcja „Sieć”: adresy, port, MAC, 100 Mb/s jako znana
cecha, droga dostępu, monitor), `docs/stages/etap-1.md`, `etap-2.md`; `CLAUDE.md` – adres IPC i PLC w „Sprzęt”.
**Bez zmian:** raporty i review w `docs/handoff/` (zapis historii) i `docs/modbus-map.md` (kontrakt z PLC; „.213” to fakt
z weryfikacji 23.11) – do decyzji architekta, czy dopisać tam uwagę.

## Polecenia `sudo` dla Grzegorza (na IPC, w katalogu `~/ai-predykcja-dev`)

1. Konflikt adresu (sonda ARP, nic nie zmienia; wynik „brak odpowiedzi” = OK):
   `sudo python3 docs/ops/arp-probe.py enp2s0 192.168.0.215`
2. Czas dzierżawy DHCP (czy adres .215 może się zmienić):
   `sudo grep -E "ADDRESS|LEASE|EXPIRES" /var/lib/NetworkManager/*.lease`

## Do decyzji

1. **Adres .215 jest z DHCP bez rezerwacji** – po wygaśnięciu dzierżawy albo restarcie routera może się zmienić (jak 27.11).
   Proponuję rezerwację .215 dla MAC `04:2b:58:12:f7:a2` w routerze (bez zmiany adresu) przed restartem IPC w części B.
2. **Droga dostępu w czasie wgrywania:** desktop-buej0av nie powinien się usypiać tej doby/nocy (albo laptop w sieci zakładu).
   Nie blokuje wgrywania, ale bez niej nie zobaczę postępu ani nie zatrzymam ręcznie.
3. Architekt: część B po dobie monitora bez przerw po stronie IPC.

Raport e3-k7a gotowy do przeglądu.
