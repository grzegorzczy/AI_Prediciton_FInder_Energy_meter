# e2-k2 review: Compose, Mosquitto, TimescaleDB, role, migracje

Recenzent: architekt (czat projektu), 23.11.2026. Podstawa: `docs/handoff/e2-k2-plan.md` (commit `9c8c08b`), `e2-k0-review.md`, `e2-k1-report-review.md`, `.env.example` (stan sprzed k2), dokumenty projektu 00, 04, 12.

## Werdykt: OK Z UWAGAMI

Plan jest zgodny z architekturą, zasadami twardymi i decyzjami D1, D3, D4, D9 oraz uwagami U1, U3, U5, U6. Mocne strony:
- role w `migrate` pod `pg_advisory_lock`, z sumami kontrolnymi migracji;
- `NO_TS_TUNE` i jawne parametry pamięci;
- Mosquitto tylko na `127.0.0.1`;
- testy w osobnym projekcie `aip-test`, bez gniazda Dockera;
- brak sekretów w raportach (`config --quiet`);
- prefiks `aip-` (bez kolizji ze smartWARE);
- `.env` z hasłami generowanymi na komputerze i nienadpisywanymi.

Uwagi K2-U1…K2-U7 do uwzględnienia w wykonaniu, bez nowego planu.

## Decyzje K2-a…K2-h – wszystkie zatwierdzone

| Id | Rozstrzygnięcie |
| --- | --- |
| K2-a | `127.0.0.1:1883` – zatwierdzone |
| K2-b | Healthcheck `nc -z` + test funkcjonalny w pytest – zatwierdzone (jeśli obraz nie ma `nc`, zamiennik w raporcie, bez dodatkowego konta MQTT) |
| K2-c | `docker-compose.test.yml`, projekt `aip-test`, tmpfs, bez gniazda Dockera – zatwierdzone |
| K2-d | `memswap_limit` = `mem_limit` – zatwierdzone |
| K2-e | Limity `app_reader` – zatwierdzone, z uwagą K2-U5 |
| K2-f | `config/devices.yaml` już w k2 – zatwierdzone |
| K2-g | Jawna podsieć `/24` – zatwierdzone, z uwagą K2-U4 |
| K2-h | PostgreSQL 16 – zatwierdzone |
| Kod na `main` przed testami na komputerze | zatwierdzone (repo jednoosobowe, raport wymienia hashe) |

## Uwagi

### K2-U1 – `POSTGRES_PASSWORD` działa tylko przy pierwszym utworzeniu bazy

Obraz ustawia hasło superużytkownika tylko przy inicjalizacji pustego wolumenu `aip_pgdata`. Hasła `app_*` `migrate` aktualizuje przy każdym uruchomieniu, ale `postgres` – nie. Skutek: jeśli `.env` zostanie zgubiony lub wygenerowany od nowa przy zachowanym wolumenie, `migrate` nie zaloguje się jako `postgres`. Do `docs/ops/jumo-ipc-setup.md` (sekcja `.env`):
- „nie generuj `.env` od nowa przy istniejącym wolumenie”;
- procedura odzyskania: `docker compose exec timescaledb psql -U postgres` przez gniazdo lokalne kontenera i `ALTER ROLE postgres PASSWORD …`, z hasłem przekazanym bez wypisywania. Sprawdzić w wykonaniu, czy obraz ma `local trust`, i wpisać wynik;
- zalecenie dla Grzegorza: kopia `.env` w menedżerze haseł. Nie w repo, nie w czacie.

`migrate.py` może przy okazji raz wyrównać hasło `postgres` z `.env` (`ALTER ROLE postgres PASSWORD`), gdy się zaloguje. Opcja do decyzji Claude Code, opisać w raporcie.

### K2-U2 – praca bez internetu (cel produktu)

Budowa i testy w k2 potrzebują Docker Hub i PyPI. Na demo to w porządku. Raport ma podać wszystkie źródła pobierania (obrazy z digestami, pakiety z wersjami), żeby w etapie 7 dało się zrobić instalację offline (`docker save`/`load`, wheelhouse). Krok 2 zaczyna się od sprawdzenia dostępu do Docker Hub (`docker pull` małego obrazu, np. przypiętego Pythona). Brak dostępu = stop, jak w planie.

### K2-U3 – zrzuty 03 i 04 jako tekst z konsoli

Grzegorz chce mniej ręcznego przesyłania zrzutów. Wyniki z konsoli (`docker compose ps`, odmowa `mosquitto_sub` bez hasła) Claude Code zbiera sam i wkleja do raportu jako bloki tekstu, bez sekretów. W dokumentacji Word pokażę je jako bloki kodu z podpisem „Rys./Wydruk N.”. Pliki `03-…png` i `04-…png` nie są wymagane. Zrzuty od Grzegorza zostają dla GUI (Grafana, GitHub, CODESYS) i testów fizycznych. Punkt 8 planu: „wydruki tekstowe w raporcie” zamiast „zrzuty Grzegorza”.

### K2-U4 – podsieć Compose

Przy wyborze `/24` wykluczyć:
- `192.168.0.0/24` (LAN);
- `172.17.0.0/16` (`docker0`);
- podsieci wszystkich istniejących sieci Dockera, w tym smartWARE (z kroku 1);
- zakresy domyślnej puli Dockera, z których przyszła sieć innego projektu mogłaby dostać adres. Wybrać np. `172.31.x.0/24` po sprawdzeniu.

Wybrana podsieć i lista sprawdzonych sieci trafiają do raportu i `docs/ops`.

### K2-U5 – `CONNECTION LIMIT 10` a pula Grafany (na k7)

Grafana domyślnie dopuszcza wiele połączeń do źródła danych. Przy limicie 10 na rolę w k7 ustawić w provisioningu źródła danych `maxOpenConns` ok. 5 i `maxIdleConns` ok. 2, żeby został zapas dla czatu i ręcznych zapytań. Zapisać jako zadanie k7 (nie zmienia k2).

### K2-U6 – kontrola `.env`

Polecenie `sed` przy braku klucza w `.env.example` nic nie zrobi, więc hasło zostanie puste. Kontrola z planu (`awk` z długościami) musi więc pokazać **dokładnie 6** zmiennych `*_PASSWORD` z długością 48 (POSTGRES, APP_WRITER, APP_READER, MQTT_COLLECTOR, MQTT_INGEST, GF_SECURITY_ADMIN) i żadnej pustej. Dodatkowo:
- `MQTT_COLLECTOR_USER=collector` i `MQTT_INGEST_USER=ingest` – niepuste;
- brak starych `MQTT_USER` / `MQTT_PASSWORD` w nowym `.env.example`.

`CLOUD_LLM_API_KEY` zostaje pusty (etap 6) i nie jest generowany.

### K2-U7 – drobne

- `GRANT SELECT ON ALL TABLES … TO app_reader` obejmie też `schema_migrations` – akceptowane (nie zawiera sekretów).
- Testy na komputerze działają równolegle z produkcyjnym stosem: szczytowo ok. 1,6 GB + 0,5 GB (test DB) + Mosquitto i pytest. Mieści się; raport podaje `free -m` w trakcie testów.
- W raporcie `docker stats` nie wklejamy nazw zmiennych środowiskowych ani `inspect`, zgodnie z planem.
- Polecenie `.env` z planu Grzegorz uruchamia w konsoli `jumo@jumo-ipc` (nie przez `ssh "…"` z cmd – cudzysłowy).

## Kontrola reszty planu

- Zasady twarde:
  - brak zapisu do PLC (k2 nie łączy się z PLC);
  - dane urządzeń tylko w `devices.yaml`;
  - sekrety tylko w `.env`;
  - `mem_limit` każdego kontenera, suma 1600 MB stale – ✔.
- Bezpieczeństwo:
  - `allow_anonymous false`;
  - ACL najmniejszych uprawnień;
  - baza bez portu;
  - `REVOKE CREATE` na `public`;
  - `app_reader` tylko do odczytu z limitem czasu;
  - smartWARE nieruszany, `down -v` tylko za zgodą – ✔.
- „Gotowe, gdy” k2 jest sprawdzalne poleceniami (`ps`, `SHOW`, `jobs`, pytest, `ss -ltn`, `StartedAt`) – ✔.
- U1 (`plc-01`, `kind = plc`) w schemacie i teście – ✔. U4 opisane – ✔. U7 (bufor Mosquitto) – ✔.

## Checklista Grzegorza po k2 (tylko to, czego Claude Code nie zrobi)

1. Uruchomić polecenie tworzące `.env` (po wypchnięciu nowego `.env.example`) i napisać „`.env` gotowy”.
2. Zachować kopię `.env` w menedżerze haseł (K2-U1).

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k2 wg planu i uwag, po kroku 3 (kod + nowy `.env.example` wypchnięte) zatrzymuje się i prosi Grzegorza o `.env`, potem kroki 4–9 → `e2-k2-report.md` → stop.
