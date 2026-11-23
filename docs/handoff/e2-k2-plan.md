# e2-k2 plan: Compose, Mosquitto, TimescaleDB, role, migracje
Status: DO PRZEGLĄDU

Podstawa: `e2-k0-plan.md`, `e2-k0-review.md` (decyzje D1, D3, D4, D9; uwagi U1, U3, U5, U6),
`e2-k1-report-review.md` (OK, punkt startowy k2 i dwie drobne poprawki do `docs/ops`),
`e2-k1-results.md` (tryb wykonania na komputerze), `CLAUDE.md`, `docs/data-model.md`.

## Cel kroku

Na `jumo-ipc` działa szkielet kręgosłupa danych: **Mosquitto z hasłem i ACL**, **TimescaleDB** z
tabelami `devices` i `measurements` (hypertable, kompresja po 1 dniu, retencja 90 dni), dwie role
(`app_writer`, `app_reader`) i jednorazowy kontener `migrate`. Collector, ingest i Grafana
dochodzą w k3, k4 i k7.

**Sprawdzalny wynik:** `docker compose ps` pokazuje `mosquitto` i `timescaledb` jako `healthy`, a
`migrate` zakończony kodem 0; testy pytest (konfiguracja, migracje, role, broker) zielone na komputerze;
`mosquitto_sub` bez hasła odrzucony; `app_reader` nie może pisać ani tworzyć obiektów; zrzuty 03 i 04.

## Tryb wykonania na komputerze

Jak w `e2-k1-results.md`: polecenia wykonuję przez `ssh jumo@192.168.0.213` (Git Bash, `bash -s`
z heredoc, bez zagnieżdżonego `ssh` bez `-n`), **bez `sudo`**, nie ruszam smartWARE (kontenerów,
wolumenów, sieci), demona Dockera ani `docker system prune`. Wszystko, co uruchamiam, działa w
projekcie Compose `ai-predykcja` (testy w osobnym `aip-test`) i dotyczy wyłącznie jego zasobów.
`docker compose down -v` na projekcie `ai-predykcja` tylko za Twoją zgodą (kasuje dane).
**W raportach nie ma sekretów:** nie wklejam wyniku `docker compose config`, `docker inspect`
ani `env`, bo zawierają hasła z `.env`; walidacja przez `docker compose config --quiet`.

## Co powstaje / zmienia się (pliki)

```
docker-compose.yml                    mosquitto, timescaledb, migrate (reszta w k3, k4, k7)
docker-compose.test.yml               infrastruktura testów: projekt aip-test, dane w tmpfs
.env.example                          nowe zmienne MQTT (D3), komentarze
config/devices.yaml                   D1: site zaklad1, line linia1; PLC, profil, urządzenie
config/mosquitto/mosquitto.conf
config/mosquitto/acl.conf
config/mosquitto/entrypoint.sh        generuje plik haseł z zmiennych środowiskowych
db/Dockerfile, db/requirements.txt    obraz kontenera migrate (Python 3.12)
db/migrate.py                         runner: role, migracje, schema_migrations
db/migrations/001_core.sql            devices, measurements, hypertable, kompresja, retencja
tests/Dockerfile, tests/requirements.txt, tests/conftest.py, pytest.ini
tests/config/test_devices_yaml.py
tests/db/test_migrations.py, tests/db/test_roles.py, tests/db/test_core_schema.py
tests/mqtt/test_broker_acl.py
docs/handoff/e2-k2-report.md
docs/ops/jumo-ipc-setup.md            dwie poprawki z review k1 + sekcja `.env` i uruchomienia stosu
docs/images/etap2/03-compose-ps-healthy.png, 04-mosquitto-auth-denied.png   (dostarcza Grzegorz)
```

Zmiany względem listy z k0: **`db/init/00-roles.sh` nie powstaje** (U5: role tworzy i aktualizuje
`migrate` przy każdym uruchomieniu, nie tylko skrypt pierwszego startu bazy).

## Compose: kontenery, porty, limity

Wspólnie: `name: ai-predykcja`, nazwy kontenerów z prefiksem `aip-` (bez kolizji z smartWARE:
`mqtt`, `postgres-server`, `reverse-proxy`), `restart: unless-stopped` (`migrate`: `"no"`),
logi `json-file` (10 MB × 3), `TZ` z `.env`, `memswap_limit` równe `mem_limit` (patrz K2-d),
konfiguracja montowana `:ro`, w `environment` tylko zmienne potrzebne danej usłudze (nie `env_file`).

| Kontener | Port na hoście (U3) | mem_limit | Dane |
| --- | --- | --- | --- |
| `aip-mosquitto` | `127.0.0.1:1883` (nie w LAN; K2-a) | 64 MB | wolumen `aip_mosquitto_data` (persistence) |
| `aip-timescaledb` | brak | 1536 MB (`shm_size` 256 MB) | wolumen `aip_pgdata` |
| `aip-migrate` | brak | 64 MB (tylko w trakcie działania) | `db/migrations` tylko do odczytu |
| **Suma stale** | | **1600 MB** (+64 MB chwilowo) | |

Sieć: jedna sieć projektu `backend` z jawnie podaną podsiecią (K2-g), wybraną po sprawdzeniu
istniejących sieci (tak, by nie nakładała się na LAN 192.168.0.0/24 ani sieci smartWARE).
`depends_on: condition: service_healthy` działa przy `docker compose up`; po restarcie komputera
decyduje `restart: unless-stopped` (U4: usługi k3/k4 same czekają na zależności).

### Mosquitto (D3, U3, U7)

- Obraz `eclipse-mosquitto` w przypiętej wersji 2.0.x (D9, wersja i digest w raporcie).
- `allow_anonymous false`; plik haseł powstaje przy starcie z `MQTT_COLLECTOR_*` i `MQTT_INGEST_*`
  (`mosquitto_passwd`, prawa 0600, na tmpfs, nie w repo ani w wolumenie); `entrypoint.sh`
  uruchamiany przez `sh` (nie polegamy na bitach wykonywania z Windowsa), kończy `exec mosquitto`.
- ACL (`acl.conf`): `collector`: tylko `write +/+/+/+`; `ingest`: tylko `read +/+/+/+`.
  Brak dostępu do `$SYS`.
- `persistence true`, `max_queued_messages` i `max_queued_bytes` dobrane do bufora ok. 60 minut
  (11 wiadomości/s ≈ 40 tys.) w limicie 64 MB; wartości i zmierzone zużycie w raporcie (U7).
- Healthcheck: kontrola portu (`nc -z`) plus test funkcjonalny w pytest (K2-b).

### TimescaleDB (U6)

- Obraz `timescale/timescaledb` w przypiętej wersji, PostgreSQL 16 (K2-h; D9: wersja i digest w raporcie).
- **`NO_TS_TUNE=true`** i jawne parametry w `command`: `shared_buffers=384MB`,
  `effective_cache_size=768MB`, `work_mem=4MB`, `maintenance_work_mem=128MB`, `max_connections=30`,
  `timezone=UTC`, `timescaledb.telemetry_level=off` (lokalnie, bez internetu). Zamiast domyślnego
  strojenia na pamięć całego komputera (16 GB). Raport: wynik `SHOW shared_buffers; SHOW max_connections;
  SHOW work_mem;`.
- Baza `energy`, superużytkownik `postgres` tylko dla `migrate`; usługi używają `app_writer` /
  `app_reader`. Bez portu na hoście.
- Healthcheck: `pg_isready -U postgres -d energy`.

## Schemat i role (D4, U1, U5)

### `migrate` (jednorazowy; D4)

`db/migrate.py` przy **każdym** uruchomieniu, w tej kolejności, pod `pg_advisory_lock`:

1. **Role** (idempotentnie): `DO`-blok tworzy `app_writer` i `app_reader`, jeśli ich nie ma;
   `ALTER ROLE … PASSWORD` z `APP_WRITER_PASSWORD` / `APP_READER_PASSWORD` (zmiana hasła w `.env`
   i ponowny `migrate` wystarczy); `REVOKE ALL ON DATABASE energy FROM PUBLIC`, `GRANT CONNECT`;
   `REVOKE CREATE ON SCHEMA public FROM PUBLIC`; `ALTER DEFAULT PRIVILEGES` (poniżej).
2. **Migracje:** pliki `db/migrations/NNN_*.sql` w kolejności, każdy w transakcji, zapis w
   `schema_migrations(version, name, checksum, applied_at)`. Już zastosowana migracja ze zmienioną
   sumą kontrolną = błąd (nie modyfikujemy historii). Migracja oznaczona `-- migrate: no-transaction`
   (potrzebne dla agregatów ciągłych w k6) idzie bez transakcji.
3. **Uprawnienia po migracjach:** ponowne `GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_reader`
   (obejmuje widoki), żeby kolejność nie miała znaczenia.

`migrate` kończy się kodem 0 przy sukcesie, ≠ 0 przy błędzie. Po restarcie komputera `migrate` się nie
uruchamia (U4); ingest w k4 sam czeka na tabele.

### Role

| Rola | Uprawnienia |
| --- | --- |
| `app_writer` (ingest; później analytics) | `CONNECT`, `USAGE` na schemacie, na `measurements`: `SELECT, INSERT`; na `devices`: `SELECT, INSERT, UPDATE` (synchronizacja z `devices.yaml`). Bez `DELETE`, `DDL`. Kolejne tabele dostają jawne `GRANT`-y w swoich migracjach |
| `app_reader` (Grafana; czat) | tylko `SELECT` na tabelach, widokach i agregatach (w tym tworzonych później: `ALTER DEFAULT PRIVILEGES`); brak `CREATE` na schemacie; `statement_timeout = 10s`, `idle_in_transaction_session_timeout = 30s`, `default_transaction_read_only = on`, `CONNECTION LIMIT 10` (K2-e) |

### `001_core.sql`

- `devices`: kolumny z `docs/data-model.md`; `kind` ograniczone do `plc`, `energy_meter`, `pump`
  (**U1: `plc-01` jest urządzeniem w `devices`**, `kind = plc`, `source = real`); wpisy dodaje ingest
  z `config/devices.yaml` w k4, nie migracja (reguła 3).
- `measurements`: `time TIMESTAMPTZ`, `device_id` (FK → `devices`), `metric`, `value DOUBLE PRECISION`,
  `unit`, `source CHECK (real, sim)`; `value` odrzuca `NaN` i nieskończoność; `UNIQUE (device_id, metric, time)`.
- Hypertable po `time`, kawałki 1 dzień; kompresja po 1 dniu, `segmentby = device_id, metric`,
  `orderby = time DESC`; retencja 90 dni.
- Bez `energy_1m`, `energy_1h` (k6) i bez tabel z późniejszych etapów (D8).

## `config/devices.yaml` (D1)

Struktura jak w szkicu z e2-k0-plan, z `site: zaklad1` i `line: linia1`; PLC `plc-01`
192.168.0.246:502 (adres tylko tu), `unit_id: 1`, FC04, odczyt rejestrów 0–43 (`count: 44`),
`map_version: 1`, `heartbeat_timeout_s: 5`; profil `finder_7m24` z offsetami z
`docs/modbus-map.md`; urządzenie `finder_7m24_1`, `block_base: 10`, serial `F0183363`. Plik jest
tworzony w k2, bo D1 ustala nazwy tematów MQTT; konsumentami są collector (k3) i ingest (k4), w k2
sprawdza go tylko test. Testowany układ: wymagane pola, unikalne `id`, brak nakładających się bloków,
`site` i `line` bez spacji i znaków spoza ASCII (segmenty tematu).

## `.env` i polecenia (tworzy Grzegorz; ja nie widzę wartości)

### Zmienne (po zmianie `.env.example`)

| Zmienna | Wartość | Skąd |
| --- | --- | --- |
| `TZ` | `Europe/Warsaw` | stała z `.env.example` (strefa kontenerów; baza zawsze UTC) |
| `POSTGRES_DB` / `POSTGRES_USER` | `energy` / `postgres` | stałe z `.env.example` |
| `POSTGRES_PASSWORD` | losowe | generowane na komputerze |
| `APP_WRITER_PASSWORD`, `APP_READER_PASSWORD` | losowe | generowane |
| `MQTT_COLLECTOR_USER` / `MQTT_COLLECTOR_PASSWORD` | `collector` / losowe | D3 |
| `MQTT_INGEST_USER` / `MQTT_INGEST_PASSWORD` | `ingest` / losowe | D3 |
| `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` | `admin` / losowe | używane od k7 (hasło do logowania odczytasz sam: `grep GF_SECURITY_ADMIN_PASSWORD ~/ai-predykcja/.env`; nie wklejaj go do czatu) |
| `CHAT_SQL_TIMEOUT_MS`, `OLLAMA_MODEL`, `CLOUD_LLM_*` | bez zmian | etap 6, nie ruszamy |

Nie wpisujesz żadnych haseł ręcznie: generuje je komputer, a polecenie nie wypisuje ich na ekran.

### Polecenie (po wypchnięciu przeze mnie nowego `.env.example`, w Twojej konsoli `jumo@jumo-ipc`)

```bash
cd /home/jumo/ai-predykcja && git pull --ff-only
umask 077
if [ -e .env ]; then echo "JUZ ISTNIEJE - nie nadpisuje"; else
  cp .env.example .env
  for v in POSTGRES_PASSWORD APP_WRITER_PASSWORD APP_READER_PASSWORD MQTT_COLLECTOR_PASSWORD MQTT_INGEST_PASSWORD GF_SECURITY_ADMIN_PASSWORD; do
    sed -i "s|^${v}=.*|${v}=$(openssl rand -hex 24)|" .env
  done
  chmod 600 .env
fi
```

`openssl rand -hex 24` daje 48 znaków alfanumerycznych (192 bity) bez znaków psujących adresy i powłokę.
Pętla jest w gałęzi `else`, więc istniejące hasła nigdy nie zostaną nadpisane. Potem napisz „`.env` gotowy”.

### Co sprawdzę bez czytania wartości

`stat -c '%a %U' .env` (oczekiwane `600 jumo`), `git check-ignore -v .env` (ignorowany),
`awk -F= '/PASSWORD=/{printf "%s %d\n",$1,length($2)}' .env` (nazwy i długości: 48 dla wygenerowanych,
bez wartości), brak pustych wymaganych zmiennych. Hasła nie trafią do repo, logów ani raportu.

## Testy pytest (bez sprzętu PLC)

Testy działają w kontenerach (Python 3.12), bo laptop i komputer nie mają gwarancji tej wersji
Pythona. `docker-compose.test.yml` (projekt `aip-test`): jednorazowy TimescaleDB w tmpfs (limit
512 MB), Mosquitto z losowymi hasłami testowymi generowanymi przez `conftest.py` (nie z `.env`),
kontener `pytest`. Uruchomienie: `docker compose -p aip-test -f docker-compose.test.yml run --rm pytest`,
potem `down -v` **tylko projektu `aip-test`**. Bez gniazda Dockera zamontowanego do kontenera (K2-c).

| Plik | Co sprawdza |
| --- | --- |
| `tests/config/test_devices_yaml.py` | struktura i walidacja `devices.yaml`; D1 (`zaklad1`, `linia1`); brak nakładania bloków; segmenty bez spacji |
| `tests/db/test_migrations.py` | migracje na pustej bazie; drugie uruchomienie niczego nie zmienia; zmiana zastosowanej migracji = błąd; wiersze `schema_migrations` zgodne z plikami |
| `tests/db/test_core_schema.py` | hypertable i kawałki 1 dzień; polityki kompresji (1 dzień) i retencji (90 dni) w `timescaledb_information.jobs`; `segmentby`; **`plc-01` z `kind = plc` jest akceptowany (U1)**; FK i `CHECK` odrzucają nieznane urządzenie, zły `source`, `NaN`; duplikat z `ON CONFLICT DO NOTHING`; po wymuszonej kompresji kawałka późny wiersz i duplikat nadal działają (zachowanie wersji przypiętej) |
| `tests/db/test_roles.py` | (U5) `app_reader`: `SELECT` działa, `INSERT` i `CREATE TABLE` odrzucone, `SHOW statement_timeout` = 10 s, zapytanie dłuższe niż limit przerwane (`pg_sleep`), tabela utworzona w późniejszej migracji jest czytelna (`DEFAULT PRIVILEGES`); `app_writer`: `INSERT` działa, `DROP`/`ALTER` odrzucone; zmiana hasła w środowisku i ponowny `migrate`: nowe hasło działa, stare nie |
| `tests/mqtt/test_broker_acl.py` | połączenie bez hasła odrzucone; `collector` publikuje, `ingest` odbiera; `collector` nie dostaje cudzych wiadomości; `ingest` nie może publikować; brak dostępu do `$SYS`; `allow_anonymous false` i `persistence true` w konfiguracji |

Test limitu czasu trwa ok. 10 s (oznaczony `slow`); pozostałe są krótkie.

## Kroki wykonania k2 i polecenia na komputerze

Wszystkie polecenia przez `ssh` w trybie powyżej; po każdym wynik (bez sekretów) do raportu.

1. **Odczyty przed:** `docker network ls`, podsieci istniejących sieci (`docker network inspect` z
   formatem podsieci), `docker images`, `df -h /`, `free -m`, `docker inspect -f '{{.Name}} {{.State.StartedAt}}'
   $(docker ps -q)` (punkt odniesienia smartWARE).
2. **Obrazy:** `docker pull` obrazów TimescaleDB, Mosquitto i Pythona (wersje zatwierdzone w K2-h/D9);
   zapis digestów (`docker image inspect`). Brak dostępu do rejestru = stop i pytanie.
3. **Kod:** pliki z listy, commit na `main`; na komputerze `git pull --ff-only`.
   `docker compose config --quiet` (walidacja bez wypisywania haseł; wymaga `.env`, więc dopiero po kroku 5).
4. **Testy:** uruchomienie z `docker-compose.test.yml`; wynik pytest do raportu; sprzątanie tylko `aip-test`.
5. **`.env`:** Grzegorz uruchamia polecenie z powyższej sekcji; ja sprawdzam uprawnienia i długości.
6. **Start:** `docker compose up -d --build`; `docker compose ps`; `docker compose logs --tail 30 migrate`
   (kod wyjścia 0); w `timescaledb` `\dt`, `\d+ measurements`, `\du`, `SHOW shared_buffers; SHOW max_connections;
   SHOW work_mem; SHOW statement_timeout` (jako `app_reader`); MQTT: odmowa bez hasła i obieg
   `collector` → `ingest` przez `docker compose exec mosquitto` z `sh -c` (hasła z zmiennych w kontenerze,
   nigdy wypisywane).
7. **Kontrola po:** `ss -ltn` (nowe tylko `127.0.0.1:1883`, 80/443 nadal smartWARE), `docker stats --no-stream`
   (nasze kontenery i smartWARE), `StartedAt` smartWARE bez zmian, `docker volume ls`, `df -h /`.
8. **Zrzuty (Grzegorz):** `docker compose ps` (03) i odmowa `mosquitto_sub` bez hasła (04); polecenia podam w raporcie.
9. **Raport** `e2-k2-report.md` i poprawki `docs/ops`; commit; stop.

### Poprawki `docs/ops/jumo-ipc-setup.md` z review k1 (dołączone do k2)

1. Pkt 2: nazwa kopii w zmiennej (`KOPIA=/home/jumo/docker-apt-source.list.bak-focal-$(date +%Y%m%d)`),
   `diff "$KOPIA" "$PLIK"` zamiast globu, który przy drugiej kopii dopasuje kilka plików.
2. Pkt 4: przed `printf >> ~/.ssh/config` dodać `mkdir -p ~/.ssh && chmod 700 ~/.ssh`.
3. Nowe sekcje: tworzenie `.env` (polecenie wyżej) i uruchamianie stosu (`docker compose up -d --build`,
   `ps`, `logs`, zakaz `down -v` bez zgody), bez wartości haseł.

## Przekazanie decyzji do tego planu

| Pozycja | Gdzie w planie |
| --- | --- |
| D1 | `config/devices.yaml` (`zaklad1/linia1`), test konfiguracji |
| D3 | konta `collector`/`ingest`, ACL, zmienne `MQTT_COLLECTOR_*`, `MQTT_INGEST_*`, test brokera |
| D4 | kontener `migrate`, `schema_migrations`, sumy kontrolne |
| D9 | przypięte obrazy i biblioteki, wersje i digesty w raporcie (tabela w sekcji niżej) |
| U1 | `kind = plc`, `plc-01` w teście `test_core_schema.py` |
| U3 | brak portu bazy; Mosquitto tylko `127.0.0.1:1883`; `ss -ltn` po starcie w raporcie (Grafana 3000 w k7) |
| U5 | role i hasła w `migrate`, `GRANT`/`DEFAULT PRIVILEGES`, `statement_timeout`, brak `CREATE`, testy ról |
| U6 | `NO_TS_TUNE=true` i jawne parametry; wynik `SHOW` w raporcie |
| U7 (częściowo) | bufor Mosquitto (`max_queued_*`) w limicie 64 MB; liczby wierszy/min w k5 |

### Wersje (do wypełnienia w raporcie; D9)

| Składnik | Plan |
| --- | --- |
| TimescaleDB / PostgreSQL | konkretny tag `X.Y.Z-pg16` i digest, najnowsza stabilna wersja dostępna w kroku 2 |
| Mosquitto | konkretny tag 2.0.x i digest |
| Python (obraz `migrate`, testy) | `3.12-slim` w konkretnym tagu i digest |
| psycopg, paho-mqtt, PyYAML, pytest | przypięte w `requirements.txt` |

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K2-a | Port Mosquitto na hoście | `127.0.0.1:1883`, nie w LAN | Review U3 dopuszcza brak portu lub lokalny; lokalny pozwala na testy i tunel SSH (np. MQTT Explorer) bez wystawiania brokera. Wystawienie w LAN dopiero przy zewnętrznym wydawcy, z osobnym kontem |
| K2-b | Healthcheck Mosquitto | kontrola portu (`nc -z`) plus test funkcjonalny w pytest | Healthcheck z logowaniem wymagałby trzeciego konta z dostępem do `$SYS`; kontrola portu mówi, że broker przyjmuje połączenia, a działanie ACL sprawdza test |
| K2-c | Testy integracyjne | osobny `docker-compose.test.yml` (projekt `aip-test`, tmpfs, kontener `pytest`), bez gniazda Dockera | Gniazdo daje kontenerowi władzę nad całym demonem, także nad smartWARE; osobny projekt ogranicza się do własnych zasobów |
| K2-d | Brak swap dla naszych kontenerów | `memswap_limit` = `mem_limit` | Przekroczenie limitu daje zabicie kontenera i wyraźny sygnał zamiast spowolnienia całego komputera przez wymianę (swap 2 GB jest wspólny ze smartWARE). Limity można korygować po pomiarze w k8 |
| K2-e | Limity roli `app_reader` | `statement_timeout = 10s`, `idle_in_transaction_session_timeout = 30s`, `default_transaction_read_only`, `CONNECTION LIMIT 10` | Rola jest wspólna dla Grafany i czatu (czat ma własny limit 5 s w `CHAT_SQL_TIMEOUT_MS`); 10 s starcza na zapytania do agregatów minutowych |
| K2-f | `config/devices.yaml` już w k2 | tak, z pełną strukturą | D1 ustala nazwy tematów; kontrakt zatwierdzamy raz, a collector (k3) i ingest (k4) tylko go czytają |
| K2-g | Podsieć Compose | jawna `/24` z zakresu 172.x, wybrana po sprawdzeniu istniejących sieci | Domyślny przydział mógłby zahaczyć o LAN lub sieci smartWARE |
| K2-h | PostgreSQL 16 | tak | Dojrzała i w pełni wspierana przez TimescaleDB; wersja 17 nie daje korzyści dla tego obciążenia, a zwiększa ryzyko. Wersję TimescaleDB wybieram po sprawdzeniu dostępnych tagów w kroku 2 |

## Ryzyka i założenia (bez potwierdzenia)

- Komputer ma dostęp do rejestru obrazów (smartWARE pochodzi z `registry.jumo.digital`, ale Docker Hub nie był
  sprawdzony). Brak dostępu = stop i pytanie, np. transfer obrazów przez `docker save`/`load`.
- Mosquitto w obrazie ma `mosquitto_passwd` i `nc` oraz uruchamia się jako root z późniejszym zejściem
  na użytkownika `mosquitto`; sprawdzam w kroku 6 i dostosowuję prawa wolumenu w `entrypoint.sh`.
- Zachowanie `INSERT … ON CONFLICT` na skompresowanych kawałkach zależy od wersji TimescaleDB; test to
  sprawdza dla wersji przypiętej.
- Kod trafia na `main` zanim testy przejdą na komputerze (testy wymagają Dockera na komputerze, a repo
  jest tam przez `git pull`). Poprawki idą kolejnymi commitami; raport wymienia wszystkie hashe. Alternatywą
  byłaby gałąź robocza; proponuję `main`, bo repo jest jednoosobowe, a zmiany nie dotykają działającego systemu.
- Hasła w `environment` kontenerów są widoczne dla użytkowników grupy `docker` (`jumo`) przez `docker inspect`;
  to akceptowalne na komputerze jednego użytkownika, ale dlatego raport ich nie wkleja. Docelowo (etap 7)
  rozważamy sekrety Dockera lub pliki.
- `.env` powstaje na komputerze, nie w repo; po utracie komputera hasła trzeba wygenerować od nowa (baza
  dostaje nowe hasła przy kolejnym `migrate`).
- Szacunki RAM i dysku z e2-k0-plan pozostają założeniami do zmierzenia w k8; w k2 raport poda wstępny
  `docker stats`.
- Zmiana limitów pamięci Postgresa po pomiarze będzie wymagała zmiany `shared_buffers` i `mem_limit` razem.

## Jak sprawdzę, że działa

1. `pytest` w projekcie `aip-test`: wszystkie testy zielone (podam liczbę i czas).
2. `docker compose ps`: `aip-mosquitto` i `aip-timescaledb` `healthy`; `aip-migrate` `Exited (0)`.
3. `\dt`, `\d+ measurements` (hypertable), `timescaledb_information.jobs` (kompresja, retencja).
4. `SHOW shared_buffers` = 384MB, `SHOW max_connections` = 30, `SHOW work_mem` = 4MB, `statement_timeout`
   `app_reader` = 10 s.
5. MQTT: odmowa bez hasła; obieg `collector` → `ingest`.
6. `ss -ltn`: nowe tylko `127.0.0.1:1883`; 80/443 bez zmian; `StartedAt` smartWARE bez zmian.
7. `docker stats --no-stream`: nasze kontenery poniżej limitów; smartWARE bez zmian.
8. Zrzuty 03 i 04 w `docs/images/etap2/`.

## Poza zakresem

Collector (k3), ingest (k4), agregaty ciągłe i widoki energii (k6), Grafana (k7), autostart po restarcie
komputera (k8), tabele `machine_states`, `anomaly_scores`, `events`, `tariffs`, `chat_log`, wystawienie
Mosquitto w LAN, zmiany w PLC i `docs/modbus-map.md`.
