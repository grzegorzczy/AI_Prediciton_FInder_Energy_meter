# E3-k7a – review raportu (architekt)

Data: 2026-11-28. Raport: `e3-k7a-report.md` (`7165cc4`). Review krótkie.

**Werdykt: OK. E3-NET wyjaśnione** – IPC nie stracił sieci 27.11: dane real 20 wierszy/s bez przerwy, jedyna luka 13 s (19:49:22–19:49:35 UTC) przy przełożeniu kabla do `enp2s0`. Przerwała się droga dostępu laptopa (hotspot → Tailscale → `desktop-buej0av` .203), nie IPC. Aktualizacja 26.11 06:43 zrestartowała NetworkManager bez zerwania łącza i bez luki; automatyczny restart komputera wyłączony, Docker trzymany.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K7A-D1 | Stare `.213` w handoff i `docs/modbus-map.md` | **Zostają** (zapis historyczny / fakt z weryfikacji 23.11). Aktualny adres – `docs/ops` „Sieć” i `CLAUDE.md`. |
| K7A-D2 | Czekanie na 24 h monitora przed częścią B | **Nie czekamy** – przyczyna znana (droga dostępu). Monitor działa dalej; wynik dobowy w raporcie B. Część B po „ok” Grzegorza i po dwóch poleceniach `sudo` (ARP, dzierżawa). |
| K7A-D3 | Rezerwacja DHCP .215 i uśpienie `desktop-buej0av` | **Decyzje Grzegorza.** Rekomendacja: rezerwacja .215 dla `04:2b:58:12:f7:a2` przed restartem IPC; `desktop-buej0av` bez usypiania na noc wgrywania (albo laptop w sieci zakładu). Bez tego wgrywanie i tak trwa na IPC (strażnik K7-U1 zatrzyma je przy problemach), tracimy tylko podgląd. |

## Uwagi

- Luka 13 s z 27.11 jako okno `network_outage`/`cable_move` w migracji wdrożenia (R-1) – zgodnie z raportem.
- Wynik `arp-probe.py` i czas dzierżawy DHCP – do raportu B; jeśli ARP pokaże inne urządzenie na .215 – stop przed restartem.
