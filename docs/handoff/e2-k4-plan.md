# e2-k4 plan: ingest (MQTT → walidacja → paczki → baza)
Status: DO PRZEGLĄDU

Podstawa: `e2-k3-report-review.md` (sekcja „Następny krok”), `e2-k0-review.md` (U1, U4, U7), `e2-k2-report-review.md` (R2-U2),
`db/migrations/001_core.sql`, `docs/data-model.md`, `config/devices.yaml`, `config/mosquitto/*`, `.claude/agents/data-platform.md`,
`CLAUDE.md`. Krok nie łączy się z PLC. Collector zostaje za profilem `live` do k5, więc w k4 do prawdziwej bazy nie trafi żaden pomiar.

## Cel kroku

Usługa `ingest` subskrybuje `+/+/+/+` w Mosquitto (konto `ingest`, tylko odczyt), waliduje każdą wiadomość, zapisuje poprawne w paczkach do
`measurements` (rola `app_writer`) i synchronizuje tabelę `devices` z `config/devices.yaml`. Nieznane urządzenie i wadliwe wiadomości
trafiają do logu, nie do bazy. Wiadomość jest potwierdzana brokerowi dopiero po zapisie w bazie, więc przerwa ingestu, bazy lub
brokera nie gubi danych w granicach buforów, a ponowne dostarczenie nie tworzy duplikatów.

**Sprawdzalny wynik:** pytest zielony na komputerze (walidacja, paczkowanie, synchronizacja `devices`, tor MQTT → baza na prawdziwym
brokerze i bazie, odporność na awarie); obraz `ingest` zbudowany, kontener `healthy` przy stosie `aip-`; w prawdziwej bazie `devices`
zawiera `plc-01` i `finder_7m24_1`, a `measurements` pozostaje puste (kontrola przed k5).

## Tryb wykonania na komputerze

Jak w k1–k3: `ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null` przy `docker compose run/exec`), **bez `sudo`**, bez ruszania
smartWARE, demona Dockera i `docker system prune`; `docker compose down -v` na `ai-predykcja` tylko za zgodą. Nie wypisuję `.env` (kontrola
tylko nazw, długości i praw); raport bez sekretów (nie wklejam `docker compose config`, `docker inspect`, `env`). Po każdym `git pull` kontrola
praw wg `docs/ops`.

## Co powstaje / zmienia się (pliki)

```
services/ingest/Dockerfile, requirements.txt
services/ingest/src/ingest/__init__.py
  main.py        wiązanie, pętla, sygnały, podsumowanie co 60 s
  config.py      minimalny parser config/devices.yaml (site, line, PLC, urządzenia: id, nazwa, kind, source, meta)
  validate.py    walidacja tematu i ładunku -> wiersz albo odrzucenie z powodem
  store.py       połączenie z bazą, synchronizacja devices, zapis paczek, klasyfikacja błędów
  pipeline.py    paczkowanie, zapis, potwierdzenia, ponawianie (bez zależności od paho)
  mqtt_in.py     paho-mqtt 2.x: sesja trwała, QoS 1, ręczne potwierdzanie
  health.py      plik znacznika żywotności (jak w collectorze)
docker-compose.yml           usługa ingest (bez profilu: startuje ze stosem)
docker-compose.test.yml      PYTHONPATH do kodu ingestu
tests/ingest/conftest.py, test_validate.py, test_pipeline.py, test_devices_sync.py, test_e2e.py,
  test_resilience.py, test_no_hardcoding.py, test_compose_service.py
docs/status-codes.md         jedno zdanie o rozgrzewce collectora (uwaga z review k3)
docs/handoff/e2-k4-report.md
```

## Zakres ingestu

### Przepływ i gwarancje

1. Start: wczytanie `devices.yaml` (błąd = kod wyjścia 2), potem **czekanie na bazę i schemat** (U4), synchronizacja `devices`, dopiero potem
   start MQTT. Dzięki temu pierwsza wiadomość nigdy nie trafia na brak wiersza w `devices`.
2. MQTT: paho 2.x, **MQTT v3.1.1** z `clean_session=False`, stałym `client_id` (`aip-ingest`), `manual_ack=True`, subskrypcja `+/+/+/+` QoS 1.
   Sesja trwała: wiadomości z czasu przerwy ingestu czekają w Mosquitto (limit niżej).
3. Wiadomość z callbacku paho trafia do ograniczonej kolejki. Pętla główna waliduje i zbiera paczkę. **Potwierdzenie (`ack`) idzie dopiero po
   udanym zapisie paczki w bazie**: nie ma utraty przy awarii ingestu między odbiorem a zapisem (broker dostarczy ponownie), a duplikaty
   usuwa `ON CONFLICT DO NOTHING`. Wadliwe wiadomości są potwierdzane od razu po zapisaniu powodu w liczniku i logu, żeby nie blokowały sesji.
4. Paczka zamyka się po **100 wiadomościach lub 1 s** (limit 100 odpowiada `max_inflight_messages` w Mosquitto: przy ręcznym potwierdzaniu
   broker nie wyśle więcej niż 100 niepotwierdzonych, więc większa paczka nigdy by się nie zapełniła). Zapis to jedno zapytanie
   `INSERT … SELECT … FROM unnest(tablice) … ON CONFLICT DO NOTHING`, liczba nowych wierszy z `rowcount` (reszta to duplikaty).
5. Zapis nie powiódł się: paczka zostaje w pamięci bez potwierdzenia, ponawianie z cofaniem 1 s → 10 s, pętla żyje (znacznik żywotności),
   a broker po osiągnięciu 100 niepotwierdzonych sam przestaje wysyłać i kolejkuje resztę w sesji.

### Walidacja (zasada: wadliwe do logu, nie do bazy)

Odrzucenie z powodem (kod powodu w liczniku i logu), w tej kolejności:

| Powód | Warunek |
| --- | --- |
| `topic` | temat nie ma dokładnie 4 poziomów albo segment ma niedozwolone znaki |
| `unknown_device` | `device_id` nie ma w `devices.yaml` (lub jest wyłączony) |
| `site_line` | `zaklad`/`linia` w temacie różne od `site`/`line` z configu |
| `metric` | nazwa metryki poza `^[a-z0-9_]+$` lub dłuższa niż 64 znaki |
| `payload` | pusty, większy niż 1 KB, nie jest JSON-em, nie jest obiektem, brak któregoś z `ts`, `value`, `unit`, `source` |
| `ts` | nie jest tekstem ISO 8601 **ze strefą czasową** (znaczniki bez strefy odrzucane), albo spoza okna (niżej) |
| `value` | nie jest liczbą (tekst, `null`, wartość logiczna), albo nie jest skończona (`NaN`, nieskończoność, także `1e400`) |
| `unit` | nie jest tekstem lub dłuższy niż 16 znaków (pusty tekst jest poprawny: współczynnik mocy, statusy) |
| `source` | spoza `real`/`sim` albo **różne od `source` urządzenia** z `devices.yaml` |

Okno czasu `ts`: nie dalej niż **5 minut w przyszłość** (dopuszczalny dryf zegarów) i nie starsze niż **400 dni** (ochrona przed zerowym
czasem Uniksa, ale z zapasem na jednorazowe wypełnienie historii symulatora w etapie 3); wartości w zmiennych środowiskowych
`INGEST_MAX_FUTURE_S` i `INGEST_MAX_PAST_DAYS`. Dodatkowe klucze w ładunku są ignorowane. Flaga `retain` jest ignorowana.
Metryki nieznane w configu są akceptowane dla znanych urządzeń (nowa metryka nie wymaga zmiany schematu): pierwsze pojawienie się
nowej pary urządzenie/metryka jest logowane raz na poziomie INFO.

### Rejestr odrzuceń bez zalewania logu

Pierwsze odrzucenie dla pary (powód, urządzenie lub temat) jest logowane na poziomie WARNING z treścią tematu i skróconym ładunkiem
(ładunki w tym systemie nie zawierają sekretów), kolejne tylko się liczą. Co 60 s pętla zapisuje jedno podsumowanie INFO: odebrane,
zapisane, duplikaty, odrzucone wg powodów, średni i maksymalny czas zapisu paczki, liczba niepotwierdzonych. Test: 1000 wadliwych wiadomości
daje najwyżej kilka wpisów logu.

### Synchronizacja `devices` (U1)

Przy starcie: `INSERT … ON CONFLICT (device_id) DO UPDATE` dla każdego wpisu configu, **w tym `plc-01` jako `kind = plc`**, `source` z
`devices.yaml` (PLC: `plc.source`); następnie `UPDATE devices SET enabled = FALSE` dla wierszy, których nie ma w configu. Przywrócony wpis
dostaje z powrotem `enabled = TRUE`. `meta` (JSONB) zawiera tylko atrybuty nieposiadające sekretów: dla licznika `profile`, `block_base`,
`serial`; dla PLC `map_version`. Adres IP PLC **nie** trafia do bazy. Synchronizacja tylko przy starcie (zmiana configu = restart ingestu i
collectora; przeładowanie sygnałem odkładam, K4-f). Rola `app_writer` ma do tego `INSERT` i `UPDATE` na `devices` (k2).

### Odporność na awarie (U4, R2-U2)

| Sytuacja | Zachowanie |
| --- | --- |
| baza niedostępna lub nie odpowiada (po restarcie komputera Docker startuje kontenery bez kolejności) | ponawianie z cofaniem, jeden wpis logu na zmianę stanu, pętla żyje, niepotwierdzone wiadomości zostają u brokera; **ingest się nie kończy** |
| brak tabel (`migrate` jeszcze nie przebiegł) lub brak roli | j.w.; komunikat podpowiada `migrate` i `APP_WRITER_PASSWORD` przy błędzie uwierzytelnienia |
| brak wiersza w `devices` (FK) dla znanego urządzenia | ponowna synchronizacja i jedna próba; jeśli nadal błąd, izolacja po jednym wierszu |
| błąd ograniczenia tylko dla części paczki | zapis po jednym wierszu: dobre trafiają do bazy, złe są odrzucone z powodem `db_constraint` i potwierdzone |
| broker niedostępny | paho łączy się ponownie sam (cofanie 1–30 s), log przy zmianie stanu; niepotwierdzone wiadomości wracają po powrocie |
| awaria lub restart ingestu | niepotwierdzone wiadomości dostarczy broker ponownie (sesja trwała); duplikaty pomija `ON CONFLICT` |
| wiadomość-trucizna (np. zły JSON) | potwierdzona i odrzucona z powodem, nie blokuje kolejnych |
| zły plik konfiguracji przy starcie | komunikat i kod 2 (restart przez Docker) |

**Utrata danych przy długiej przerwie ingestu lub bazy (opis wprost, R2-U2).** Po zapełnieniu kolejki sesji Mosquitto (`max_queued_messages`
50 000, `max_queued_bytes` 20 MB; przy ok. 13 wiadomościach na sekundę wiąże liczba wiadomości, czyli ok. 64 minuty) broker odrzuca **najnowsze**
wiadomości, a zostają najstarsze, więc luka w danych pojawia się **na końcu przerwy**. Collector ma własny bufor (20 000 wiadomości, ok. 25 minut), w którym
odrzuca **najstarsze**, ale działa on tylko przy niedostępnym brokerze. Dla demo akceptowalne; test e2e potwierdza brak utraty w granicach buforów.

### Połączenie z bazą i zasoby

Jedno połączenie jako `app_writer` (limit roli 10 połączeń), `application_name=aip-ingest`, `connect_timeout` 5 s, `statement_timeout` 30 s.
Hasło wyłącznie ze zmiennej środowiskowej (`APP_WRITER_PASSWORD` mapowane na `DB_PASSWORD`), nigdy w logu; błędy bazy logowane bez treści zapytania.
Usługa `aip-ingest`: `mem_limit` i `memswap_limit` **128 MB**, bez portów, `restart: unless-stopped`, `depends_on` na `mosquitto` i
`timescaledb` (`service_healthy`, kolejność przy `compose up`; po restarcie komputera ingest sam czeka), konfiguracja `:ro`, utwardzenie jak collector
(nie-root uid 10003, `read_only` z `tmpfs: /tmp`, `cap_drop: [ALL]`, `no-new-privileges`), healthcheck „pętla żyje” (`python -m ingest.health`).
**Bez profilu:** ingest startuje razem ze stosem. Suma limitów `aip-` po k4: 1600 (stos) + 128 (collector, gdy aktywny) + 128 = **1856 MB**.

## Testy pytest bez sprzętu

Jak w k3: kod ingestu działa w procesie testu (kontener `pytest` dostaje `services/ingest/src` w `PYTHONPATH`), prawdziwy Mosquitto i prawdziwa
baza z projektu `aip-test`; testy jednostkowe bez infrastruktury.

| Plik | Co sprawdza |
| --- | --- |
| `test_validate.py` | każdy powód z tabeli (w tym granice: +4 min dozwolone, +6 min odrzucone; bez strefy; `NaN`, `Infinity`, `1e400`; wartość logiczna i tekst; `source` zgodny/niezgodny z urządzeniem; temat 3 i 5 poziomów; zły `site`/`line`; metryka z wielkimi literami; ładunek za duży; `retain` ignorowane; dodatkowe klucze ignorowane) oraz poprawne wiadomości z `Z` i z przesunięciem strefy, z zachowaniem milisekund |
| `test_pipeline.py` | paczka po 100 wiadomościach lub 1 s; **potwierdzenie dopiero po zapisie**, brak potwierdzenia przy błędzie bazy i ponawianie z cofaniem; wadliwe potwierdzane od razu; izolacja po jednym wierszu przy błędzie ograniczenia; ponowna synchronizacja przy FK; liczniki zapisane i duplikaty; log odrzuceń bez zalewania (1000 wadliwych → kilka wpisów) |
| `test_devices_sync.py` | `devices` po synchronizacji: `plc-01` z `kind = plc`, licznik z `meta`; ponowna synchronizacja nic nie zmienia; wpis usunięty z configu dostaje `enabled = FALSE`, przywrócony `TRUE`; adres IP nie trafia do bazy |
| `test_e2e.py` | wiadomości z kontem `collector` przez prawdziwy broker → wiersze w `measurements` z poprawnym czasem (ms), wartością, jednostką i `source`; **`link_status` od `plc-01` trafia do bazy (U1)**; duplikat daje jeden wiersz; nieznane urządzenie, niezgodne `source`, zły ładunek i zły `ts` nie dają wierszy; rola zapisu to `app_writer`; przepustowość serii kilku tysięcy wiadomości (do raportu) |
| `test_resilience.py` | **ingest wystartowany przed bazą i przed `migrate` (U4)**: nie kończy się, nic nie traci, po `migrate` zapisuje wszystko; wiadomości opublikowane w czasie przerwy ingestu (sesja trwała) trafiają do bazy po restarcie; „awaria” między odbiorem a zapisem (bez potwierdzenia) → ponowne dostarczenie i dokładnie jeden wiersz; baza niedostępna → brak potwierdzeń i wznowienie bez utraty; znacznik żywotności odświeżany także przy niedostępnej bazie |
| `test_no_hardcoding.py` | w źródłach ingestu brak adresów IP, numerów seryjnych, identyfikatorów urządzeń, `zaklad1`, `linia1` i haseł; brak `DELETE`, `DROP`, `TRUNCATE` w SQL (rola i kod zapisują tylko dane) |
| `test_compose_service.py` | utwardzenie, limity 128 MB, brak profilu, brak portów, `config/devices.yaml:ro`, konto MQTT tylko `ingest`, brak zmiennych collectora, hasło bazy tylko z `APP_WRITER_PASSWORD` |

## Kroki wykonania k4

1. `docs/status-codes.md`: jedno zdanie, że w cyklu rozgrzewki (ok. 1 s po połączeniu collectora) `link_status` nie jest publikowany (uwaga z review k3).
2. Kod ingestu i testy na laptopie (testy jednostkowe lokalnie, `py_compile`), commit na `main`; poprawki kolejnymi commitami, raport wymienia hashe.
3. Na komputerze: `git pull --ff-only`, kontrola praw, `sh tests/run-tests.sh </dev/null` (cały zestaw k2–k4); pomiar `free -m` w trakcie testów.
4. Budowa obrazu, `docker compose up -d --build` (startuje `ingest`; collector zostaje za profilem): `docker compose ps -a`, logi ingestu (synchronizacja,
   subskrypcja), `docker stats --no-stream`.
5. Kontrola w prawdziwej bazie: `devices` zawiera dokładnie `plc-01` (plc) i `finder_7m24_1` (energy_meter) z `enabled = t`; `measurements` ma **0 wierszy**.
   Dymek bez zapisu do `measurements`: wiadomość opublikowana na nieznane urządzenie (konto `collector` z kontenera Mosquitto, hasło ze zmiennej środowiskowej,
   nie wypisywane) jest odrzucona i widoczna w podsumowaniu ingestu; po nim `measurements` nadal puste.
6. `ss -ltn` bez zmian (ingest bez portów), `StartedAt` smartWARE bez zmian.
7. Raport `e2-k4-report.md`; commit; stop.

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K4-a | Parser `devices.yaml` | własny, minimalny, w ingeście (bez wspólnej biblioteki z collectorem) | Obrazy usług są niezależne; ingest nie potrzebuje układu rejestrów. Cena to niewielkie powielenie kodu wczytywania; zgodność obu z jednym plikiem pilnują testy |
| K4-b | Gwarancje dostarczania | ręczne potwierdzanie po zapisie, MQTT v3.1.1 z sesją trwałą, stały `client_id`, paczka do 100 wiadomości lub 1 s | Przerwa lub awaria ingestu nie gubi danych w granicach bufora, a powtórzenia usuwa `ON CONFLICT`; limit 100 wynika z `max_inflight_messages` brokera |
| K4-c | Okno czasu `ts` | przyszłość do 5 min, przeszłość do 400 dni, wartości w zmiennych środowiskowych | Ochrona przed błędnym zegarem i znacznikiem zerowym przy zachowaniu miejsca na wypełnienie historii symulatora (etap 3); retencja 90 dni sama usunie najstarsze |
| K4-d | Nieznane metryki znanych urządzeń | akceptować, nowe pary logować raz | „Nowa metryka nie wymaga zmiany schematu” (`data-model.md`); literówka w nazwie jest widoczna w logu, a nie blokuje danych |
| K4-e | Odrzucenia | potwierdzać od razu, liczyć wg powodu, log pierwszego wystąpienia i podsumowanie co 60 s | Wadliwa wiadomość nie może blokować sesji ani zalewać logu |
| K4-f | Przeładowanie configu | tylko restart (synchronizacja `devices` przy starcie), bez obsługi sygnału | Zmiany `devices.yaml` są rzadkie i i tak wymagają restartu collectora; prostsze i testowalne. Do rozważenia w etapie 7 |
| K4-g | Start w prawdziwym stosie | ingest startuje ze stosem (bez profilu), dymek bez zapisu do `measurements` | Weryfikuje synchronizację i połączenia na komputerze, a pusta tabela `measurements` zostaje czysta do liczenia wierszy w k5 |
| K4-h | Zasoby i utwardzenie | 128 MB, nie-root, `read_only`, `cap_drop: ALL`, `no-new-privileges` | Jak collector (zatwierdzone w k3); ingest nie potrzebuje niczego poza siecią i `/tmp` |
| K4-i | Zdrowie kontenera | „pętla żyje”, a nie „baza i broker działają” | Niedostępna baza to stan do zgłoszenia (log), nie powód do restartu kontenera (U4); inaczej Docker restartowałby ingest przy każdej przerwie bazy |
| K4-j | Jedno połączenie z bazą | tak, `statement_timeout` 30 s | Limit 10 połączeń na rolę jest wspólny z analityką (etap 4); przy 13 wiadomościach na sekundę jedno połączenie z paczkami wystarcza z dużym zapasem |

## Przekazanie decyzji do tego planu

| Pozycja | Gdzie w planie |
| --- | --- |
| U1 | `plc-01` z `kind = plc` w synchronizacji `devices`; test e2e „`link_status` od `plc-01` trafia do bazy” |
| U4 | czekanie na bazę i schemat, brak zakończenia przy braku zależności, test ingestu wystartowanego przed `migrate`, zdrowie „pętla żyje” |
| U7 | bufor Mosquitto: 50 000 wiadomości / 20 MB, ok. 64 minuty przy 13 na sekundę; wzór wierszy: 13 na sekundę = 780 na minutę |
| R2-U2 | opis wprost: Mosquitto odrzuca najnowsze (luka na końcu przerwy), collector najstarsze; test braku utraty w granicach buforów |
| walidacja z review k3 | `source` zgodne z `devices.source`, `ts` nie z odległej przyszłości, `ON CONFLICT DO NOTHING`, synchronizacja z `enabled = false` dla usuniętych |
| uwaga z review k3 (rozgrzewka) | krok 1: zdanie w `docs/status-codes.md` |
| Zadania k7 (bez zmian) | K2-U5 (`maxOpenConns` ok. 5, `maxIdleConns` ok. 2), K3-U3 (kafelek stanu licznika uwzględnia `link_status`) |

## Ryzyka i założenia (bez potwierdzenia)

- Zachowanie `manual_ack` w paho 2.2.0 z MQTT v3.1.1 i sesją trwałą (ponowne dostarczenie po rozłączeniu bez potwierdzenia, potwierdzenia po zmianie
  połączenia): sprawdzają to testy odporności na prawdziwym brokerze; jeśli zachowanie okaże się inne, zgłaszam i proponuję zmianę, zamiast zakładać.
- Mosquitto z `max_inflight_messages 100` przestaje wysyłać po 100 niepotwierdzonych wiadomościach; to jest warunek działania paczki 100 (test przepustowości
  to potwierdzi).
- Zapis do skompresowanych kawałków z `ON CONFLICT DO NOTHING` działa w przypiętej wersji TimescaleDB (sprawdzone testem w k2).
- Przepustowość: wymagane jest 13 wiadomości na sekundę; w etapie 3 dojdą cztery liczniki i pompa (rząd 65 na sekundę) oraz wypełnianie historii. Test podaje
  zmierzoną przepustowość, żeby etap 3 mógł z niej korzystać.
- Wiadomości z długiej przerwy (ponad ok. 64 minuty) giną na końcu przerwy (opisane wyżej); akceptowane dla demo.
- Ponowne dostarczenie po zmianie połączenia może dać stare identyfikatory pakietów w `ack` (broker je zignoruje); skutkiem są co najwyżej duplikaty,
  które usuwa `ON CONFLICT`.
- Kod trafia na `main` przed testami na komputerze (zatwierdzone w k2); poprawki kolejnymi commitami.

## Jak sprawdzę, że działa

1. pytest na komputerze: wszystkie testy zielone (liczba i czas w raporcie), w tym testy ingestu przed `migrate` i redostarczenia po awarii.
2. `docker compose ps -a`: `aip-ingest` `healthy` obok `mosquitto` i `timescaledb`; `migrate` Exited (0); collector nie istnieje.
3. `devices`: dokładnie 2 wiersze, `plc-01` (plc) i `finder_7m24_1` (energy_meter), oba `enabled = t`; `measurements`: 0 wierszy.
4. Dymek: nieznane urządzenie odrzucone (widoczne w podsumowaniu), tabela `measurements` nadal pusta.
5. `docker stats --no-stream`: `aip-ingest` poniżej limitu; smartWARE bez zmian; `ss -ltn` bez zmian.
6. Nic nie łączy się z PLC w tym kroku.

## Poza zakresem

Start collectora na sprzęcie i test na prawdziwych danych (k5), agregaty ciągłe (k6), Grafana (k7), autostart po restarcie komputera (k8), symulator
(etap 3), przeładowanie configu sygnałem, metryki HTTP, zmiany schematu bazy (migracja 002 w k6), zmiany w PLC i `docs/modbus-map.md`.
