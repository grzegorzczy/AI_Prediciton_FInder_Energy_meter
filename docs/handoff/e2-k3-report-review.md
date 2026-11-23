# e2-k3 report review: collector (Modbus TCP → MQTT)

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k3-report.md` (ostatni commit `b74e3c9`), `docker-compose.yml` (usługa `collector`), `config/devices.yaml`, `e2-k3-review.md`.

## Werdykt: OK – krok k3 zaliczony

| Kryterium z planu | Dowód | Ocena |
| --- | --- | --- |
| pytest zielony na komputerze | `136 passed in 92.50s` (k2: 44), w tym 8 testów e2e na prawdziwym Mosquitto; brak resztek `aip-test` | ✔ |
| Zasada 1 – tylko FC04 | `assert_only_reads()` = `{4}` we wszystkich scenariuszach e2e; atrapa odrzuca zapisy; publiczny interfejs klienta = `close`, `connect`, `connected`, `read_input_registers`; brak nazw metod zapisu w źródłach | ✔ |
| Reguła 3 | testy: brak IP, portu 502, numeru seryjnego, `plc-01`, `zaklad1`, `linia1` w kodzie usługi; `source` dla PLC i licznika z `devices.yaml` (K3-U1) | ✔ |
| Reguły ważności i kody (D10, U2) | ewaluator: kolejność, granica 5,0 s, zawinięcie heartbeatu, rozgrzewka, status przed serialem, kod 10 tylko dla jednego licznika (konfiguracja z dwoma) | ✔ |
| Obraz i Compose | 124,5 MB, uid 10002, konfiguracja `:ro` parsuje się w kontenerze; `config --quiet`; profil `live`; utwardzenie w definicji i w teście | ✔ |
| R2-U1 | pliki 644, katalogi 755, `.env` 600; `find` czysty także po kolejnym `git pull`; `docs/ops`: `.env` w podpowłoce, kontrola praw po `pull` | ✔ |
| R2-U3 | `deny` Read/Grep; Read i Grep ze ścieżką do pliku odmówione; atrapa usunięta | ✔ (luka opisana niżej) |
| smartWARE, porty | `StartedAt` bez zmian; `ss -ltn` bez zmian | ✔ |
| K3-U4 czasy | cykl 0,5 ms (atrapa), wykrycie offline 0,15 s, serwer milczący = `timeout_s`, 2 wpisy logu w 3 s awarii, cofanie 1/2/4/8/10 s | ✔ |

## Odstępstwa – ocena

| Nr | Ocena |
| --- | --- |
| 1 – rozgrzewka bez `link_status` | **akceptowane**: przez ok. 1 s panel pokazuje poprzedni stan, a nie fałszywe OK/alarm. Przy braku zmiany heartbeatu przez 5 s pojawia się `link_status = 2` – reguła kontraktu zachowana. Dopisać do `docs/status-codes.md` jedno zdanie (jeśli go nie ma) |
| 2 – `SimDevice` w atrapie | akceptowane (tylko testy) |
| 3 – `tests/dbtools.py` | akceptowane |
| 4 – montowania w `docker-compose.test.yml` | akceptowane (tylko do odczytu) |
| 5 – skrócone okresy w e2e | akceptowane; wartości produkcyjne sprawdzone osobno zegarem wstrzykniętym |
| 6 – `plc.source` w `devices.yaml` | akceptowane (K3-U1) |
| 7 – test `StateLogger` w `test_publisher_buffer.py` | akceptowane |

## Luka Grep po katalogu (R2-U3) – decyzja

Akceptuję stan opisany w raporcie. Bezpośredni odczyt `.env` (Read, Grep ze ścieżką) jest zablokowany regułami. Przeszukiwanie katalogu pomija `.env`, bo jest w `.gitignore`. Drogi przez powłokę obejmuje zasada „nie wypisujemy `.env`”, bez reguł `Bash`. Dodatkowych środków technicznych nie wprowadzamy. Zasada jest zapisana w dokumencie projektu 04 i w `e2-k1-results.md`.

## Do k5 (przenoszone)

1. Pierwsze uruchomienie kontenera collectora z `read_only`, `cap_drop: ALL`, `tmpfs: /tmp` – w tym healthcheck `python -m collector.health` (na systemie plików tylko do odczytu Python nie zapisze `__pycache__`, to oczekiwane).
2. NAT sieci Compose (172.31.50.0/24) do PLC 192.168.0.246:502 – pierwsza kontrola łączności z kontenera.
3. Prawdziwy PLC:
   - zgodność wartości z `mbpoll` (napięcie ±0,5 V, moc ±0,2 W);
   - test przerwy RS485 (`meter_status = 1`, diagnostyka, powrót ok. 3 s po podłączeniu);
   - PLC offline (odłączony kabel) i powrót bez ingerencji;
   - zatrzymany program PLC (Stop w CODESYS – test opcjonalny, za zgodą Grzegorza) → `link_status = 2`;
   - heartbeat ok. 6/s.
4. Zmierzone zużycie pamięci collectora (`docker stats`) i czas cyklu na prawdziwej sieci.
5. Usunięcie profilu `live` i sprawdzenie, że `docker compose up -d` startuje collector bez `--profile`.
6. Liczba wiadomości: 13/s przy sprawnym PLC i liczniku (wzór z K3-U2), 1/s przy `link_status ≠ 0`.

Zadania k7 bez zmian: K2-U5 (`maxOpenConns` ok. 5, `maxIdleConns` ok. 2), K3-U3 (kafelek stanu licznika uwzględnia `link_status`).

## Checklista Grzegorza po k3

Brak czynności.

## Następny krok

Claude Code: `docs/handoff/e2-k4-plan.md` (ingest: MQTT → walidacja → paczki → baza) z U1 (`plc-01` w `devices`), U4 (czekanie na bazę i tabele), U7/R2-U2 (bufor Mosquitto, utrata danych przy długiej przerwie – opisana wprost), synchronizacją `devices` z `devices.yaml` (upsert, `enabled=false` dla usuniętych), walidacją ładunku (w tym `source` zgodne z `devices.source`, `ts` nie z odległej przyszłości) i `ON CONFLICT DO NOTHING` → stop.
