# e2-k4 report review: ingest (MQTT → walidacja → paczki → baza)

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k4-report.md`, `e2-k4-review.md`.

## Werdykt: OK – krok k4 zaliczony

| Kryterium | Dowód | Ocena |
| --- | --- | --- |
| pytest zielony na komputerze | `257 passed in 157.65s` (nowe 121), bez resztek `aip-test` | ✔ |
| `ack` po zapisie, brak strat i duplikatów | baza niedostępna: dokładnie 100 w locie, po powrocie 250/250 różnych wierszy; awaria bez potwierdzeń: 30/30; sesja trwała przy wyłączonym ingeście: 40/40 | ✔ (K4-U2) |
| U4: ingest przed bazą i `migrate` | test: pusta baza bez schematu i roli, ingest żyje, MQTT startuje dopiero po synchronizacji `devices` | ✔ |
| U1: `plc-01` w `devices`, `link_status` w bazie | `devices` = `plc-01` (plc) i `finder_7m24_1` (energy_meter); test e2e | ✔ |
| Walidacja | 9 powodów, granice okna czasu, NaN/Infinity/1e400, `source` vs urządzenie; 1000 wadliwych → 1 wpis WARNING | ✔ |
| Prawdziwy stos | `aip-ingest` healthy, uid 10003, `read_only`; `measurements` = 0 przed i po dymku; nieznane urządzenie odrzucone (`rejected=1`) | ✔ |
| K4-U3 | log bez haseł i SQL; `meta` bez adresu IP | ✔ |
| K4-U1, R2-U2 | utrata danych przy przerwach opisana w `docs/ops` (najstarsze w collectorze, najnowsze w Mosquitto, wygaśnięcie sesji po 7 dniach) | ✔ |
| smartWARE, porty, prawa plików | bez zmian; `.env` 600 | ✔ |
| Zasoby | ingest 26,3 MiB / 128 MB; suma limitów po k5: 1856 MB | ✔ |

Wykryty i poprawiony przed wdrożeniem błąd podwójnego potwierdzenia po izolacji wierszy dobrze pokazuje sens testów potoku. Odstępstwa 1–6 akceptowane: nazwy plików testów, helpery, sprzątanie sesji testowych, klucz `rejected`. Brak testu `retain` jest akceptowany, bo flaga jest ignorowana z konstrukcji. Restart brokera przechodzi do k5/k8.

## Uwagi do kolejnych kroków

1. **Przepustowość 1363/s** pochodzi z bazy w tmpfs (`fsync=off`). W k5 odczytać z podsumowania ingestu `zapis_ms_sr` i `zapis_ms_maks` na prawdziwej bazie. Przy 13/s paczki są małe; sam czas zapisu wystarczy jako wskaźnik.
2. **Etap 3, wypełnianie historii:** liczby z raportu (120 dni × 1 Hz ≈ 674 mln wiadomości, ponad 5 dni przez MQTT) przenoszę do decyzji etapu 3. Do wyboru będzie rzadsze próbkowanie historii albo osobny tor zapisu do bazy.
3. **Restart brokera w trakcie pracy:** test bez czekania na k8, w k5 na własnym kontenerze (`docker compose restart mosquitto` – to nasz kontener `aip-mosquitto`, nie smartWARE). Oczekiwane:
   - collector buforuje wiadomości i wysyła je po powrocie;
   - ingest łączy się ponownie z tą samą sesją;
   - w bazie brak luki dłuższej niż czas restartu i brak duplikatów (`UNIQUE`).

## Zakres k5 (dla planu `e2-k5-plan.md`)

Pierwsze prawdziwe dane. Polecenia na komputerze wykonuje Claude Code; czynności fizyczne – Grzegorz, w umówionych momentach, z jasnym „teraz odłącz / teraz podłącz”.

1. Usunięcie profilu `live`; `docker compose up -d` startuje collector bez `--profile`; pierwszy start z `read_only`, `cap_drop: ALL`, `tmpfs: /tmp`; healthcheck.
2. NAT: łączność kontenera z 192.168.0.246:502 (pierwszy odczyt FC04).
3. Zgodność wartości: w tej samej chwili `mbpoll` (z komputera, tylko odczyt, jak w etapie 1) i ostatnie wiersze w bazie – napięcie ±0,5 V, moc ±0,2 W, energia, serial.
4. Liczba wierszy: 780/min ±2% (764–796), `rejected=0`, heartbeat ok. 6/s.
5. **Test przerwy RS485 (Grzegorz odłącza jeden przewód na ok. 10 s):**
   - w bazie `meter_status = 1`, `meter_error_count` +1, `meter_data_age_ms` rośnie;
   - brak pomiarów licznika w tym czasie;
   - powrót pomiarów ok. 3 s po podłączeniu.
6. **Test PLC offline (Grzegorz odłącza kabel LAN1 PLC na ok. 30 s):**
   - `link_status = 1`, 1 wiersz/s;
   - po podłączeniu powrót bez ingerencji, w tym rozgrzewka ok. 1 s.
7. Opcjonalnie, za zgodą Grzegorza: Stop programu w CODESYS na ok. 15 s → `link_status = 2` (zamrożony heartbeat przy odpowiadającym serwerze Modbus – lub `1`, jeśli serwer CODESYS przestaje odpowiadać; wynik zapisać jako fakt) → Start. Download programu nie jest potrzebny.
8. Restart `aip-mosquitto` (punkt 3 wyżej).
9. Zasoby: `docker stats` collectora i ingestu pod obciążeniem, czas cyklu collectora na prawdziwej sieci, `zapis_ms` ingestu.
10. Raport z wydrukami (tekst) i krótkim „tak wygląda poprawny stan” dla dokumentacji. Zrzuty z GUI nie są potrzebne (Grafana dopiero w k7). Grzegorz może zrobić 1–2 zdjęcia przy testach fizycznych (opcjonalnie, `docs/images/etap2/30-…`).

Zasada 1 obowiązuje bez zmian: z komputera do PLC tylko FC04 (collector i `mbpoll -t 3`).

## Checklista Grzegorza po k4

Brak czynności.

## Następny krok

Claude Code: `docs/handoff/e2-k5-plan.md` wg sekcji „Zakres k5” → stop.
