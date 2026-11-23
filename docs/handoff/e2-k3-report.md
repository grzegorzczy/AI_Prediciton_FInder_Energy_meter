# e2-k3 raport: collector (Modbus TCP → MQTT)
Status: DO PRZEGLĄDU

Wykonanie 23.11.2026 wg `e2-k3-plan.md` i uwag K3-U1…U4 z `e2-k3-review.md`. Polecenia na `jumo-ipc` wykonywałem
przez `ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null`), bez `sudo`, bez ruszania smartWARE, demona Dockera ani
`docker system prune`. **Nic nie łączyło się z PLC ani z licznikiem.** `.env` nie był czytany ani wypisywany (kontrola tylko
nazw, długości i praw). Raport nie zawiera sekretów.

## Co zrobiono

| Hash | Zawartość |
| --- | --- |
| `8b38a92` | review k3 |
| `7094fa4` | collector, atrapa PLC, testy, `docs/status-codes.md`, zmiany `devices.yaml`, Compose, `docs/ops`, `deny Grep` (39 plików) |

Pliki: `services/collector/` (`Dockerfile`, `requirements.txt`, `src/collector/`: `main`, `config`, `codec`, `status`, `evaluator`,
`publisher`, `messages`, `statelog`, `health`, `drivers/base`, `drivers/modbus_plc`), `config/devices.yaml` (zmiany), `docker-compose.yml`
(usługa `collector`), `docker-compose.test.yml`, `tests/fakes/modbus_plc.py`, `tests/collector/` (10 plików), `tests/dbtools.py`,
`docs/status-codes.md`, `docs/ops/jumo-ipc-setup.md`, `.claude/settings.json`.

## R2-U1: prawa plików w klonie (wykonane jako pierwsze)

Przed (tylko nazwy i prawa): `.env` 600, `config/devices.yaml` 600, `db/migrate.py` 600, `config` 700, `db` 700, `tests/run-tests.sh` 664.
Po poprawce (`find … chmod 755/644`, `chmod 600 .env`; `.git` nietknięty):

```text
600 jumo .env
644 jumo config/devices.yaml
644 jumo db/migrate.py
755 jumo config
755 jumo db
775 jumo .git
644 jumo tests/run-tests.sh
```

Kontrola `find` na plikach i katalogach nieczytelnych dla innych: **bez wyników**; `git status -sb` czysty; kontenery `aip-` nie były
ruszane. Po późniejszym `git pull` (commit `7094fa4`) ta sama kontrola: bez wyników, `.env` nadal 600 (nowe pliki dostały 664/775,
czyli czytelne). `docs/ops/jumo-ipc-setup.md`: polecenie tworzące `.env` jest teraz w podpowłoce `( umask 077; … )`, dodany krok
„kontrola praw po każdym `git pull`” z komendami `find` i naprawą; decyzja o montowaniu `config/devices.yaml` `:ro` zapisana.
Okno konsoli z `umask 077`: zamknięcie po stronie Grzegorza (potwierdzone w review k3, bez czynności).

## R2-U3: `deny Grep` dla `.env` i test na atrapie

`.claude/settings.json`: `Read(.env)`, `Read(**/.env)`, `Grep(.env)`, `Grep(**/.env)`. Test na atrapie `docs/decoy/.env`
(treść `DECOY=1`, ignorowana przez git, usunięta po teście). Wyniki:

| Próba | Wynik |
| --- | --- |
| Zapis atrapy narzędziem Write | odmowa („covered by a Read deny rule”) |
| Odczyt atrapy narzędziem Read | odmowa |
| Grep ze ścieżką bezpośrednio do pliku (przed dodaniem reguł `Grep`) | odmowa (już przez regułę `Read`) |
| Grep ze ścieżką do pliku (po dodaniu reguł `Grep`) | odmowa |
| Grep na katalogu z atrapą (z `glob: .env` i bez) | „No matches found”: **nie odmowa**, tylko pominięcie, bo ripgrep omija pliki ignorowane przez `.gitignore` |

Wniosek: bezpośrednie dotarcie do `.env` przez Read lub Grep jest zablokowane. Przeszukiwanie katalogu nie czyta `.env` tylko dlatego,
że jest w `.gitignore`, a nie dzięki regule; nie mam opcji narzędzia, która by to wymusiła, więc tej luki nie da się przetestować inaczej.
Ścieżki przez powłokę (`cat`, `type`, `grep` w `Bash` lub `PowerShell`) nie są objęte regułami (decyzja architekta: bez reguł `Bash`);
obowiązuje zasada: nie wykonuję poleceń wypisujących `.env`. Atrapa usunięta (`docs/decoy` nie istnieje, `git status` czysty).

## Wyniki testów

Polecenie na komputerze: `sh tests/run-tests.sh </dev/null` (projekt `aip-test`, dane w tmpfs). Lokalnie na laptopie przed wypchnięciem:
91 przeszło, 8 pominiętych (testy e2e wymagają brokera).

**`136 passed in 92.50s`** na komputerze (k2: 44; nowe: 92). Rozkład: kodek 13, Compose 6, loader konfiguracji 15, sterownik 7, e2e 8,
ewaluator 18, brak zapisu 6, ładunek 7, bufor MQTT 6 (w tym logowanie stanów), dokument statusów 4, konfiguracja 9 (+2), baza 29, broker 8.
Po testach nie zostały zasoby projektu `aip-test`.

### Zasada 1: do PLC nie piszemy (trzy warstwy plus kody funkcji w scenariuszach)

- `test_public_interface_of_the_client_is_read_only`: publiczny interfejs `ReadOnlyModbusClient` = `close`, `connect`, `connected`,
  `read_input_registers`.
- `test_no_write_function_names_in_collector_sources`: w `services/collector/` brak nazw `write_*`, `mask_write`, `readwrite`, `WriteSingle`…
- `test_only_fc04_is_requested_in_sources`: w źródłach tylko `read_input_registers`, bez odczytu cewek czy rejestrów podtrzymujących.
- **`assert_only_reads()` w każdym ze scenariuszy e2e** (pełny cykl, PLC offline i powrót, zamrożony heartbeat, zła mapa, przerwa RS485, zły serial):
  do serwera atrapy docierał wyłącznie kod funkcji **04** (zbiór `{4}`), a atrapa dodatkowo odrzuca każdy zapis.
- Reguła 3: `test_no_ip_addresses_or_port_in_code` i `test_no_device_identifiers_or_register_numbers_in_code`: w kodzie usługi brak
  adresów IP, portu 502, numeru seryjnego, `finder_7m24`, `plc-01`, `zaklad1`, `linia1`.

### Pokrycie reguł ważności i kodów statusów (D10, U2)

Ewaluator: kolejność (offline → mapa → heartbeat → liczniki), heartbeat dokładnie 5,0 s nie jest awarią, powyżej tak (zegar wstrzyknięty),
zawinięcie `FFFFFFFF` → 0 to zmiana, rozgrzewka, status 0/1/2/nieznany, **status przed serialem** (NO_DATA z pustym serialem nie daje 10),
kod 10 blokuje tylko ten licznik (konfiguracja z dwoma licznikami, bazy 10 i 60), wartości nieskończone pomijane i zgłaszane,
`source` z konfiguracji (K3-U1: urządzenie i PLC z `source: sim` dają `"source":"sim"` w ładunku). E2E z prawdziwym Mosquitto (konto `ingest`):
komplet **13 wiadomości na cykl** z wartościami z próbki 23.11.2026 (U 240,4 V, P 7,0 W, f 50,02 Hz, energia 3500 Wh, serial zgodny),
`link_status` 1, 2, 3, `meter_status` 1 z diagnostyką i powrót po przerwie RS485, `meter_status` 10.

## Pomiary czasu (K3-U4)

Na komputerze, atrapa PLC na localhost (wartości **nie** są wartościami z prawdziwej sieci i PLC; to dolna granica, prawdziwe pomiary w k5):

| Pomiar | Wynik |
| --- | --- |
| Jeden cykl: odczyt FC04 (44 rejestry) + ocena | mediana **0,5 ms**, maks. 0,7 ms z 30 cykli |
| Wykrycie „PLC offline” po wyłączeniu serwera (połączenie zamknięte) | **0,15 s** (przy `timeout_s` = 1,0; wymóg: ≤ `timeout_s` + 1 s) |
| Odczyt z serwerem, który przyjmuje połączenie i milczy (zawieszone PLC) | **1,00 s** przy `timeout_s` = 1,0 (czyli bez ponowień biblioteki); przy produkcyjnym `timeout_s` = 2,0 oczekuję ok. 2 s |
| Logi w 3 s ciągłej awarii (ok. 15 cykli) | **2 wpisy WARNING** (próg testu: ≤ 4) |

Wniosek: `retries=0` i `reconnect_delay=0` w pymodbus działają; bez nich zapytanie do wyłączonego PLC trwałoby kilkanaście sekund.
Cofanie wykładnicze sprawdzone zegarem wstrzykniętym: próby w 0, 1, 3, 7, 15, 25 s (1, 2, 4, 8, 10 s).

## Obraz i Compose

- `docker compose build` obrazu `aip-collector:local`: **124,5 MB**, użytkownik **uid 10002** (nie-root), import pakietu `collector.main` OK,
  `load_config('/config/devices.yaml')` w kontenerze (montowanie `:ro`) przechodzi: `zaklad1 linia1 192.168.0.246 502 ['finder_7m24_1']`.
- `docker compose config --quiet` bez profilu: usługi `migrate mosquitto timescaledb`; z `--profile live`: dochodzi `collector`.
  **Kontener collectora nie istnieje i nie był uruchamiany** (profil `live` do k5). Stos `aip-` bez zmian (`mosquitto`, `timescaledb` healthy,
  `migrate` Exited (0)); `StartedAt` wszystkich 7 kontenerów smartWARE bez zmian; `ss -ltn` bez zmian (collector bez portów).
- Utwardzenie w definicji (test `test_compose_service.py`): `read_only: true` z `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit` i
  `memswap_limit` 128 MB, `restart: unless-stopped`, `depends_on: mosquitto: service_healthy`, `config/devices.yaml:ro`, bez portów,
  konto MQTT tylko `collector`. Suma limitów `aip-` stale: 1600 + 128 = **1728 MB**.
- `pip freeze` obrazu: `paho-mqtt==2.2.0`, `pymodbus==3.16.2`, `PyYAML==6.0.4` (bez zależności pośrednich; dopisane do `docs/ops`).

## Zasoby

`free -m` w trakcie testów (próbka po 40 s): used 1478 MB, available 13 627 MB, swap 0. Kontenery testowe: `aip-test-db-1` 112,4 MiB / 512,
`aip-test-pytest-run` 51,2 MiB / 256, `aip-test-mosquitto-1` 1,3 MiB / 64. Stos `aip-` w spoczynku: `aip-timescaledb` 46,8 MiB / 1,5 GiB,
`aip-mosquitto` 1,5 MiB / 64 MiB. smartWARE bez zmian (ok. 517 MiB razem). **Zużycie pamięci kontenera collectora nie jest zmierzone**: kontener
nie działał (zmierzę w k5).

## Odstępstwa od planu i dlaczego

1. **Rozgrzewka nie publikuje też `link_status`.** Plan mówił o braku pomiarów do pierwszej zmiany heartbeatu. Dodatkowo w tym jednym
   cyklu (ok. 1 s po połączeniu) nie publikuję `link_status`, bo „0” byłoby deklaracją sprawności bez zweryfikowanych danych, a „2” fałszywym
   alarmem. Panel pokazuje przez ten czas poprzedni stan (zwykle `link_status` = 1 z awarii).
2. **API pymodbus 3.16.2 różni się od moich założeń z planu**, co dotyczy tylko atrapy i testów, nie kodu produkcyjnego: model danych
   (`ModbusDeviceContext`, `ModbusSequentialDataBlock`) jest przestarzały (błąd adresu, ostrzeżenia), więc atrapa używa `SimDevice` z funkcją
   `action`, która wstawia aktualny obraz rejestrów przy każdym odczycie i odrzuca żądania zapisu; `retries` jest w `client.ctx.retries`, a
   `reconnect_delay` w `client.comm_params`.
3. **Wspólne helpery testów bazy w `tests/dbtools.py`.** W repo są teraz dwa pliki `conftest.py` (główny i `tests/collector/`), więc import po
   nazwie `conftest` byłby niejednoznaczny. Zmieniłem importy w `test_migrations.py` i `test_roles.py` (zmiana mechaniczna, testy z k2 nadal zielone).
4. **`docker-compose.test.yml`:** kontener `pytest` dostaje dodatkowo zamontowane `docs`, `services` i `docker-compose.yml` (tylko do odczytu) oraz
   `PYTHONPATH` do kodu collectora; w `tests/requirements.txt` doszedł `pymodbus==3.16.2`.
5. **W testach e2e skrócone okresy:** `poll_interval_s` 0,2 s, `timeout_s` 1 s, `heartbeat_timeout_s` 1 s (nadpisania konfiguracji). Wartość produkcyjna
   5 s i granica „dokładnie 5,0 s” są sprawdzone osobno w testach ewaluatora zegarem wstrzykniętym.
6. **Pole `plc.source` w `devices.yaml`** (domyślnie `real`): zgodnie z K3-U1 źródło ładunku dla `plc-01` też pochodzi z konfiguracji.
7. **Test logowania stanów** (`StateLogger`) jest w `test_publisher_buffer.py`, nie w osobnym pliku.

## Uwagi K3-U1…U4 i zadania na kolejne kroki

- **K3-U1:** wykonane (patrz wyżej, testy w `test_evaluator.py` i `test_payload.py`).
- **K3-U2:** 13 wiadomości na sekundę = **780 wierszy na minutę**, ok. 1,12 mln na dobę (13 × 86 400 = 1 123 200) i ok. 101 mln w 90 dni.
  **Wzór do checklisty k5:** 7 pomiarów + 2 stany energii + `meter_status` + `meter_error_count` + `meter_data_age_ms` + `link_status` = 13 na sekundę
  (przy `meter_status` ≠ 0 wierszy jest mniej; przy `link_status` ≠ 0 tylko 1 na sekundę). Pomiar dysku po dobie w k8.
- **K3-U3 (zadanie k7):** kafelek stanu licznika w Grafanie ma uwzględniać `link_status` („brak danych z PLC”, gdy `link_status` ≠ 0 albo ostatni
  `meter_status` starszy niż kilka sekund), obok K2-U5 (`maxOpenConns` ok. 5, `maxIdleConns` ok. 2).
- **K3-U4:** pomiary powyżej; `docs/status-codes.md` zawiera zachowanie czasowe (NO_DATA do ok. 10 s po starcie PLC, brak pomiarów ok. 3 s po przerwie
  RS485 przez filtr PLC, ok. 1 s po połączeniu); w k5 przy usuwaniu profilu `live` sprawdzę, że `docker compose up -d` startuje collector bez `--profile`.
- **R2-U2:** asymetria buforów: collector przy przepełnieniu (20 000 wiadomości, ok. 25 minut przy 13 na sekundę) odrzuca **najstarsze**, a Mosquitto przy
  zapełnieniu kolejki sesji ingestu odrzuca **najnowsze**. Przy długiej przerwie ingestu luka w danych będzie na końcu przerwy; powtórzę to w raporcie k4.

## Checklista dla Grzegorza

Brak czynności (zgodnie z review k3): krok nie dotyka sprzętu ani GUI.

## Otwarte kwestie

- **Pierwsze uruchomienie kontenera collectora z `read_only: true`, `cap_drop: ALL` i `tmpfs: /tmp` nastąpi dopiero w k5.** Testy sprawdzają definicję,
  a obraz uruchomiłem tylko z poleceniami diagnostycznymi. Kod zapisuje wyłącznie plik znacznika w `/tmp`, więc nie oczekuję problemu, ale to jedyne
  miejsce, gdzie definicja nie była jeszcze wykonana.
- **k5:** NAT sieci Compose do PLC (192.168.0.246:502) nie był sprawdzany; zachowanie zatrzymanego PLC z odpowiadającym serwerem Modbus (zamrożone
  rejestry) i ciągłość heartbeatu 6/s zweryfikuje test na sprzęcie. Atrapa zachowuje się jak serwer dla FC04, ale nie jest serwerem CODESYS.
- **Luka `.gitignore` przy Grep** opisana w sekcji R2-U3; do ewentualnej decyzji architekta.
