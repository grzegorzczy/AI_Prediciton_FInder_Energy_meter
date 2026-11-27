# E3-k7 – review planu (architekt)

Data: 2026-11-28. Plan: `e3-k7-plan.md` (`57f2216`). Review krótkie.

**Werdykt: OK Z UWAGAMI.** Część A (E3-NET) – wykonuj po „ok” Grzegorza; część B dopiero po wyniku A i odpowiedzi Grzegorza o kablu. Dobra diagnoza wstępna: brak link-down 12:00–20:49, przełożenie `enp1s0` → `enp2s0` o 20:49:22, `enp2s0` na 100 Mb/s.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K7-D1 | Monitor sieci na stałe w ops | **Tak**, lekki: ping do routera i PLC co 30–60 s, wykrycie innego urządzenia na adresie IPC; log z limitem rozmiaru (rotacja), bez `sudo`, osobno od `~/aip-monitor` (ten znika po etapie 3). Docelowo (etap 7) jako metryka w bazie. |
| K7-D2 | Połączenie TCP do portu 502 PLC w monitorze | **Nie.** Dostępność PLC przez Modbus mierzy już collector (`link_status`); dodatkowe połączenia do serwera Modbus PLC to zbędne obciążenie jego puli połączeń. Monitor – tylko ping do PLC. |
| K7-D3 | Terminy | **Pilotaż 1 doby w dzień** (ok. 30 min, Grzegorz dostępny, łatwo przerwać), **pełne wgranie w nocy po pilotażu**. Restart IPC na początku części B – tak (z kontrolą: produkcja wstaje < 5 min, 20 wierszy/s). |

## Uwagi

- **K7-U1 – automatyczny stop wgrywania w nocy.** Bez nadzoru nocą narzędzie (albo osobny strażnik) wstrzymuje wgrywanie, gdy: dane real < 18 wierszy/s przez > 60 s, `aip-ingest` > 80 % limitu RAM, wolne miejsce < 3 × pozostała prognoza albo kolejka brokera dla ingestu > 20 000. Wznowienie rano tym samym poleceniem. W raporcie: czy zadziałał i dlaczego.
- **K7-U2 – kompresja.** Wstrzymanie tylko na noc wgrywania; wznowienie także przy przerwaniu (krok w procedurze „po przerwaniu”), w raporcie rozmiar bazy i liczba skompresowanych chunków przed i po.
- **K7-U3 – aktualizacje.** Restart w części B tylko uruchamia już zainstalowane aktualizacje; bez `apt upgrade` (D11: pakiety Dockera trzymane). Sprawdzić i opisać, czy `unattended-upgrades` może restartować usługi sieciowe lub Dockera; decyzja o wyłączeniu – Grzegorz, w k8.
- **K7-U4 – luka danych real 27.11** (od–do z bazy) do `data_windows` (`network_outage`), także luki z nocy wgrywania, jeśli wystąpią.
- **K7-U5 – adres.** Po rezerwacji DHCP plan używa docelowego adresu IPC (.213 po rezerwacji); w raporcie potwierdzenie adresu i prędkości łącza (1000 Mb/s po wymianie kabla/portu albo opis, czemu 100).

## Pytania do Grzegorza (z planu)

1. Czy ok. 20:49 27.11 kabel IPC był przełożony z portu 1 do portu 2? Który port zostaje (rezerwacja DHCP na jego MAC; `enp2s0` = `04:2b:58:12:f7:a2`)?
2. Kontrola kabla i portu switcha (100 Mb/s zamiast 1 Gb/s); rezerwacje DHCP: IPC .213, PLC .246.
