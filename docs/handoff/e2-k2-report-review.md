# e2-k2 report review: Compose, Mosquitto, TimescaleDB, role, migracje

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k2-report.md` (commit `3dddca9`), `docker-compose.yml`, `config/mosquitto/*`, `config/devices.yaml`, `db/migrate.py`, `db/migrations/001_core.sql`, `.env.example` (sprawdzony: same nazwy zmiennych, żadnych wartości haseł), `e2-k2-review.md`.

## Werdykt: OK Z UWAGAMI – k2 zaliczony; uwagę R2-U1 wykonać na początku k3

„Gotowe, gdy” z planu k2 jest potwierdzone wynikami:

| Kryterium | Dowód | Ocena |
| --- | --- | --- |
| `mosquitto`, `timescaledb` healthy, `migrate` Exited (0) | wydruk `docker compose ps -a` | ✔ |
| pytest zielony | `44 passed in 69.74s` (konfiguracja 7, schemat 12, migracje 7, role 10, broker 8); po testach brak zasobów `aip-test` | ✔ |
| hypertable, kawałki 1 dzień, kompresja po 1 dniu, retencja 90 dni | `timescaledb_information.jobs`, `segmentby`, `orderby` | ✔ |
| U6: pamięć Postgresa | `shared_buffers` 384MB, `max_connections` 30, `work_mem` 4MB, `TimeZone` UTC, telemetria off; spoczynek 46,6 MiB / 1,5 GiB | ✔ |
| U5: role | `app_reader` tylko SELECT, `statement_timeout` 10 s, brak CREATE; `app_writer` bez DELETE/DDL; `public_connect` = f | ✔ |
| D3 / U3: MQTT | odmowa bez hasła i ze złym hasłem; obieg collector → ingest; `ingest` nie publikuje; tylko `127.0.0.1:1883` | ✔ |
| smartWARE nienaruszony | 7 × `StartedAt` bez zmian, porty 80/443 bez zmian | ✔ |
| K2-U4 podsieć | `172.31.50.0/24`, sprawdzone 172.17, 172.19, 172.20, LAN | ✔ |
| K2-U2 źródła pobierania | digesty obrazów, `pip freeze` w `docs/ops` | ✔ |
| Brak sekretów | raport, `.env.example`, logi `migrate` (`log_min_error_statement = panic`, błędy bez treści zapytania) | ✔ |

Dobre decyzje w wykonaniu:
- Hasła MQTT są usuwane ze środowiska brokera po wygenerowaniu pliku haseł.
- Nazwy kont są walidowane przed `sed`.
- Przy złym `POSTGRES_PASSWORD` `migrate` zgłasza czytelny błąd z odesłaniem do `docs/ops` (zamiast martwego `ALTER ROLE`, odstępstwo 7 – akceptowane).
- Poprawne wnioski z odstępstw 1 i 2: Mosquitto nie odrzuca SUBSCRIBE, tylko filtruje dostarczanie, a `default_transaction_read_only` nie jest granicą bezpieczeństwa. Granicą są uprawnienia. Wniosek dla etapu 6 zapisany.

## Odstępstwa – ocena

| Nr | Ocena |
| --- | --- |
| 1 (ACL Mosquitto: test zachowania zamiast odmowy SUBSCRIBE) | akceptowane – gwarancja ta sama |
| 2 (`default_transaction_read_only`) | akceptowane – test obu warstw osobno |
| 3 (migracje w obrazie `migrate`) | akceptowane, ale przyczyna wymaga naprawy – patrz R2-U1 |
| 4 (`-T`, `</dev/null`) | akceptowane, opisane w `docs/ops` |
| 5 (`run-tests.sh`, `-- migrate: next`) | akceptowane; podział bez transakcji zweryfikować na prawdziwym agregacie w k6 |
| 6 (TimescaleDB `2.32.1-pg16`) | **akceptowane**: obraz przypięty digestem, 44 testy zielone. Zostajemy przy 2.32.1; zmiana na `2.31.2-pg16` tylko przy problemie (jedna linia + testy). Wersję przeglądamy przed etapem 7 |
| 7 (bez wyrównania hasła `postgres`) | akceptowane |
| 8 (`deny Read(.env)`) | akceptowane, z R2-U3 |

## Uwagi

### R2-U1 (przed k3, obowiązkowe) – prawa plików w klonie na komputerze

Pliki w `/home/jumo/ai-predykcja` mają prawa 600/700. Przyczyną był `umask 077` z polecenia tworzącego `.env`: pozostał aktywny w otwartej konsoli Grzegorza, a późniejszy `git pull` w tej konsoli utworzył pliki bez prawa odczytu dla innych. Obejście przez wbudowanie plików w obraz `migrate` działa, ale w k3/k4 collector i ingest mają czytać `config/devices.yaml` montowany `:ro`. Kontener z użytkownikiem innym niż `jumo` dostałby wtedy `Permission denied`.

Do zrobienia na początku k3 (Claude Code, bez `sudo`):
1. Jednorazowo przywrócić zwykłe prawa w klonie **z wyjątkiem `.env`**: katalogi 755, pliki 644 (skrypty jak w repo), `.git` bez zmian; `.env` zostaje 600. Wynik (`stat` kilku plików, w tym `.env`) do raportu k3.
2. W `docs/ops/jumo-ipc-setup.md` (sekcja `.env`) dopisać: polecenie z `umask 077` uruchamiać w podpowłoce `( umask 077; … )` albo zamknąć konsolę po nim. Zmienić samo polecenie w `docs/ops` na wariant z podpowłoką.
3. Grzegorz: zamknąć okno konsoli, w którym tworzył `.env` (umask znika z sesją).
4. Decyzja projektowa dla k3/k4: montować `config/devices.yaml` `:ro` (prościej, zmiana adresu PLC bez przebudowy obrazu – zgodne z komentarzem w `devices.yaml`). Kontrola praw jak w pkt 1 trafia do `docs/ops` jako krok po każdym `git pull`.

### R2-U2 – `max_queued_messages`: co ginie po przepełnieniu

Mosquitto po zapełnieniu kolejki sesji odrzuca **nowe** wiadomości (zostają najstarsze), co komentarz w `mosquitto.conf` opisuje poprawnie. Raport k4 ma to powtórzyć wprost. Przy długiej przerwie ingestu luka w danych będzie na końcu przerwy, nie na początku. Dla demo akceptowalne.

### R2-U3 – kopia `.env` na laptopie i blokada w Claude Code

Decyzja Grzegorza (23.11.2026): kopia haseł to plik `.env` w katalogu repo na laptopie, ignorowany przez git (sprawdzone: `git check-ignore`, `git status` czysty). Menedżera haseł nie ma, więc pkt 2 checklisty k2 jest zamknięty tą decyzją.

`deny Read(.env)` blokuje tylko narzędzie Read. Proszę dodać też `deny` dla `Grep` na ścieżkach `.env` i `**/.env`. Reguł `Bash` nie dodajemy (wzorce poleceń są nieszczelne). Obowiązuje zasada: Claude Code nie wykonuje poleceń, które wypisują `.env` (`cat`, `type`, `grep` po wartościach), także na komputerze. Kontrola `.env` wyłącznie przez nazwy i długości.

### R2-U4 – drobne

- Sieć `upgrade_pg_default` i stare obrazy smartWARE: nie nasze, nie ruszamy. Zapisane w `docs/ops` jako znane pozostałości – ok.
- Uwaga K2-U5 (`maxOpenConns` w Grafanie) przechodzi do k7 – ok.
- Hasła w `environment` widoczne dla grupy `docker` – do etapu 7, zgodnie z raportem.

## Checklista Grzegorza po k2

1. `.env` na komputerze – zrobione.
2. Kopia haseł – zrobione (`.env` na laptopie, decyzja R2-U3).
3. Zamknąć okno konsoli `jumo@jumo-ipc`, w którym tworzony był `.env` (R2-U1 pkt 3).

## Następny krok

Claude Code: `docs/handoff/e2-k3-plan.md` (collector) z D2, D10, U2, U4, nowym filtrem 3 s w PLC (pola 10–15 wg `docs/modbus-map.md`), R2-U1 jako pierwszym punktem wykonania i R2-U3 (`deny Grep`) → stop.
