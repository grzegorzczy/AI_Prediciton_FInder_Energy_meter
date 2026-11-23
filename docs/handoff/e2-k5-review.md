# e2-k5 review: pierwsze prawdziwe dane

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k5-plan.md` (commit `d803b96`), `e2-k4-report-review.md` („Zakres k5”), `e2-k3-report-review.md`, `docs/modbus-map.md`, `docs/stages/etap-1.md`, dokumenty projektu 00, 01, 12.

## Werdykt: OK

Plan pokrywa cały „Zakres k5” i punkty „Do k5” z review k3. Szczególnie dobre:
- kontrola PLC przed startem (`mbpoll` hex: mapa, status, serial) ze stopem przy różnicy;
- test samego gniazda TCP z kontenera przed pierwszym żądaniem Modbus;
- natychmiastowe wycofanie (`docker compose stop collector`);
- czytelny protokół „TERAZ odłącz / odłączony / TERAZ podłącz / podłączony”;
- wyznaczanie czasów z danych, a nie z zegarka;
- obsługa ryzyka DHCP i drugiego klienta Modbus;
- test Stop programu tylko za wyraźną zgodą.

Zasada 1 jest zachowana: collector i `mbpoll -t 3` używają tylko FC04.

## Decyzje K5-a…K5-g – wszystkie zatwierdzone

| Id | Rozstrzygnięcie |
| --- | --- |
| K5-a | Bez zmian w kodzie; czas cyklu pośrednio – zatwierdzone |
| K5-b | RS485 ok. 10 s, LAN1 ok. 30 s – zatwierdzone |
| K5-c | Stop programu opcjonalny, tylko za zgodą w chwili testu – zatwierdzone (patrz K5-U2) |
| K5-d | 5 par `mbpoll`/baza, plan awaryjny przy odmowie drugiego klienta – zatwierdzone |
| K5-e | Okno 10 pełnych minut – zatwierdzone (patrz K5-U4) |
| K5-f | DHCP: > 60 s `link_status = 1` po podłączeniu → stop i pytanie – zatwierdzone |
| K5-g | Dane z testów zostają, okna czasu w raporcie – zatwierdzone (patrz K5-U3) |

## Uwagi

### K5-U1 – który kabel: LAN1, nie LAN2

variTRON 300 ma dwa gniazda Ethernet: **LAN1** = sieć ze switchem (192.168.0.246, Modbus TCP) i **LAN2** = system bus EtherCAT do modułów (router 705043, CTR04). Do testu PLC offline odłączamy **wyłącznie LAN1**. Odłączenie LAN2 nie testuje komunikacji z komputerem, za to przerywa szynę modułów (w etapie 1 zmieniło też moc z 7 na 6,7 W). W komunikacie „TERAZ odłącz” napisać wprost: „kabel **LAN1** (do switcha), **nie** LAN2”.

### K5-U2 – Stop programu w CODESYS (jeśli Grzegorz się zgodzi)

- Grzegorz jest zalogowany online do tej samej aplikacji. Używa **Stop**, a po ok. 15 s **Start**. Nie używa „Reset” (warm/cold/origin) ani „Login with download”.
- Jeśli CODESYS przy logowaniu zapyta o download (program w IDE różni się od sterownika), anulować i nie robić testu. Program na sterowniku to wersja z poprawką `FB_EnergyMeter` z 23.11.2026, a ponowny download nie jest potrzebny.
- Po Start sprawdzić stan RUN w CODESYS i `link_status = 0` w bazie.

### K5-U3 – okna testów w formie do maszynowego użycia

W raporcie tabela okien testowych w UTC: `start`, `koniec`, `rodzaj` (`rs485_break`, `plc_lan1_unplugged`, `plc_program_stop`, `mqtt_broker_restart`), `uwagi`. Tę samą tabelę przeniosę do dokumentu projektu 12. Etap 4/5 wyłączy te okna z analityki (później jako wpisy w tabeli `events`).

### K5-U4 – kolejność i rozdzielenie okien

Okno 10 minut do liczenia wierszy (krok 4) ma nie nachodzić na żaden test (RS485, LAN1, Stop, restart brokera) ani na start collectora. Proponowana kolejność:

1. start;
2. 10 minut spokoju (liczenie i zasoby);
3. restart brokera;
4. RS485;
5. LAN1;
6. ewentualnie Stop.

Między testami co najmniej 1 minuta stabilnej pracy, żeby każdy powrót był widoczny osobno.

### K5-U5 – heartbeat i pierwsze sekundy przerwy

- Heartbeat „ok. 6/s” to obserwacja z etapu 1, nie wymóg. Kryterium kontraktu: zmiana w ciągu 5 s. Zmierzoną wartość zapisać jako fakt.
- W pierwszym ułamku sekundy po odłączeniu RS485 PLC może jeszcze podawać status 0 z ostatnimi dobrymi wartościami („Keep last value”), zanim kanał RTU zgłosi timeout (rzędu 200 ms × zapytania w kolejce). Pojedynczy wiersz pomiaru z tej chwili nie jest błędem. Kryterium: od pierwszego `meter_status = 1` do powrotu brak pomiarów. Opisać w raporcie, jeśli się pojawi.

## Kontrola reszty planu

- Zasady twarde: brak zapisu do PLC (FC04, `mbpoll -t 3`), brak zmian w PLC i mapie, smartWARE nieruszany, bez `sudo` – ✔.
- „Gotowe, gdy” k5 – tabela kryteriów sprawdzalna danymi z bazy i logów – ✔.
- Rola Grzegorza ograniczona do trzech czynności fizycznych na wyraźne polecenie – ✔ (zgodnie z dokumentem 04).
- Dokumentacja: wydruki tekstowe, osie czasu testów, opcjonalne zdjęcia `docs/images/etap2/30-…` – ✔.

## Checklista Grzegorza w k5

1. Na „TERAZ odłącz przewód RS485” – odłączyć **jeden** przewód przy złączu „COM” PLC, odpisać „odłączony”; na „TERAZ podłącz” – podłączyć, odpisać „podłączony”.
2. Na „TERAZ odłącz kabel LAN1” – odłączyć **LAN1** (do switcha), nie LAN2; potem podłączyć jak wyżej.
3. Opcjonalnie: zgoda (albo nie) na Stop/Start programu w CODESYS wg K5-U2.
4. Opcjonalnie 1–2 zdjęcia (np. odłączony przewód RS485).

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k5 w kolejności z K5-U4, z uwagami K5-U1…U5 → `e2-k5-report.md` → stop.
