# e2-k2 raport: Compose, Mosquitto, TimescaleDB, role, migracje
Status: DO PRZEGLĄDU

Wykonanie 23.11.2026 wg `e2-k2-plan.md` i uwag K2-U1…U7 z `e2-k2-review.md`. Polecenia na `jumo-ipc`
wykonywałem przez `ssh jumo@192.168.0.213` (Git Bash, `bash -s`), bez `sudo`, bez ruszania smartWARE,
demona Dockera ani `docker system prune`. `.env` na komputerze utworzył Grzegorz; jego wartości nigdy
nie były czytane ani wypisywane (kontrola tylko nazw i długości). Raport nie zawiera sekretów.

## Co zrobiono

Commity na `main` (wszystkie wypchnięte):

| Hash | Zawartość |
| --- | --- |
| `12694a2` | review k2 |
| `56574f4` | kod k2: Compose, Mosquitto, TimescaleDB, `migrate`, migracja 001, `devices.yaml`, testy, `.env.example` |
| `dfc908f` | `.claude/settings.json`: `deny` dla `Read(.env)` i `Read(**/.env)` (na prośbę Grzegorza) |
| `092acf3` | poprawka testów ról i brokera (patrz odstępstwa 1 i 2) |
| `bde4b45` | `migrate`: skrypt i migracje wbudowane w obraz z prawami odczytu (odstępstwo 3) |

Pliki: `docker-compose.yml`, `docker-compose.test.yml`, `.env.example`, `config/devices.yaml`,
`config/mosquitto/{mosquitto.conf,acl.conf,entrypoint.sh}`, `db/{Dockerfile,requirements.txt,migrate.py}`,
`db/migrations/001_core.sql`, `pytest.ini`, `tests/{Dockerfile,requirements.txt,conftest.py,run-tests.sh}`,
`tests/config/`, `tests/db/` (3 pliki), `tests/mqtt/`, `.claude/settings.json`, uzupełnienia w
`docs/ops/jumo-ipc-setup.md`. Nie powstał `db/init/00-roles.sh` (U5: role w `migrate`).

Stan na komputerze: `aip-mosquitto` i `aip-timescaledb` działają i są `healthy`; `aip-migrate` zakończył się
kodem 0. Klon repo: `bde4b45`.

## Wyniki testów

Polecenie na komputerze (projekt `aip-test`, dane w tmpfs): `sh tests/run-tests.sh </dev/null`.

- **Pierwsze uruchomienie:** 39 przeszło, 4 nie. Dwie porażki dotyczyły ról (zapis odrzucony przez
  `default_transaction_read_only`, zanim sprawdzono uprawnienia), dwie brokera (Mosquitto nie odrzuca subskrypcji,
  patrz odstępstwa 1 i 2). To były błędne założenia w testach, nie błędy systemu.
- **Po poprawkach (`092acf3`):** `44 passed in 69.74s`. Rozkład: konfiguracja 7, schemat rdzenia 12,
  migracje 7, role 10, broker 8. Test limitu czasu zapytania (`slow`, ok. 10 s) jest w tym biegu.
- Po testach nie zostały żadne kontenery, wolumeny ani sieci projektu `aip-test`.
- Test obrazu `migrate` w wersji produkcyjnej: pierwsze uruchomienie po budowie dało błąd uprawnień (odstępstwo 3);
  po poprawce `migrate` przeszedł (log niżej).

## Wydruki zamiast zrzutów 03 i 04 (K2-U3)

### `docker compose ps -a` (po poprawce)

```text
NAME              STATUS                        PORTS
aip-migrate       Exited (0) 1 second ago       
aip-mosquitto     Up About a minute (healthy)   127.0.0.1:1883->1883/tcp
aip-timescaledb   Up About a minute (healthy)   5432/tcp
```

Wersje obrazów: `eclipse-mosquitto:2.0.23@sha256:6a332cc7a8dbe011cbc076180cbb76b37c6f0f55809682ea08e7980ef0112ad9`,
`timescale/timescaledb:2.32.1-pg16@sha256:5d7a2f9d9d593315368338aa6054fda37d7707b4a12a912e30dcb7523385e2b4`.

### Log `migrate`

```text
INFO roles synchronized: app_writer, app_reader
INFO applied 001_core.sql
INFO done: 1 applied, 0 already applied
```

### Odmowa `mosquitto_sub` bez hasła i ze złym hasłem

```text
$ mosquitto_sub -h localhost -t '#' -C 1 -W 3
Connection error: Connection Refused: not authorised.
exit code: 5
$ mosquitto_sub -h localhost -u collector -P <zle-haslo> -t '#' -C 1 -W 3
Connection error: Connection Refused: not authorised.
exit code: 5
```

### Obieg `collector` → `ingest` i brak prawa publikacji dla `ingest`

```text
ingest otrzymal:
zaklad1/linia1/finder_7m24_1/voltage {"ts":"2026-11-23T16:40:00.000Z","value":240.4,"unit":"V","source":"real"}
ingest publish na a/b/c/d (MQTT v5): Warning: Publish 1 failed: Not authorized.
```

Hasła do tych poleceń pochodziły ze zmiennych środowiskowych w kontenerze; nie były wypisywane.

## Baza: wyniki z komputera

`\dt`: `devices`, `measurements`, `schema_migrations` (właściciel `postgres`). `measurements` to hypertable,
kawałki **1 dzień**, `compression_enabled = t`. Polityki (`timescaledb_information.jobs`):

```text
 proc_name          | schedule_interval | config
 policy_compression | 12:00:00          | {"hypertable_id": 1, "compress_after": "1 day"}
 policy_retention   | 1 day             | {"drop_after": "90 days", "hypertable_id": 1}
```

Kompresja: `segmentby` = `device_id`, `metric`; `orderby` = `time DESC`. Indeksy: `UNIQUE (device_id, metric, time)`
i `measurements_time_idx`. Ograniczenia: `metric ~ '^[a-z0-9_]+$'`, `source IN ('real','sim')`, `value` odrzuca NaN i
nieskończoność, FK do `devices`.

### `SHOW` (U6)

| Parametr | Wartość |
| --- | --- |
| `shared_buffers` | 384MB |
| `max_connections` | 30 |
| `work_mem` | 4MB |
| `effective_cache_size` | 768MB |
| `TimeZone` | UTC |
| `timescaledb.telemetry_level` | off |

### Role i uprawnienia (U5)

```text
 Role name  | Attributes
 app_reader | No inheritance, 10 connections
 app_writer | No inheritance, 10 connections
 postgres   | Superuser, Create role, Create DB, Replication, Bypass RLS
```

Ustawienia `app_reader` (`pg_db_role_setting`): `statement_timeout=10s`, `idle_in_transaction_session_timeout=30s`,
`default_transaction_read_only=on`. **Wartość `statement_timeout` = 10 s.**

```text
 reader_select | reader_insert | writer_insert | writer_delete | reader_create | public_connect
 t             | f             | t             | f             | f             | f
```

`schema_migrations`: wersja 1, `001_core.sql`, suma kontrolna `653c7f510a0a…`.

### `pg_hba` w obrazie (K2-U1)

Obraz ma `local all all trust` (oraz `host … 127.0.0.1 trust` tylko w obrębie kontenera) i `host all all all scram-sha-256`
dla sieci. Procedura odzyskania hasła `postgres` przez gniazdo lokalne (`docker compose exec timescaledb psql -U postgres`)
jest więc możliwa; opisana w `docs/ops/jumo-ipc-setup.md`, sekcja 6. Nie była wykonywana na produkcyjnej bazie.

## Porty i izolacja (U3)

`ss -ltn` po starcie: nowe tylko `127.0.0.1:1883`; bez zmian `0.0.0.0:80`, `:443` (smartWARE), `:22`,
`127.0.0.1:631`, `127.0.0.53:53`. **Baza bez portu na hoście**, 3000 wolny (Grafana w k7). `StartedAt` wszystkich 7 kontenerów
smartWARE identyczne z punktem odniesienia z k1 (`2026-11-23T08:00:24.2…Z` itd.): nie zostały zrestartowane.

Sieć `aip_backend` `172.31.50.0/24` (K2-U4). Sprawdzone przed wyborem: zajęte `172.17.0.0/16` (docker0), `172.19.0.0/16`
(`upgrade_pg_default`, pochodzenie nieznane), `172.20.0.0/16` (`smartware_4527022_default`); LAN `192.168.0.0/24`. Wolumeny:
`aip_pgdata`, `aip_mosquitto_data`.

## Odstępstwa od planu i dlaczego

1. **Mosquitto nie odrzuca subskrypcji; filtruje dostarczanie.** Wbudowany `acl_file` zawsze przyznaje `SUBSCRIBE`, a prawo odczytu
   sprawdza przy dostarczaniu wiadomości. Test „collector nie może subskrybować” (z planu) zamieniłem na test zachowania:
   `collector` subskrybuje `+/+/+/+` i `#`, publikuje, a **nie dostaje żadnej wiadomości**, podczas gdy `ingest` dostaje.
   Test „`$SYS` niedostępne” zamieniłem na kontrolę konfiguracji (`sys_interval 0`) i szablonu ACL (dokładnie 4 reguły).
   Gwarancja bezpieczeństwa jest ta sama, tylko mechanizm inny, niż napisałem w planie.
2. **`default_transaction_read_only` nie jest granicą bezpieczeństwa.** Rola może sama przestawić to ustawienie
   (`SET default_transaction_read_only = off`). Granicą są uprawnienia: po wyłączeniu read-only `INSERT`, `UPDATE`,
   `DELETE`, `CREATE TABLE` i `CREATE SCHEMA` są nadal odrzucane (`InsufficientPrivilege`). Test sprawdza obie warstwy osobno.
   Wniosek dla czatu (etap 6): nie polegać na tym ustawieniu, tylko na braku uprawnień.
3. **Migracje i skrypt wbudowane w obraz `migrate` zamiast montowania katalogu.** Plan zakładał `./db/migrations:/migrations:ro`.
   Pliki w klonie na komputerze miały prawa 600 (katalogi 700), bo `git pull` poszedł w powłoce z `umask 077`; użytkownik
   `migrate` (uid 10001) nie mógł ich czytać (`Permission denied`, kod 2). Teraz `Dockerfile` kopiuje pliki i ustawia
   `chmod -R a+rX`, więc wynik nie zależy od uprawnień na hoście. Skutek: po `git pull` nowe migracje stosuje
   `docker compose up -d --build` (opisane w `docs/ops`). Sumy kontrolne migracji i test historii bez zmian.
4. **`</dev/null` i `-T` przy `docker compose run/exec` w skryptach `bash -s`:** polecenie zjadało resztę skryptu ze standardowego
   wejścia. `tests/run-tests.sh` używa `run --rm -T`. Dopisane do `docs/ops`.
5. **Dodatki spoza listy planu:** `tests/run-tests.sh` (uruchomienie testów z losowymi hasłami `TEST_*` i sprzątaniem tylko
   `aip-test`), znacznik `-- migrate: next` do dzielenia migracji bez transakcji na instrukcje (potrzebne w k6 dla agregatów;
   założenie, którego nie sprawdzałem osobno: wieloinstrukcyjny `execute` w `psycopg` działa jak jedna niejawna transakcja;
test przechodzi z `CREATE INDEX CONCURRENTLY`, które w transakcji by się nie udało), `.claude/settings.json` (prośba Grzegorza).
6. **Wersje:** wybrałem najnowsze stabilne z list tagów Docker Hub z 23.11.2026: TimescaleDB `2.32.1-pg16` (tag zaktualizowany 19.11.2026, najmłodszy minor na liście;
   starsze `2.31.2` i `2.30.3` są dostępne, gdybyśmy woleli bardziej sprawdzoną), Mosquitto `2.0.23`,
   Python `3.12.16-slim-trixie`. Test kompresji i polityk działa na tej wersji (komendy `add_compression_policy` i
   `ALTER TABLE … SET (timescaledb.compress …)` nadal działają w 2.32.1).
7. **K2-U1, opcja wyrównania hasła `postgres` w `migrate.py`: nie wdrożyłem.** Skoro `migrate` loguje się hasłem z `.env`,
   udane logowanie dowodzi zgodności, więc `ALTER ROLE postgres PASSWORD` byłoby bezczynne. Zamiast tego `migrate` przy
   niezgodności zgłasza czytelny błąd z odesłaniem do `docs/ops` (test `test_wrong_superuser_password_fails_fast_with_hint`).
8. **`.claude/settings.json` `deny Read(.env)`** obejmuje narzędzie Read. Nie blokuje innych dróg (np. `cat .env` w powłoce
   lub wyszukiwanie w plikach). Nie sięgam po te drogi; jeśli chcesz twardszej blokady, mogę dodać reguły dla `Bash` i `Grep`.

## Zmierzone zasoby

Stan spoczynkowy (po starcie, bez obciążenia danymi; realne obciążenie dopiero od k5):

```text
NAME              MEM USAGE / LIMIT     MEM %     CPU %
aip-timescaledb   46.6MiB / 1.5GiB      3.03%     0.04%
aip-mosquitto     1.453MiB / 64MiB      2.27%     0.04%
dataview          92.55MiB / 15.38GiB   0.59%     0.00%
datareportengine  108.5MiB / 15.38GiB   0.69%     0.00%
datareport        99.11MiB / 15.38GiB   0.63%     0.00%
datastore         144.8MiB / 15.38GiB   0.92%     0.00%
reverse-proxy     9.652MiB / 15.38GiB   0.06%     3.85%
mqtt              6.609MiB / 15.38GiB   0.04%     0.04%
postgres-server   57.04MiB / 15.38GiB   0.36%     0.00%
```

`free -m` po starcie: used 1407 MB, available 13 779 MB, swap 0 użyty. smartWARE razem ok. 517 MiB (bez zmian od k1).

**W trakcie testów (K2-U7)**, próbka po 45 s: `free -m` used 1461 MB, available 13 655 MB; kontenery testowe:
`aip-test-db-1` 114,7 MiB / 512 MiB, `aip-test-pytest-run` 56,9 MiB / 256 MiB, `aip-test-mosquitto-1` 1,2 MiB / 64 MiB.
Testy mieszczą się z dużym zapasem obok stosu.

Dysk `/`: 938 GB, zajęte 20 GB (3%), wolne 871 GB (przed k2 było 18 GB). Obrazy: TimescaleDB ok. 2,0 GB, `migrate` 132 MB,
`aip-pytest` 149 MB, Mosquitto 14 MB, Python 119 MB.

**Limity sumaryczne** `aip-` stale: 1600 MB (+64 MB chwilowo `migrate`), bez zmian względem planu. Zmierzone zużycie pod obciążeniem
poda k5 (po zapisie realnych danych) i k8 (po dobie pracy).

## Checklista dla Grzegorza

Wszystko poza jedną rzeczą zostało sprawdzone przeze mnie:

1. **`.env` na komputerze:** zrobione (6 haseł po 48 znaków, wszystkie różne, `600 jumo`, ignorowany przez git).
2. **Kopia `.env` w menedżerze haseł (K2-U1):** do potwierdzenia przez Ciebie. Nie w repo, nie w czacie.

## Źródła pobierania (K2-U2)

Lista obrazów z digestami i pakietów z wersjami jest w `docs/ops/jumo-ipc-setup.md` (sekcja „Źródła pobierania”),
razem z pełną listą zależności (`pip freeze`) obrazów `migrate` i testowego. Docker Hub i PyPI były dostępne z komputera
(`docker pull` małego obrazu Pythona był pierwszym krokiem k2).

## Otwarte kwestie

- **K2-U5 (zadanie k7):** w provisioningu źródła danych Grafany ustawić `maxOpenConns` ok. 5 i `maxIdleConns` ok. 2
  (limit roli `app_reader` to 10 połączeń).
- **Sieć `upgrade_pg_default`** (`172.19.0.0/16`) i stare obrazy smartWARE (`13.5.0.2`, `2.5.0.x`) wyglądają na pozostałości po
  aktualizacji; nie są nasze i ich nie ruszamy.
- **Restart komputera** (autostart całego stosu bez ręcznego `docker compose up`) sprawdza k8; `migrate` po restarcie się nie
  uruchamia (`restart: "no"`), a ingest w k4 czeka na tabele sam.
- **TimescaleDB 2.32.1** to najnowszy minor na liście tagów z 23.11.2026; jeśli wolisz starszą stabilną (`2.31.2-pg16`), zmiana to jedna linia
  digestu w `docker-compose.yml` i `docker-compose.test.yml` plus ponowny bieg testów.
- **Hasła w `environment` kontenerów** są widoczne dla grupy `docker` (`docker inspect`); akceptowalne na komputerze jednego
  użytkownika, do przeglądu przy etapie 7 (sekrety Dockera lub pliki).
- **Procedura odzyskania hasła `postgres`** opisana, ale niewykonana na produkcyjnej bazie.
