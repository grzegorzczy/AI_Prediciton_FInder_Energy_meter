# e2-k0 plan: plan etapu 2 (kręgosłup danych)
Status: DO PRZEGLĄDU

Podstawa: `docs/plan.md` (etap 2), `docs/modbus-map.md` v1, `docs/data-model.md`
(projekt wstępny), `.claude/agents/data-platform.md`, `.env.example`, ustalenia
Grzegorza i architekta z 23.11.2026. Ten plik nie zawiera kodu; po review i „ok”
każdy krok z listy poniżej przechodzi własny cykl plan → review → ok → wykonanie → raport.

## Cel etapu

PLC (Modbus TCP) → collector → Mosquitto → ingest → TimescaleDB → Grafana, na komputerze
`jumo-ipc` (192.168.0.213). **Gotowe, gdy:** wykresy w Grafanie odświeżają się na żywo
z prawdziwego licznika, a po restarcie komputera wszystko wstaje samo, bez żadnej ręcznej
czynności, i dane znowu płyną.

Poza zakresem etapu 2: symulator i pompa P-101 (etap 3), `machine_states`, `anomaly_scores`,
`events`, `tariffs`, `chat_log` (etapy 4–6), widok `pump_1m` (etap 3), alarmy (etap 5),
Ollama/czat (etap 6).

## Lista kroków (każdy kończy się czymś sprawdzalnym)

| Krok | Co | Agent | Sprawdzalny wynik |
| --- | --- | --- | --- |
| k1 | Przygotowanie komputera: porządek w repo APT Dockera, weryfikacja Dockera, portów, czasu, katalogu i `.env` | główna sesja (polecenia wykonuje Grzegorz) | wyniki poleceń z listy w k1 wklejone do raportu |
| k2 | `docker-compose.yml` (szkielet), Mosquitto z hasłem, TimescaleDB, role, migracje tabel surowych | `data-platform` | `docker compose ps` healthy; `\dt`; publikacja i odbiór MQTT z hasłem; pytest migracji zielony |
| k3 | Collector (Modbus TCP, FC04, reguły ważności, publikacja MQTT) | `data-platform` | pytest z lokalnym serwerem pymodbus zielony; test „collector nigdy nie pisze” |
| k4 | Ingest (MQTT → walidacja → paczki → baza) | `data-platform` | pytest zielony; przypadki: nieznane urządzenie, zły ładunek, duplikat |
| k5 | Połączenie na sprzęcie: prawdziwy PLC → MQTT → baza | `data-platform` + Grzegorz | liczba wierszy ≈ oczekiwana; wartości zgodne z `mbpoll`; test „PLC offline” |
| k6 | Agregaty ciągłe, kompresja, retencja, widoki przyrostów energii | `data-platform` | pytest na danych syntetycznych (w tym reset licznika); polityki widoczne w katalogu |
| k7 | Grafana: provisioning (źródło danych, dashboard) | `dashboards` | dashboard „Energia – na żywo” odświeża się co 5 s; zrzut |
| k8 | Autostart, restart komputera, pomiar RAM/dysku, `etap-2.md`, agent `reviewer` | `data-platform` + `reviewer` | test restartu przechodzi; `docker stats`; checklista |

Kolejność k3 i k4 jest wymienna. Zrzuty do `docs/images/etap2/` zamawiam w trzech momentach:
po k5 (`docker ps`, logi collectora i ingestu, próbka z bazy), po k7 (Grafana na żywo),
po k8 (stan po restarcie komputera: `docker ps` z czasem działania, Grafana, logi).

## Pliki (całość etapu)

```
docker-compose.yml
.env.example                      (uzupełnienie zmiennych, patrz decyzja D3)
config/devices.yaml               (PLC, urządzenia, profile rejestrów)
config/mosquitto/mosquitto.conf
config/mosquitto/acl.conf
config/mosquitto/entrypoint.sh    (generuje passwd z .env przy starcie)
db/init/00-roles.sh               (role z haseł z .env, tylko przy pierwszym utworzeniu bazy)
db/migrations/001_core.sql        (devices, measurements, hypertable, kompresja, retencja)
db/migrations/002_aggregates.sql  (energy_1m, energy_1h, polityki, widoki przyrostów)
db/migrate.py                     (runner migracji, tabela schema_migrations)
services/collector/               (Dockerfile, requirements.txt, src/…)
services/ingest/                  (Dockerfile, requirements.txt, src/…)
grafana/provisioning/datasources/timescaledb.yaml
grafana/provisioning/dashboards/provider.yaml
grafana/dashboards/energia-na-zywo.json
tests/conftest.py, tests/fakes/modbus_plc.py
tests/config/, tests/collector/, tests/ingest/, tests/db/
docs/stages/etap-2.md             (checklista akceptacji, na końcu etapu)
docs/images/etap2/                (zrzuty, patrz wyżej)
docs/handoff/e2-kM-*.md           (plan i raport każdego kroku)
```

## Docker Compose: kontenery, porty, mem_limit

Wszystkie usługi: `restart: unless-stopped`, healthcheck, logi `json-file` (max 10 MB × 3),
sieć wewnętrzna Compose, `TZ` z `.env`. Kolejność startu przez `depends_on: condition: service_healthy`.

| Kontener | Port na hoście | mem_limit | Uwagi |
| --- | --- | --- | --- |
| mosquitto | **1883** (z hasłem, bez anonimowych) | 64 MB | `persistence true` na wolumenie; ACL osobno dla collectora i ingestu |
| timescaledb | **brak** (tylko sieć wewnętrzna) | 1536 MB | `shared_buffers` ok. 384 MB, `max_connections` 30; tag obrazu przypięty, nie `latest` |
| migrate | brak | 64 MB | jednorazowy (`restart: "no"`); stosuje `db/migrations/*.sql`, kończy się |
| collector | brak | 128 MB | do PLC idzie przez NAT Dockera (bez `network_mode: host`) |
| ingest | brak | 128 MB | czeka na `migrate` (zakończony) i bazę |
| grafana | **3000** (do potwierdzenia w k1, że wolny) | 384 MB | tylko rola `app_reader`; porty 80/443 NIE są używane (zajmuje je smartWARE) |
| **Suma limitów** | | **2240 MB** (+64 MB chwilowo, `migrate`) | to limity, nie pomiar; zmierzone zużycie poda raport k8 |

Budżet 16 GB (reguła 2): system i Docker ok. 1 GB (założenie) + smartWARE 0,4–1 GB + etap 2
2,2 GB + rezerwa na Ollamę ok. 3 GB (założenie dla `qwen2.5:3b` z `.env.example`; do
zmierzenia w etapie 6) + późniejsze usługi (symulator, analytics, chat) ok. 1,5 GB ≈ 9–9,5 GB.
Zapas ok. 6,5 GB. Limity z tabeli skoryguję po pomiarze w k8.

Dysk (szacunek do zmierzenia po dobie, nie fakt): ok. 10 metryk × 1 s ≈ 0,86 mln wierszy/dobę;
90 dni surowych to ok. 78 mln wierszy, po kompresji rząd kilku GB na 1 TB NVMe.

## Schemat bazy (migracje)

Zasada: etap 2 tworzy tylko to, co sam wykorzystuje; reszta tabel z `docs/data-model.md`
powstaje w swoich etapach (nowa migracja `00N`).

- **`001_core.sql`**
  - `devices` (kolumny jak w `data-model.md`), synchronizowana z `config/devices.yaml`
    przy starcie ingestu (upsert; urządzenia usunięte z YAML dostają `enabled=false`).
  - `measurements`: `time, device_id, metric, value, unit, source`; hypertable po `time`,
    kawałki 1 dzień; `UNIQUE (device_id, metric, time)`; kompresja po 1 dniu,
    `segmentby = device_id, metric`; retencja 90 dni.
  - Role: `app_writer` (INSERT/SELECT na `measurements`, `devices`; ingest) i `app_reader`
    (tylko SELECT, `statement_timeout` ustawiony na roli; Grafana, później czat).
    Hasła z `.env`, nie z repo.
- **`002_aggregates.sql`**
  - `energy_1m`: agregat ciągły z `measurements`, jeden wiersz = urządzenie × minuta;
    pivot metryk przez `FILTER (WHERE metric = …)`. Zawiera: śr./min/maks. mocy czynnej,
    napięcia, prądu; śr. `power_factor`, `frequency`; `first/last/min/max` liczników
    `energy_import_wh` i `energy_export_wh`; `sample_count`; `energy_integral_wh`
    (patrz „Rozdzielczość licznika”). Retencja 1 rok.
  - `energy_1h`: agregat hierarchiczny nad `energy_1m`, bez limitu retencji.
  - Polityki odświeżania z `start_offset` krótszym niż retencja surowych danych, żeby
    usunięcie starych surowych wierszy nie kasowało zmaterializowanych agregatów.
  - Widoki przyrostów (zwykłe widoki nad agregatami): przyrost energii w oknie z obsługą
    resetu (patrz niżej).
- `pump_1m` (retencja 1 rok) powstaje w etapie 3 razem z metrykami pompy.

### Energia: stan licznika i przyrosty

Zapisujemy stan licznika w Wh = `mantysa × 10^wykładnik` (rejestry 34–39), nie REAL kWh
z rejestrów 30–33. Mantysa to DINT ze znakiem, wykładnik INT ze znakiem.

Przyrost w oknie = `last − poprzednie last`. Agregat ciągły TimescaleDB nie pozwala na funkcje
okna, więc agregat przechowuje `first/last/min/max`, a przyrost liczy zwykły widok z `LAG`.
Reset: jeśli `last < poprzednie last`, przyrost = `last` (licznik wystartował od zera),
a zdarzenie jest oznaczone w widoku (`reset_detected`). Test na danych syntetycznych
w k6 obejmuje reset, przeskok o wiele jednostek i lukę w danych.

### Rozdzielczość licznika (100 Wh) i małe obciążenie

Licznik zmienia stan co 100 Wh. Przy 7 W (stan z 23.11.2026) to jeden krok na ok. 14 godzin,
więc stan licznika nie pokazuje zużycia w krótkich oknach. **Propozycja:** obok stanu licznika
liczymy `energy_integral_wh` = suma mocy czynnej × czas próbkowania (1 s nominalnie, z
`sample_count` zamiast zakładania pełnej minuty; luki w danych nie są dopełniane).
Dashboard pokazuje:

- **zużycie z całki mocy** jako wartość główną dla krótkich okien (minuta, godzina),
- **stan licznika** i przyrost z licznika jako wartość wzorcową i do kontroli,
- różnicę obu na dłuższym oknie (doba, tydzień) jako kontrolę poprawności.

Całka jest przybliżeniem: błąd rośnie z lukami i szybkimi zmianami obciążenia. Koszty
(etap 4) będą musiały wybrać źródło; to decyzja do `docs/decisions.md`, nie do etapu 2.

## `config/devices.yaml` (szkic struktury)

Cały opis urządzenia i układ rejestrów są w pliku konfiguracyjnym (reguła 3). W kodzie
zostają tylko typy dekodowania (`uint16`, `uint32`, `int16`, `int32`, `real32`, `ascii`).

```yaml
# ZASADA: adres PLC występuje tylko tutaj (DHCP: po zmianie adresu edytujemy ten plik).
plc:
  id: plc-01
  host: 192.168.0.246
  port: 502
  unit_id: 1
  function: 4              # Read Input Registers, jedyna używana
  read: { start: 0, count: 44 }
  poll_interval_s: 1.0
  map_version: 1           # rejestr 2 musi się zgadzać
  heartbeat_timeout_s: 5   # rejestry 0-1
  site: <do ustalenia, D1>
  line: <do ustalenia, D1>

profiles:
  finder_7m24:
    status:   { offset: 0,  type: uint16 }
    # offsety wg docs/modbus-map.md (blok 50 rejestrów)
    metrics:
      active_power:      { offset: 6,  type: real32, unit: W }
      reactive_power:    { offset: 8,  type: real32, unit: var }
      apparent_power:    { offset: 10, type: real32, unit: VA }
      power_factor:      { offset: 12, type: real32, unit: "" }
      frequency:         { offset: 14, type: real32, unit: Hz }
      voltage:           { offset: 16, type: real32, unit: V }
      current:           { offset: 18, type: real32, unit: A }
      energy_import_wh:  { mantissa: 24, exponent: 26, unit: Wh }
      energy_export_wh:  { mantissa: 27, exponent: 29, unit: Wh }
    serial: { offset: 30, type: ascii, registers: 4 }

devices:
  - id: finder_7m24_1
    name: "Licznik energii Finder 7M.24 nr 1"
    kind: energy_meter
    source: real
    profile: finder_7m24
    block_base: 10
    serial: F0183363       # niezgodność = błąd konfiguracji
```

Wyniki walidacji: brakujące pole, powtórzone `id` albo nakładające się bloki rejestrów to
błąd przy starcie (test w `tests/config/`).

## Collector (zakres)

- Jedno zapytanie FC04 co 1 s: Unit ID 1, rejestry 0–43, starsze słowo pierwsze.
  Biblioteka pymodbus w wersji przypiętej w `requirements.txt`; **tylko odczyt** (reguła 1):
  klient opakowany w klasę wystawiającą wyłącznie `read_input_registers`.
- Wspólny interfejs źródeł (`SourceDriver`) już teraz, implementacja `ModbusPlcDriver`;
  OPC UA później bez zmiany reszty.
- Reguły ważności z `docs/modbus-map.md`, w tej kolejności:
  1. brak połączenia / timeout → `link_status = 1` („PLC offline”), brak pomiarów;
  2. `map_version ≠ 1` → `link_status = 3` (błąd konfiguracji), brak pomiarów;
  3. `heartbeat` bez zmiany > 5 s (zegar monotoniczny collectora) → `link_status = 2`
     („PLC zatrzymany”), brak pomiarów;
  4. `serial` ≠ wartość z `devices.yaml` → `link_status = 3`, brak pomiarów;
  5. `status` licznika ≠ 0 → pomiary nieważne, publikujemy tylko `meter_status`;
  6. w przeciwnym razie `link_status = 0` i pełen zestaw metryk.
- Ponowne łączenie z wykładniczym wzrostem przerwy (maks. 10 s). Przerwa MQTT:
  ograniczona kolejka w pamięci, po przepełnieniu najstarsze odrzucane i logowane.
- Znacznik czasu: zegar komputera (PLC nie ma zegara w tej mapie), UTC, ISO 8601 z milisekundami.
- Temat: `{site}/{line}/{device_id}/{metric}`, ładunek `{ts, value, unit, source: "real"}`,
  QoS 1. Poza metrykami licznika: `plc-01/link_status` oraz `finder_7m24_1/meter_status`
  (kody liczbowe, jednostka pusta).
- Healthcheck przez plik znacznika aktualizowany po każdym cyklu (stary znacznik = unhealthy).

## Ingest (zakres)

- Subskrypcja `+/+/+/+`, QoS 1, stały `client_id` i sesja trwała, żeby wiadomości z czasu
  krótkiej przerwy ingestu nie przepadły (Mosquitto, `persistence true`).
- Walidacja: 4 segmenty tematu; `ts` parsowalny i nie z odległej przyszłości; `value`
  skończona liczba; `unit` napis; `source ∈ {real, sim}` zgodne z `devices.source`.
  Odrzucone → log (z limitem częstotliwości), nie baza.
- Nieznane `device_id` → log, nie baza (zgodnie z `data-platform.md`).
- Zapis paczkami (np. co 1 s lub 500 wierszy) jednym `INSERT … ON CONFLICT DO NOTHING`.
  Ponowienie tej samej wiadomości nie tworzy duplikatu.
- Rola `app_writer`. Ponowne łączenie z bazą z cofaniem; w tym czasie wiadomości czekają
  w kolejce Mosquitto (`max_queued_messages` ustawione tak, by pomieścić kilkadziesiąt minut
  przy ok. 10 wiadomościach na sekundę; **po dłuższej przerwie bazy dane giną**, o czym
  raport k4 poinformuje wprost).
- Healthcheck plikiem znacznika, jak w collectorze.

## Grafana

- Źródło danych TimescaleDB jako `app_reader` z provisioningu (hasło z `.env` przez zmienną
  środowiskową, nie w pliku).
- Dashboard „Energia – na żywo”: napięcie, prąd, moc czynna/bierna/pozorna, współczynnik
  mocy, częstotliwość; kafelki statusu („PLC offline”, „PLC zatrzymany”, „błąd
  konfiguracji”, „licznik: brak danych”) wyświetlane po polsku; zużycie z całki mocy obok
  stanu licznika. Odświeżanie 5 s, domyślny zakres 15 min, strefa Europe/Warsaw.
- Pliki w repo (provisioning), nic klikane ręcznie.

## Testy pytest (bez sprzętu)

- `tests/fakes/modbus_plc.py`: lokalny serwer Modbus TCP (pymodbus) z rejestrami zbudowanymi
  wg mapy, w tym wartościami z 23.11.2026 (U 240,4 V, energia pobrana 3500 Wh = mantysa 35,
  wykładnik 2, serial F0183363). Serwer zapisuje, jakie kody funkcji do niego trafiły.
- Collector: dekodowanie (kolejność słów, ze znakiem), każda z reguł ważności (6 przypadków
  powyżej), ponowne łączenie po zerwaniu, **żaden kod funkcji zapisu nie dotarł do serwera**.
- Ingest: poprawny ładunek, zły JSON, brak pola, nieznane urządzenie, niezgodne `source`,
  duplikat, paczkowanie.
- Konfiguracja: `devices.yaml` wczytuje się i walidacja łapie błędy; żaden adres IP ani
  numer rejestru nie występuje w kodzie usług (test przeszukujący źródła).
- Baza (testy integracyjne, wymagają Dockera, oznaczone `integration`): migracje na pustej
  bazie, idempotencja runnera, role (`app_reader` nie może pisać, limit czasu zapytania),
  agregaty na danych syntetycznych, w tym reset licznika.
- Testy jednostkowe nie wymagają Dockera ani PLC; uruchamiane `pytest -m "not integration"`.

## Checklista dla Grzegorza (szkic; pełna w `docs/stages/etap-2.md`)

Polecenia z laptopa w cmd jako `ssh jumo@192.168.0.213 "<polecenie>"`, z sudo `ssh -t …`.

1. `docker compose ps`: wszystkie usługi `healthy` (wyjątek: `migrate`, zakończony kodem 0).
2. Wiersze w bazie rosną: zapytanie liczące `measurements` z ostatniej minuty (oczekiwane
   ok. 540–600, zależnie od liczby metryk).
3. Grafana: `http://192.168.0.213:3000`, dashboard odświeża się co 5 s; wartości zgodne z
   `mbpoll` i wyświetlaczem licznika.
4. Test „PLC offline”: odłączenie PLC od sieci na ok. 30 s pokazuje „PLC offline” na
   dashboardzie, po podłączeniu dane wracają bez ingerencji.
5. Test restartu: `ssh -t jumo@192.168.0.213 "sudo reboot"`; po ok. 3 minutach (cel; do
   potwierdzenia pomiarem) `docker compose ps` pokazuje wszystko `healthy`, a dashboard
   znowu rysuje dane.
6. `docker stats --no-stream` i `free -m`: zużycie RAM do raportu.
7. Zrzuty do `docs/images/etap2/` (kiedy: po k5, k7, k8).

## Krok k1: przygotowanie komputera (polecenia, nie kod)

Sprawdzam, zanim zmieniam; komendy wykonuje Grzegorz, wyniki wklejamy do `e2-k1-report.md`.

1. `lsb_release -cs` oraz `cat /etc/apt/sources.list.d/*docker*` (i `/etc/apt/sources.list`):
   zobaczymy, który plik wskazuje na „focal”.
2. Kopia pliku przed zmianą, potem zamiana `focal` na `jammy` w odpowiednim wpisie Dockera
   (`sudo cp …`, `sudo sed -i …`); następnie `sudo apt update` bez błędów repozytorium.
   Zakładam, że system to Ubuntu 22.04 („jammy”), jak wynika z opisu; **potwierdza to wynik
   `lsb_release -cs`** i jeśli będzie inny, zatrzymuję się i pytam.
3. `docker --version`, `docker compose version`, `systemctl is-enabled docker` (musi być
   `enabled`, inaczej autostart nie zadziała), `docker run hello-world`.
4. `ss -ltn` (porty 1883 i 3000 wolne; 80/443 zajęte przez smartWARE, nie ruszamy), `df -h /`,
   `free -m`, `timedatectl` (zegar zsynchronizowany, strefa Europe/Warsaw; znaczniki czasu
   idą z zegara komputera).
5. Katalog projektu i dostarczenie repo (decyzja D5), `.env` z silnymi hasłami, uprawnienia 600.
   Hasła generuje i wpisuje Grzegorz; ja ich nie widzę.

## Decyzje do podjęcia (propozycja i uzasadnienie)

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| D1 | Nazwy `zaklad` i `linia` w temacie MQTT | Do ustalenia z Grzegorzem; potrzebuję dwóch napisów ASCII bez spacji, np. demonstracyjnych | To segmenty tematu i klucze w bazie; zmiana później to migracja danych. Nie zgaduję. |
| D2 | Skąd `ts` | Zegar komputera (UTC, ms) | Mapa nie zawiera czasu z PLC; opóźnienie odczytu to milisekundy, mniejsze niż okres 1 s |
| D3 | Konta MQTT | Dwa konta: `collector` (tylko zapis) i `ingest` (tylko odczyt), ACL w pliku. `.env.example` ma teraz jedną parę `MQTT_USER/MQTT_PASSWORD`; proponuję rozbić na `MQTT_COLLECTOR_*` i `MQTT_INGEST_*` | Najmniejsze uprawnienia: przejęty collector nie czyta danych, ingest nie publikuje; w etapie 3 dojdzie konto symulatora |
| D4 | Migracje | Jednorazowy kontener `migrate` z prostym runnerem i tabelą `schema_migrations` | `docker-entrypoint-initdb.d` działa tylko przy pierwszym utworzeniu bazy; kolejne etapy dodają migracje do istniejącej bazy. Kosztem jest jeden krótkotrwały kontener |
| D5 | Dostarczenie repo na komputer | `git clone` przez HTTPS, jeśli repo jest publiczne lub będzie token; w przeciwnym razie `git archive` + `scp` | Nie wiem, czy repo jest publiczne; od tego zależy, czy komputer musi mieć dostęp do GitHuba. Czekam na decyzję |
| D6 | Przyrosty energii | Zwykłe widoki z `LAG` nad agregatem, bez rozszerzenia `timescaledb_toolkit` | Obraz z toolkitem (`counter_agg` z obsługą resetu) jest większy i cięższy pamięciowo; własny widok jest mały i testowalny |
| D7 | Całka mocy jako druga miara zużycia | Tak, patrz „Rozdzielczość licznika” | Przy 7 W licznik zmienia stan raz na ok. 14 h |
| D8 | Tabele spoza etapu 2 | Nie tworzymy ich w etapie 2 | Kolumny w `data-model.md` to propozycja; każdy etap zatwierdzi swoje, gdy zna wymagania |
| D9 | Tagi obrazów | Przypiąć konkretne wersje (TimescaleDB/PostgreSQL, Mosquitto, Grafana, pymodbus, paho-mqtt, psycopg) w k2–k4 i wpisać do raportów | Powtarzalna instalacja na drugim komputerze (etap 7); nie zgaduję tu numerów, wybiorę po sprawdzeniu w k2 |
| D10 | `link_status` i `meter_status` jako metryki w MQTT | Tak | Spójne z architekturą (jedna droga danych), widoczne w Grafanie i do późniejszych alarmów |

## Ryzyka i założenia (bez potwierdzenia)

- System komputera to Ubuntu 22.04 („jammy”); do potwierdzenia w k1.
- Porty 1883 i 3000 są wolne (1883 potwierdzone przez Grzegorza, 3000 do sprawdzenia).
- Kontener w sieci mostowej Dockera dociera do PLC w LAN przez NAT (zwykle działa); jeśli nie,
  zgłaszam i proponuję rozwiązanie, `network_mode: host` tylko za zgodą.
- Adres PLC 192.168.0.246 jest z DHCP: po jego zmianie collector zgłasza „PLC offline”
  aż do edycji `config/devices.yaml`. Rezerwacja adresu w routerze rozwiązałaby to na stałe;
  to decyzja po stronie sieci Grzegorza, nie etapu 2.
- Szacunki RAM i dysku są założeniami do zmierzenia (k8).
- Zegar komputera jest synchronizowany (sprawdzane w k1).
- Wersje pymodbus: API zmienia się między wersjami (np. nazwa parametru Unit ID); wersję
  przypinam i testy to sprawdzają.
- Strata danych: dłuższa niż kilkadziesiąt minut przerwa bazy przy działającym collectorze
  powoduje utratę danych z tego okresu (bufor w Mosquitto jest ograniczony). Dla demo
  akceptowalne; raport k4 to opisze.

## Jak sprawdzę, że działa (poza testami pytest)

- k2: `docker compose up -d`, `docker compose ps`, `\dt`, `mosquitto_pub/sub` z hasłem
  (i odmowa bez hasła).
- k5: porównanie odczytu z `mbpoll` z wartościami w bazie w tej samej sekundzie.
- k7: otwarcie dashboardu, zrzut ekranu z odświeżającym się wykresem.
- k8: restart komputera i pomiar czasu do stanu „healthy”.
- Dokumenty projektu (`modbus-map.md`) nie są zmieniane. Jeśli test ujawni potrzebę zmiany
  mapy, zatrzymuję się i zgłaszam.

## Poza zakresem

Symulator, pompa P-101, analityka, anomalie, alarmy, czat, Ollama, logowanie użytkowników,
kopie zapasowe, instalator, drugi licznik (blok od rejestru 60 jest w mapie, ale w etapie 2
konfigurujemy tylko `finder_7m24_1`).
