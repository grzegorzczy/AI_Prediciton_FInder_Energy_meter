# e2-k3 plan: collector (Modbus TCP → MQTT)
Status: DO PRZEGLĄDU

Podstawa: `e2-k0-plan.md` i `e2-k0-review.md` (D2, D10, U2, U4), `e2-k2-report-review.md` (R2-U1, R2-U2, R2-U3),
`docs/modbus-map.md` (stan po poprawce filtra 3 s, pola 10–15), `config/devices.yaml`, `CLAUDE.md`.
Krok nie łączy się z prawdziwym PLC: collector powstaje, jest testowany na lokalnym serwerze pymodbus i budowany
jako obraz; start na sprzęcie to k5.

## Cel kroku

Usługa `collector` czyta PLC wyłącznie funkcją FC04 co 1 s (Unit ID 1, rejestry 0–43 jednym zapytaniem, starsze słowo
pierwsze), ocenia ważność danych wg kontraktu i publikuje do Mosquitto temat `zaklad1/linia1/{device_id}/{metric}`
z ładunkiem `{ts, value, unit, source: "real"}`. Do PLC i licznika nigdy nie pisze (reguła 1).

**Sprawdzalny wynik:** pytest zielony na komputerze (w tym test, że na serwer PLC nie dotarł żaden kod funkcji poza 04),
obraz `collector` buduje się, `docker compose config --quiet` przechodzi, prawa plików w klonie poprawione (R2-U1),
`deny` dla `Read` i `Grep` na `.env` działa (R2-U3, sprawdzone na atrapie).

## Tryb wykonania na komputerze

Jak w k1 i k2 (`e2-k1-results.md`): `ssh jumo@192.168.0.213`, Git Bash i `bash -s`, `</dev/null` przy `docker compose
run/exec`, **bez `sudo`**, bez ruszania smartWARE, demona Dockera i `docker system prune`; `docker compose down -v` na
projekcie `ai-predykcja` tylko za zgodą. Raport nie zawiera sekretów. Zasada z R2-U3: nie wykonuję poleceń wypisujących `.env`
(`cat`, `type`, `grep` po wartościach), także na komputerze; `.env` sprawdzam tylko po nazwach i długościach.

## Pierwszy punkt wykonania: R2-U1 (prawa plików w klonie) i R2-U3 (`deny Grep`)

### R2-U1

Przyczyna z k2: `umask 077` z polecenia tworzącego `.env` pozostał w konsoli Grzegorza, a późniejszy `git pull` utworzył
pliki 600/700. Kroki (ja, bez `sudo`):

```bash
cd /home/jumo/ai-predykcja
find . -path ./.git -prune -o -type d -exec chmod 755 {} +
find . -path ./.git -prune -o -type f ! -name .env -exec chmod 644 {} +
chmod 600 .env
git ls-files -s | awk '$1=="100755"{print $4}' | xargs -r chmod 755   # pliki z bitem wykonywania w repo (obecnie brak)
```

Kontrola (do raportu k3): `stat -c '%a %U %n' .env config/devices.yaml db/migrate.py config .git`; oczekiwane `600` dla `.env`,
`644` dla plików, `755` dla katalogów; `find . -path ./.git -prune -o -type f ! -name .env ! -perm -o=r -print` oraz to samo
dla katalogów (`-type d ! -perm -o=rx`) bez wyników; `git status -sb` czysty (Git śledzi tylko bit wykonywania).

Zmiany w `docs/ops/jumo-ipc-setup.md`:

1. Polecenie tworzące `.env` (sekcja 6) w podpowłoce `( umask 077; … )`, żeby `umask` nie zostawał w konsoli.
2. Nowy krok „po każdym `git pull`: kontrola praw” (komenda `find … -print` wyżej, oczekiwany pusty wynik; naprawa
   `chmod` jak wyżej). Uzasadnienie: kontenery z innym użytkownikiem niż `jumo` czytają `config/devices.yaml`
   zamontowany `:ro` (decyzja R2-U1 pkt 4).
3. Grzegorz zamyka okno konsoli, w którym tworzył `.env` (umask znika z sesją).

### R2-U3

Do `.claude/settings.json` dopisuję `deny` dla `Grep` na ścieżkach `.env` i `**/.env` (obok istniejącego `Read`).
Reguł `Bash` nie dodajemy (wzorce poleceń są nieszczelne). **Weryfikacja bez ryzyka:** nie testuję na prawdziwym `.env`.
Tworzę atrapę `docs/decoy/.env` z treścią `DECOY=1` (ignorowana przez git: `*.env`), próbuję ją odczytać narzędziem Read i
przeszukać narzędziem Grep; oczekiwana odmowa obu. Atrapę usuwam. Jeśli reguła `Grep` z takim wzorcem nie jest rozpoznawana,
raportuję to wprost i proponuję alternatywę, zamiast zakładać, że działa.

## Co powstaje / zmienia się (pliki)

```
services/collector/Dockerfile, requirements.txt
services/collector/src/collector/__init__.py
  main.py          pętla: harmonogram, odczyt, ocena, publikacja, healthcheck
  config.py        wczytanie i walidacja config/devices.yaml
  codec.py         dekodowanie rejestrów (uint16/32, int16/32, real32, ascii, energia mantysa × 10^wykładnik)
  status.py        enumy kodów: LinkStatus, MeterStatus (jedno miejsce w kodzie)
  evaluator.py     reguły ważności (czysta funkcja + stan heartbeat, zegar wstrzykiwany)
  publisher.py     paho-mqtt 2.x, bufor w pamięci, ponowne łączenie, tematy i ładunek
  health.py        plik znacznika żywotności
  drivers/base.py  interfejs SourceDriver (później OPC UA)
  drivers/modbus_plc.py   ModbusPlcDriver + ReadOnlyModbusClient (tylko read_input_registers)
docs/status-codes.md   kody link_status i meter_status z tłumaczeniem na polski (dla Grafany, k7)
config/devices.yaml    uzupełnienia (nazwy metryk statusów, timeout, ponawianie; patrz niżej)
docker-compose.yml     usługa collector (profil `live`, patrz K3-f)
docker-compose.test.yml, tests/requirements.txt   montowanie kodu collectora, pymodbus w testach
tests/fakes/modbus_plc.py   atrapa PLC: serwer Modbus TCP z rejestrami wg mapy i rejestrem kodów funkcji
tests/collector/test_codec.py, test_evaluator.py, test_payload.py, test_driver.py,
  test_publisher_buffer.py, test_e2e.py, test_no_write.py
docs/ops/jumo-ipc-setup.md, .claude/settings.json
docs/handoff/e2-k3-report.md
```

## Zakres collectora

### Biblioteka i odczyt (D2 i zasada 1)

- `pymodbus` **3.16.2** (sprawdzone w odizolowanym środowisku: parametr identyfikatora urządzenia to `device_id`, nie
  `slave`; klient domyślnie ponawia 3 razy i sam łączy się ponownie, więc ustawiam `retries=0` oraz `reconnect_delay=0`, a
  ponawianie robię sam, żeby zapytanie do wyłączonego PLC nie trwało kilkanaście sekund). Wersja przypięta w
  `requirements.txt` (D9), razem z `paho-mqtt==2.2.0` i `PyYAML==6.0.4`.
- Klient pymodbus ma metody zapisu (`write_register`, `write_registers`, `write_coil`, `mask_write_register`,
  `readwrite_registers`…). Dlatego `ReadOnlyModbusClient` trzyma go prywatnie i wystawia tylko `connect`, `close` i
  `read_input_registers`. Test sprawdza publiczny interfejs i to, że w źródłach `services/collector/` nie występują nazwy
  metod zapisu. Ostateczny dowód po stronie serwera: atrapa PLC zapisuje kody funkcji (`trace_pdu`), a test wymaga,
  by były tylko `{4}`.
- `timeout_s: 2`, jedno zapytanie `read_input_registers(0, count=44, device_id=1)`, dane dekodowane wg profilu z
  `devices.yaml` (starsze słowo pierwsze; `real32` z dwóch słów jako big-endian; energia = mantysa DINT × 10^wykładnik INT).
- Znacznik czasu `ts`: zegar komputera w chwili odbioru odpowiedzi, UTC, ISO 8601 z milisekundami (`…T12:00:00.123Z`), jeden
  `ts` na cały odczyt (D2).

### Reguły ważności (kontrakt `docs/modbus-map.md`) i kody statusów (D10, U2)

Kolejność oceny w każdym cyklu:

| Krok | Warunek | `link_status` | Co publikujemy |
| --- | --- | --- | --- |
| 1 | brak połączenia, timeout, wyjątek Modbus, krótka odpowiedź | **1** (PLC offline) | tylko `link_status` |
| 2 | `map_version` ≠ 1 | **3** (błąd konfiguracji: zła wersja mapy) | tylko `link_status` |
| 3 | `heartbeat` bez zmiany > 5 s (zegar monotoniczny collectora) | **2** (PLC zatrzymany) | tylko `link_status` |
| 4 | wszystko powyższe OK | **0** | `link_status` i oceny liczników niżej |

Dla każdego licznika osobno (przy `link_status = 0`), więc pomyłka w jednym nie blokuje drugiego (U2):

| Warunek | `meter_status` | Pomiary |
| --- | --- | --- |
| rejestr `status` = 1 (COMM_ERROR) lub 2 (NO_DATA) | wartość z rejestru (1 lub 2) | nie |
| rejestr `status` = inna wartość niż 0–2 | wartość surowa (widoczna, nieznana) i ostrzeżenie w logu | nie |
| `status` = 0 i `serial` ≠ numer z `devices.yaml` | **10** (SERIAL_MISMATCH, liczony przez collector) | nie |
| `status` = 0 i serial zgodny | **0** | tak (7 pomiarów, 2 stany energii) |

**Odstępstwo od numeracji w mapie:** ocenę `status` wykonuję **przed** `serial`. Przy NO_DATA (do ok. 10 s po starcie PLC)
rejestry numeru seryjnego są puste, więc odwrotna kolejność zgłaszałaby fałszywy SERIAL_MISMATCH. Wynik końcowy jest
zgodny z kontraktem (żadne dane nie zostaną zapisane przy złym liczniku). Kody opisuje `docs/status-codes.md` i jeden enum w
`status.py`; test sprawdza ich zgodność.

`meter_status` publikujemy tylko przy `link_status = 0` (przy 1–3 rejestry licznika są nieważne lub zamrożone).

### Filtr 3 s w PLC i pola 10–15

Po stronie PLC (`FB_EnergyMeter`): `status` = 1 od pierwszego błędu, powrót do 0 dopiero po 3 s bez błędu, `error_count` =
liczba przerw (jedna przerwa = +1, przepełnienie 65535 → 0), `data_age_ms` rośnie równo przez całą przerwę (0 przy OK,
`FFFFFFFF` przy NO_DATA), `error_code` = ostatni kod (161 = RESPONSE_TIMEOUT). Skutki dla collectora:

- **Nie dodaję drugiego filtru** po stronie collectora: `meter_status = 1` publikuję natychmiast i do momentu powrotu PLC do 0.
  Skutek do odnotowania w raportach: po zakończeniu przerwy RS485 pomiarów nie ma jeszcze przez ok. 3 s.
- Publikuję diagnostykę (K3-a): `meter_error_count` (surowa wartość, zawinięcie obsługują odbiorcy) i `meter_data_age_ms` (bez
  `FFFFFFFF`: przy NO_DATA tej metryki nie publikuję). `error_code` tylko do logu przy zmianie.

### Start po (ponownym) połączeniu: unikanie zamrożonych danych

PLC zatrzymany, ale odpowiadający serwer Modbus pokazałby stare, niezmienne rejestry. Przy pierwszym odczycie po
połączeniu nie ma jeszcze poprzedniego heartbeatu, więc collector **nie publikuje pomiarów, dopóki nie zobaczy co najmniej
jednej zmiany `heartbeat`**. Jeśli zmiany nie ma przez 5 s: `link_status = 2`. Koszt: pierwsze pomiary po starcie z opóźnieniem
rzędu 1 s (heartbeat rośnie ok. 6 razy na sekundę). Zawinięcie `FFFFFFFF` → 0 liczy się jako zmiana.

### Publikacja (D2, D10)

- Temat `{site}/{line}/{device_id}/{metric}` z `devices.yaml` (D1: `zaklad1/linia1`); QoS 1; ładunek JSON
  `{"ts","value","unit","source":"real"}`; `value` zawsze liczba skończona (NaN lub nieskończoność nie są publikowane).
- Metryki licznika `finder_7m24_1`: `active_power`, `reactive_power`, `apparent_power`, `power_factor`, `frequency`,
  `voltage`, `current`, `energy_import_wh`, `energy_export_wh`, `meter_status`, `meter_error_count`, `meter_data_age_ms`.
  Metryka PLC: `plc-01/link_status`. Wszystkie nazwy i jednostki z `devices.yaml`.
- **Liczba wierszy na minutę przy sprawnym PLC i liczniku: 13 na sekundę, czyli 780** (7 pomiarów + 2 stany energii +
  `meter_status` + `meter_error_count` + `meter_data_age_ms` + `link_status`). To zmienia liczbę z uwagi U7 (660), bo doszła
  diagnostyka; wzór trafi do checklisty k5.
- `link_status` i statusy publikuję w **każdym cyklu** (K3-d), nie tylko przy zmianie: wykres stanu jest ciągły, a „ostatnia
  wartość” zawsze świeża.

### Harmonogram, ponawianie, bufor, logi (U4)

- Harmonogram na zegarze monotonicznym (bez dryfu); jeśli odczyt trwa dłużej niż okres, pomijam opóźnione cykle zamiast je nadrabiać
  seriami.
- Ponowne łączenie z PLC z cofaniem wykładniczym 1 s → maks. 10 s (`reconnect` w configu); w tym czasie cykl nadal publikuje
  `link_status = 1` co sekundę, ale nie młóci PLC próbami.
- **Collector nie kończy się z powodu braku zależności** (U4): brak MQTT lub PLC to stan, nie błąd. Błąd konfiguracji
  przy starcie (zły `devices.yaml`) kończy proces z kodem ≠ 0 i jasnym komunikatem; `restart: unless-stopped` zrobi resztę.
- Publikacja MQTT przez paho 2.x (`connect_async`, `loop_start`, `reconnect_delay_set(1, 30)`). Gdy broker niedostępny:
  bufor w pamięci `deque(maxlen=COLLECTOR_BUFFER_MAX)`, domyślnie 20 000 wiadomości (ok. 25 minut przy 13 na sekundę;
  K3-e). **Po przepełnieniu odrzucane są najstarsze wiadomości** (zgodnie z k0), a odrzucenia są logowane raz na epizod z
  licznikiem. Po powrocie brokera bufor jest opróżniany po kolei, z ograniczeniem tempa, z oryginalnymi znacznikami `ts`. Wewnętrzna
  kolejka paho jest ograniczona (`max_queued_messages_set`), żeby nie rosła bez limitu.
- Logi bez zalewania: jeden wpis na **zmianę stanu** (PLC offline/powrót, zła mapa, zatrzymany PLC, status licznika,
  niezgodny serial, MQTT rozłączony/połączony) oraz przypomnienie co 60 s dla trwającego stanu; w trakcie 30 s ciągłej awarii
  test wymaga nie więcej niż kilku wpisów. Hasło MQTT nigdy w logu.
- Healthcheck: plik znacznika (`/tmp/collector.health`) aktualizowany po każdym zakończonym cyklu; kontener jest `healthy`, gdy
  znacznik jest świeższy niż 15 s. Zdrowie oznacza „pętla żyje”, a nie „PLC działa” (PLC offline to poprawny stan).

### Usługa w Compose (K3-c, K3-f)

`aip-collector`: obraz z `services/collector` (Python 3.12 przypięty digestem jak w k2), `restart: unless-stopped`, `mem_limit` i
`memswap_limit` **128 MB**, `config/devices.yaml` montowany `:ro`, zmienne środowiskowe tylko te potrzebne:
`MQTT_HOST=mosquitto`, `MQTT_USER` i `MQTT_PASSWORD` z `MQTT_COLLECTOR_*`, `TZ`, `LOG_LEVEL`, `COLLECTOR_BUFFER_MAX`,
`DEVICES_CONFIG`. Utwardzenie: użytkownik nie-root, `read_only: true` z `tmpfs: /tmp`, `cap_drop: [ALL]`,
`security_opt: [no-new-privileges:true]`. Do PLC (192.168.0.246:502) dociera przez NAT sieci Compose (bez
`network_mode: host`; założenie z k0, sprawdza je k5). `depends_on` na `mosquitto` (kolejność przy `compose up`); po restarcie
komputera collector sam czeka na broker. **Profil `live`:** w k3 usługa jest zdefiniowana i zbudowana, ale `docker compose up -d`
bez profilu jej nie startuje; w k5 profil zostaje usunięty (jedna linia) i collector rusza razem ze stosem. Suma limitów
`aip-` stale po k3: 1600 MB + 128 MB = **1728 MB**.

## `config/devices.yaml`: zmiany

Zgodnie z regułą 3 nazwy metryk statusów, limity czasu i ponawianie są w configu, nie w kodzie:

- `plc`: `timeout_s: 2.0`, `reconnect: { initial_s: 1, max_s: 10 }`, `link_metric: link_status`.
- profil `finder_7m24`: `status: { …, metric: meter_status }`, `diagnostics.error_count: { …, metric: meter_error_count }`,
  `diagnostics.data_age_ms: { …, metric: meter_data_age_ms, omit_value: 0xFFFFFFFF }`, `diagnostics.error_code` bez `metric`
  (tylko log).
- Adres, port, Unit ID, `map_version`, `heartbeat_timeout_s`, układ rejestrów bez zmian. `tests/config/test_devices_yaml.py`
  rozszerzam o nowe pola (nazwy metryk zgodne z ograniczeniem `^[a-z0-9_]+$` z bazy).

## Testy pytest bez sprzętu

`docker compose -p aip-test -f docker-compose.test.yml run …` jak w k2 (kontener `pytest` dostaje zamontowany kod
`services/collector` i `PYTHONPATH`). Atrapa PLC (`tests/fakes/modbus_plc.py`) działa w procesie testu na lokalnym porcie:
serwer pymodbus 3.16.2, rejestry zbudowane wg mapy (wartości z 23.11.2026: U 240,4 V, P 7,0 W, Q −8,7 var, S 19,1 VA,
PF 0,365, f 50,02 Hz, I 0,08 A, energia pobrana 3500 Wh = mantysa 35 × 10², serial F0183363), tło zwiększające `heartbeat`,
metody do scenariuszy (status licznika, serial, `map_version`, zatrzymanie heartbeatu, wyłączenie serwera, opóźnienie odpowiedzi)
i **rejestr kodów funkcji** (`trace_pdu`). Broker w testach: prawdziwy Mosquitto z projektu `aip-test`.

| Plik | Co sprawdza |
| --- | --- |
| `test_codec.py` | kolejność słów (starsze pierwsze), `uint32`, `int32` i `int16` ze znakiem, `real32` z dwóch słów, mantysa × 10^wykładnik (35×10² = 3500; ujemny wykładnik), serial ASCII `4630 3138 3333 3633` → `F0183363`; wartości z próbki 23.11.2026 po zdekodowaniu całego obrazu rejestrów |
| `test_evaluator.py` | każda reguła i kolejność (offline → mapa → heartbeat → liczniki); heartbeat: dokładnie 5,0 s nie jest awarią, powyżej tak, zawinięcie `FFFFFFFF`→0 to zmiana, brak pomiarów do pierwszej zmiany; status 0/1/2/nieznany; **status przed serialem** (NO_DATA z pustym serialem nie daje 10); niezgodny serial blokuje tylko ten licznik (konfiguracja dwóch liczników w teście: bazy 10 i 60); diagnostyka: `meter_data_age_ms` pomijane przy `FFFFFFFF` |
| `test_payload.py` | temat, ładunek `{ts,value,unit,source}`, format `ts` (UTC, ms, `Z`), `source = real`, wartość skończona, nazwy i jednostki z configu |
| `test_driver.py` | odczyt z atrapy; zerwanie połączenia i powrót bez restartu; cofanie 1 s → 10 s (zegar wstrzyknięty); brak odpowiedzi przez `timeout_s` = „offline”, a nie zawieszenie; `retries=0` i `reconnect_delay=0` faktycznie ustawione |
| `test_publisher_buffer.py` | bufor ograniczony; po przepełnieniu odrzucane najstarsze i jeden log na epizod; po powrocie brokera kolejność i oryginalne `ts`; kolejka paho nie rośnie bez limitu (atrapa transportu) |
| `test_e2e.py` | atrapa PLC → collector w procesie → prawdziwy Mosquitto → odbiorca z kontem `ingest`: komplet 13 wiadomości na cykl; PLC wyłączone → tylko `link_status=1` i brak pomiarów, powrót bez restartu; zamrożony heartbeat → `link_status=2`; `map_version=2` → `3`; przerwa RS485 (status 1) → `meter_status=1` i diagnostyka, bez pomiarów, a po 3 s w atrapie powrót; zły serial → `meter_status=10`; liczba wpisów logu w 30 s awarii; plik znacznika odświeżany |
| `test_no_write.py` | **na serwer atrapy nie dotarł żaden kod funkcji poza 04** (przy wszystkich scenariuszach z `test_e2e.py`); `ReadOnlyModbusClient` nie ma publicznych metod zapisu; w `services/collector/` nie ma nazw `write_*`, `mask_write`, `readwrite`; adres IP i numery rejestrów nie występują w kodzie usługi (reguła 3, test przeszukujący źródła) |

## Kroki wykonania k3

1. **R2-U1 i R2-U3** (sekcja wyżej): prawa w klonie, poprawki `docs/ops`, `deny Grep` z atrapą. Raport: wyniki `stat` i `find`.
2. Kod collectora, atrapa PLC i testy na laptopie; kontrola składni (`py_compile`, `sh -n`); commit na `main` (jak w k2: poprawki kolejnymi commitami,
   raport wymienia wszystkie hashe).
3. Na komputerze: `git pull --ff-only`, kontrola praw po `pull`, `sh tests/run-tests.sh </dev/null` (całość, razem z k2); pomiar `free -m`
   w trakcie testów.
4. Budowa obrazu `collector` (`docker compose build collector`, bez startu, bo profil `live`); `docker compose config --quiet`; kontrola, że obraz
   uruchamia się jako użytkownik nie-root i importuje pakiet (`docker run --rm … python -c "import collector"`), bez dotykania PLC.
5. Raport `e2-k3-report.md`; commit; stop.

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K3-a | Diagnostyka licznika w MQTT | publikować `meter_error_count` i `meter_data_age_ms` | Potrzebne do alarmów w etapie 5; kosztem 2 wierszy na sekundę (780 zamiast 660 wierszy na minutę, ok. 170 tys. wierszy dziennie więcej). Decyzja zostawiona Claude Code w review k0 |
| K3-b | Kolejność oceny licznika | `status` przed `serial`; nieznane wartości `status` publikowane surowo | Przy NO_DATA serial jest pusty; odwrotna kolejność dawałaby fałszywy SERIAL_MISMATCH. Wynik zgodny z kontraktem |
| K3-c | Utwardzenie kontenera | nie-root, `read_only`, `cap_drop: ALL`, `no-new-privileges` | Collector nie potrzebuje niczego poza siecią i `/tmp`; mniejsze skutki ewentualnej luki |
| K3-d | Statusy w każdym cyklu | tak | Ciągły wykres stanu i świeża „ostatnia wartość”; koszt to 2 wiersze na sekundę (wliczone w 13) |
| K3-e | Bufor MQTT | `COLLECTOR_BUFFER_MAX` = 20 000, odrzucane najstarsze, log raz na epizod | Zgodne z k0; ok. 25 minut przy 13 wiadomościach na sekundę, pamięć rzędu kilku MB. Mosquitto po swojej stronie odrzuca najnowsze (R2-U2); opisuję obie asymetrie w raporcie |
| K3-f | Profil `live` w Compose do k5 | zdefiniować usługę teraz, nie uruchamiać | Budowa i limity sprawdzone w k3; start na sprzęcie zostaje w k5, zgodnie z listą kroków |
| K3-g | Limity czasowe | `timeout_s` 2 s, ponawianie 1 s → 10 s, w `devices.yaml` | Reguła 3; zapytanie dłuższe niż okres 1 s tylko przy awarii |
| K3-h | Brak zmiany `heartbeat` po połączeniu | nie publikować pomiarów do pierwszej zmiany, po 5 s `link_status = 2` | Unika zapisania zamrożonych danych z zatrzymanego PLC; koszt ok. 1 s opóźnienia |
| K3-i | Błąd konfiguracji przy starcie | zakończenie z kodem ≠ 0 (restart przez Docker) | Zły config nie ma sensownego stanu do publikacji; U4 dotyczy zależności, nie konfiguracji |
| K3-j | Testy bez osobnych kontenerów collectora | atrapa PLC i collector w procesie `pytest`, prawdziwy broker | Prostsze i szybsze niż sieć kontenerów; obraz sprawdzamy osobno (krok 4), pełny tor na sprzęcie w k5 |
| K3-k | `ts` | jeden na odczyt, zegar komputera | D2 (zatwierdzone); jeden znacznik spójnie opisuje całą migawkę |

## Przekazanie decyzji do tego planu

| Pozycja | Gdzie w planie |
| --- | --- |
| D2 | `ts` z zegara komputera, UTC, ms, jeden na odczyt |
| D10, U2 | `link_status` 0–3, `meter_status` 0–2 z rejestru i 10 liczone przez collector, enum w `status.py`, `docs/status-codes.md` (polskie nazwy do k7) |
| U4 | brak zakończenia przy braku zależności, cofanie wykładnicze, logi bez zalewania, healthcheck bez wymagania PLC |
| Filtr 3 s i pola 10–15 | sekcja „Filtr 3 s w PLC”; brak drugiego filtru, diagnostyka, `error_code` do logu |
| R2-U1 | pierwszy punkt wykonania, poprawka polecenia `.env` w `docs/ops`, `config/devices.yaml` montowany `:ro`, kontrola praw po `git pull` |
| R2-U2 | asymetria buforów (collector: najstarsze, Mosquitto: najnowsze) opisana; powtórzenie wprost w raporcie k4 |
| R2-U3 | `deny Grep` na `.env`, weryfikacja na atrapie, zasada „nie wypisuję `.env`” |
| Z k2 (K2-U5) | `maxOpenConns` ok. 5 i `maxIdleConns` ok. 2 w Grafanie: zadanie k7, nie k3 |

## Ryzyka i założenia (bez potwierdzenia)

- Kontener w sieci mostowej Dockera dociera do PLC w LAN przez NAT (założenie z k0); sprawdza je dopiero k5 na sprzęcie. W k3 nie łączę się z PLC.
- Atrapa serwera pymodbus zachowuje się jak serwer CODESYS dla FC04 w zakresie odczytu. Różnice (np. zachowanie przy zatrzymanym
  programie PLC) wyjdą dopiero w k5; reguły ważności są napisane tak, by dobrze znosić oba przypadki (brak odpowiedzi albo zamrożone rejestry).
- pymodbus 3.16.2 zmienia API między wersjami (np. `slave` → `device_id`); testy sprawdzają zachowanie przypiętej wersji.
- Rejestr `status` jest nieważny przez ok. 10 s po starcie PLC (NO_DATA) i ok. 3 s po przerwie RS485; w tym czasie brak pomiarów to zachowanie
  oczekiwane, nie błąd.
- `deny Grep` z podanym wzorcem może nie być rozpoznawany przez to narzędzie; sprawdzam na atrapie, a nie na prawdziwym `.env`.
- Kod trafia na `main` przed testami na komputerze (zatwierdzone w k2); poprawki kolejnymi commitami.
- Zegar komputera jest zsynchronizowany (potwierdzone w k1); dryf zegara przesuwa wszystkie `ts` jednakowo.

## Jak sprawdzę, że działa

1. R2-U1: `stat` i `find` bez wyników dla plików nieczytelnych; `git status` czysty; `.env` 600.
2. R2-U3: atrapa `docs/decoy/.env` niedostępna dla Read ani Grep; atrapa usunięta.
3. pytest: wszystkie testy zielone (liczba i czas w raporcie), w tym `test_no_write.py`: kody funkcji tylko `{4}`.
4. `docker compose config --quiet` i budowa obrazu `collector`; proces w kontenerze jako nie-root; import pakietu.
5. `free -m` w trakcie testów; `StartedAt` smartWARE bez zmian; `ss -ltn` bez zmian (collector nie wystawia portów).
6. Nic nie łączy się z PLC w tym kroku.

## Poza zakresem

Start collectora na sprzęcie i test na prawdziwym PLC (k5), ingest (k4), agregaty (k6), Grafana (k7), autostart po restarcie
komputera (k8), drugi licznik w konfiguracji produkcyjnej (testy używają go tylko syntetycznie), OPC UA (interfejs `SourceDriver`
tylko przygotowuje miejsce), zmiany w PLC i `docs/modbus-map.md`.
