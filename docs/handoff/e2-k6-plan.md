# e2-k6 plan: poprawki collectora (krok 0) i agregaty energii
Status: DO PRZEGLĄDU

Podstawa: `e2-plc1-diag-review.md` (decyzja: diagnoza E2-PLC1 odłożona, **bez osobnego k5b**; jego zakres wchodzi do kroku 0 tego planu), `e2-k5-report-review.md` (U-2, U-3, U-4 i „Zadania przenoszone” dla k6),
`e2-plc1-diag.md`, `e2-k0-plan.md` i `e2-k0-review.md` (D6, D7, U7, retencje), `docs/data-model.md`, `db/migrations/001_core.sql`, `docs/status-codes.md`, `config/devices.yaml`, `CLAUDE.md`.
**Bez testów fizycznych:** nic nie odłączamy, nie zatrzymujemy programu PLC, nie ruszamy PLC ani licznika. Do PLC z komputera nadal wyłącznie FC04 (collector i ewentualnie `mbpoll -t 3`).

## Cel kroku

1. **Krok 0 (collector):** `link_status` w awarii co sekundę, bez luk po 3 s; wyciszony szum pymodbus; log i metryka `meter_error_code`; opisy kodów w `docs/status-codes.md`.
2. **Agregaty:** ciągłe agregaty `energy_1m` i `energy_1h` z **całką mocy**, **pokryciem (`coverage`)** i **przyrostem licznika wzorcowego**, kompresja i retencja, widoki liczące wartości pochodne oraz widok porównujący całkę z licznikiem na dobie.

**Sprawdzalny wynik:** pytest zielony na komputerze (collector, ingest, agregaty); collector po poprawce pracuje stabilnie i publikuje 13 wierszy na sekundę przy sprawnym liczniku (5 przy `meter_status` ≠ 0, 1 przy awarii PLC, bez luk);
agregaty w prawdziwej bazie zgadzają się dokładnie z zapytaniami po surowych danych; polityki kompresji i retencji widoczne w katalogu; `app_reader` czyta agregaty i widoki, `app_writer` ich nie zmienia.

## Tryb wykonania

Jak w k1–k5: `ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null`), **bez `sudo`**, bez ruszania smartWARE, demona Dockera i `docker system prune`; `docker compose down -v` tylko za zgodą. Nie wypisuję `.env`. Raport bez sekretów. Po każdym `git pull` kontrola praw wg `docs/ops`.
Oczekiwanie na zdarzenia przez pętlę z warunkiem (nie samo `sleep`), długie operacje w tle przez `setsid`.

## Co powstaje / zmienia się (pliki)

```
services/collector/src/collector/main.py        pętla: odczyt jako zadanie w tle, status co okres; wyciszenie pymodbus
services/collector/src/collector/evaluator.py   metryka meter_error_code, stan „odczyt w toku”
services/collector/src/collector/status.py      nazwy znanych kodów błędów (log)
services/collector/src/collector/statelog.py    log zmiany kodu błędu
config/devices.yaml                             diagnostics.error_code.metric: meter_error_code; resolution_wh licznika
services/ingest/src/ingest/config.py            meta urządzeń: poll_interval_s, energy_resolution_wh
docs/status-codes.md                            U-3, kody meter_error_code, model wierszy 13/5
db/migrations/002_energy_aggregates.sql         energy_1m, energy_1h, polityki odświeżania, kompresji i retencji (bez transakcji)
db/migrations/003_energy_views.sql              widoki energy_1m_calc, energy_1h_calc, energy_daily_check, uprawnienia
docs/data-model.md                              definicje agregatów, pokrycia, całki, przyrostu, retencji
docs/ops/jumo-ipc-setup.md                      odświeżanie ręczne po wypełnianiu historii, polityki
tests/collector/…                               nowe i zmienione testy (patrz niżej)
tests/ingest/…                                  test meta urządzeń
tests/db/test_energy_aggregates.py, test_energy_views.py, test_energy_policies.py
docs/handoff/e2-k6-report.md
```

## Krok 0: poprawki collectora

### 0.1 Luki `link_status` w awarii (U-2)

**Przyczyna (z k5):** próba ponownego połączenia lub odczytu do nieodpowiadającego PLC blokuje pętlę do `timeout_s` + 1 s (3 s), więc w tym cyklu nic się nie publikuje (80,6% sekund z wierszem; luki 3,00 s co ok. 12 s).

**Rozwiązanie (K6-a):** odczyt z PLC (`driver.read()`, łącznie z łączeniem) działa jako **zadanie w tle**, a pętla co okres publikuje wynik:
- w każdym cyklu pętla czeka na zadanie najwyżej do końca bieżącego okresu; jeśli odczyt zdążył, wynik jest oceniany jak dotąd;
- jeśli odczyt nadal trwa (blokada połączenia lub timeout), pętla w tym cyklu zgłasza „PLC offline” (`on_read_failed`, które przy okazji zeruje śledzenie heartbeatu, więc powrót wymaga rozgrzewki jak w k3) i publikuje `link_status` = 1;
  zadanie nie jest przerywane: jego wynik zostanie przetworzony w jednym z następnych cykli (późny sukces = rozgrzewka, późny błąd = tylko log);
- nigdy nie startuje drugi odczyt, gdy poprzedni trwa; przy zatrzymaniu zadanie jest anulowane i nic nie wisi.
Reguły ważności, kolejność oceny i FC04 pozostają bez zmian; wykrycie offline nadal ≤ `timeout_s` + 1 s (teraz zwykle ok. 1 okres po ostatnim poprawnym odczycie).

**Testy:**
- atrapa „czarna dziura” (fabryka klienta, której `connect()` nigdy się nie kończy) oraz `SilentServer` (połączenie przyjęte, brak odpowiedzi): w teście skróconych okresów (np. okres 0,2 s, timeout 1,0 s) **co najmniej 95% okresów ma wiersz `link_status`**, a w awarii nie ma żadnego innego wiersza;
- wykrycie offline ≤ `timeout_s` + 1 s od chwili awarii;
- powrót po awarii: rozgrzewka jednego cyklu, potem komplet 13 wierszy, bez dwukrotnej publikacji tego samego cyklu;
- późny sukces i późny błąd zadania w tle, anulowanie przy `stop` (brak zadań wiszących po zatrzymaniu), brak równoległych odczytów;
- wszystkie testy k3 (kody funkcji tylko FC04, brak zapisu, reguły ważności, bufor MQTT) zielone bez zmian oczekiwań, poza świadomie zmienionymi (niżej).

### 0.2 Wyciszenie pymodbus (U-4)

**Mechanizm (sprawdzony w kodzie biblioteki):** surowe linie `>>>>> send:`/`recv:` to ostatnie ramki, które pymodbus (`Log.error`) dopisuje do każdego komunikatu `ERROR` na loggerze `pymodbus.logging`; logger dziedziczy poziom po `pymodbus`.
Ustawienie loggera `pymodbus` na **`CRITICAL`** (zamiast dzisiejszego `ERROR`) usuwa zarówno wpisy `ERROR pymodbus.logging`, jak i surowe ramki. Zdarzenia stanu i tak loguje `StateLogger`, a pierwszą przyczynę odczytu collector loguje sam.
**Test:** po `_setup_logging` poziom `pymodbus` to `CRITICAL`; uruchomienie sterownika przeciw `SilentServer` przy poziomie ogólnym `DEBUG` (przechwycenie logu i `capfd`) nie zostawia w wyjściu żadnych linii z `pymodbus` ani z `>>>>>`.

### 0.3 Log i metryka `meter_error_code` (decyzja z review plc1)

- **Metryka:** `meter_error_code` (surowa wartość rejestru 11) publikowana **tylko przy `meter_status` ≠ 0** (także przy `NO_DATA`); przy statusie 0 nie jest publikowana. Nazwa w `devices.yaml` (`diagnostics.error_code.metric`), zgodna z `^[a-z0-9_]+$`; jednostka pusta.
  Skutek dla modelu wierszy: **sekunda z błędem licznika ma 5 wierszy** (`link_status`, `meter_status`, `meter_error_count`, `meter_data_age_ms`, `meter_error_code`), a nie 4; sprawny licznik nadal 13. Zaktualizuję model w `docs/status-codes.md` i w testach (13/5).
- **Log:** przy przejściu do `COMM_ERROR` i przy **każdej zmianie kodu** w trakcie błędu wpis z kodem w postaci liczbowej, szesnastkowej i nazwy, jeśli jest znana, np. `meter:finder_7m24_1: OK -> COMM_ERROR (error_code=162, 0xA2, RESPONSE_CRC_FAIL)`.
  Implementacja przez szczegół stanu w `StateLogger` (stan = nazwa + kod), tak aby zmiana kodu była zmianą stanu, a przypomnienie co 60 s zostało bez zmian.
- **Nazwy kodów (K6-b):** mała tablica w `status.py` dla trzech kodów z dokumentacji CODESYS `MB_ErrorCodes` podanych w review plc1: 161 (16#A1) `RESPONSE_TIMEOUT`, 162 (16#A2) `RESPONSE_CRC_FAIL`, 163 (16#A3) `RESPONSE_WRONG_SLAVE`; kod spoza tablicy loguje się liczbowo, bez nazwy.
  Źródło (dokumentacja biblioteki) podaję za review; sam go nie weryfikowałem. Test zgodności tablicy z `docs/status-codes.md`.
- **Testy:** ewaluator (metryka przy statusie 1, 2, 10 i nieznanym; brak przy 0; `omit_value` bez zmian), konfiguracja (`metric` obowiązkowe tylko tam, gdzie je podano), log przy zmianie kodu (jeden wpis na zmianę, nie na cykl), e2e z prawdziwym brokerem (komplet 5 wierszy w sekundzie z błędem, wartość 162 z atrapy), brak `error_code` w sekundzie ze sprawnym licznikiem.

### 0.4 `docs/status-codes.md`

- **U-3:** Stop programu w CODESYS: serwer Modbus TCP nie odpowiada → `link_status` = 1. Kod 2 dotyczy sytuacji, w której serwer odpowiada, a heartbeat stoi (np. zawieszony MainTask); na variTRON 300 nie zaobserwowano. Stop/Start jest „gorący”: heartbeat i `error_count` nie są zerowane, a `NO_DATA` po Start nie występuje.
- Nowa sekcja `meter_error_code` (kody 161/162/163 z uwagą o źródle, obserwowane 162 w epizodach co 64 s, wzmianka o kodzie 0 przy statusie OK).
- Model wierszy 13/5, ciągłość `link_status` w awarii (po poprawce), zachowanie po zaniku zasilania (autostart, rozgrzewka) jako krótka notka.
- Rozszerzony test zgodności dokumentu z enumami i tablicą kodów.

### 0.5 Wdrożenie i obserwacja (bez testów fizycznych)

Po zielonych testach na komputerze: `docker compose up -d --build collector` (własny kontener; ingest i reszta stosu bez ruszania). Obserwacja **20 minut** (zdarzenia stanu licznika dzieją się same: epizody co 64 s były obecne w danych k5 i po 11:01 w dniu diagnostyki, ale nie mam gwarancji, że wystąpią):
brak luk w `link_status` (ciągłość 1 wiersza na sekundę), brak linii pymodbus w logu, `healthy`, zasoby; jeśli epizod wystąpi: log z kodem i metryka `meter_error_code` w bazie (wartość 162 oczekiwana, ale to obserwacja, nie wymóg), 5 wierszy na sekundę błędu.
Jeśli w 20 minutach nie wystąpi żaden epizod, zapisuję w raporcie, że ścieżka błędu na żywo nie została zaobserwowana (sprawdzona wyłącznie testami z atrapą). Poprawki luk `link_status` na prawdziwym PLC bez odłączania kabla nie da się sprawdzić na żywo (to byłby test fizyczny), więc ta poprawka jest weryfikowana atrapą „czarna dziura”.

## Agregaty energii

### Zasady i założenia

- Agregaty ciągłe nazywają się **`energy_1m` i `energy_1h`** (architektura, `CLAUDE.md`) i przechowują wyłącznie wartości addytywne lub odtwarzalne (sumy, liczności, minima, maksima, pierwsze i ostatnie): tylko takie można poprawnie złożyć w agregat godzinny. **Wartości pochodne** (średnie, całka, pokrycie, przyrost) liczą widoki `energy_1m_calc`, `energy_1h_calc` (K6-c).
- **Luki są normalnym stanem danych** (epizody co 64 s, awarie, zaniki zasilania): całka liczy energię tylko z obecnych próbek, **bez interpolacji przez luki**; `coverage` mówi, jaka część okna ma pomiar.
- Okres próbkowania i rozdzielczość licznika **nie są stałymi w SQL** (reguła 3): `poll_interval_s` (z `plc.poll_interval_s`) i `energy_resolution_wh` (z profilu licznika w `devices.yaml`, obecnie 100 Wh) trafiają do `devices.meta` przy synchronizacji ingestu (K6-d), a widoki biorą je stamtąd.
  Brak wartości w `meta` daje NULL w kolumnach pochodnych, a nie cichy domysł.
- Czas: wiaderka w UTC; tylko widok dobowy używa lokalnej doby `Europe/Warsaw` (K6-e).

### `energy_1m` (urządzenie × minuta, agregat ciągły nad `measurements`)

Pivot metryk przez `FILTER (WHERE metric = …)` i `WHERE metric IN (…)` (bez `link_status`, więc `plc-01` nie generuje wierszy):

| Kolumny | Zawartość |
| --- | --- |
| `bucket`, `device_id` | klucz |
| `active_power_n`, `_sum`, `_min`, `_max` | liczba próbek (sekund z pomiarem), suma, minimum, maksimum mocy czynnej |
| `voltage_n`, `_sum`, `_min`, `_max`; `current_n`, `_sum`, `_min`, `_max` | jak wyżej dla napięcia i prądu |
| `reactive_power_n/_sum`, `apparent_power_n/_sum`, `power_factor_n/_sum`, `frequency_n/_sum` | liczność i suma (średnia w widoku) |
| `import_first`, `import_last`, `import_min`, `import_max`; `export_first`, `export_last`, `export_min`, `export_max` | stan licznika energii pobranej i oddanej (Wh) |
| `meter_error_seconds`, `meter_status_n` | sekundy ze `meter_status` ≠ 0 i liczba sekund z jakimkolwiek statusem |

### `energy_1h`

Agregat **hierarchiczny** nad `energy_1m` (sumy sum, liczności, min z min, max z max, `first(import_first, bucket)`, `last(import_last, bucket)`). Jeśli TimescaleDB 2.32.1 nie pozwoli na agregat z agregatu (lub na `first`/`last` z `FILTER`), plan awaryjny (K6-h):
`energy_1h` liczony bezpośrednio z `measurements`, z tymi samymi kolumnami. Rozstrzyga krótki spike na początku kroku (niżej).

### Widoki pochodne

- **`energy_1m_calc`, `energy_1h_calc`:**
  - `*_avg` = suma / liczność (NULL przy 0);
  - **`energy_integral_wh`** = `active_power_sum × poll_interval_s / 3600` (całka z obecnych próbek);
  - **`coverage`** = `LEAST(1, active_power_n × poll_interval_s / długość_okna_s)` (60 lub 3600; wiaderko w toku ma `coverage` < 1 z natury, bo okno jeszcze trwa);
  - **`energy_import_delta_wh`** (i `energy_export_delta_wh`): przyrost licznika wzorcowego = `import_last` − `import_last` poprzedniego wiaderka tego urządzenia (`LAG`, bez `timescaledb_toolkit`, D6);
    przy resecie (`import_last` < poprzednie) przyrost = `import_last` i flaga **`import_reset`**; dla pierwszego wiaderka urządzenia `import_last − import_first`; flaga **`gap_before`** gdy odstęp od poprzedniego wiaderka przekracza okno (przyrost obejmuje wtedy czas, w którym nie było pomiarów, a całka go nie widzi);
  - `meter_error_seconds`, `meter_error_share`.
- **`energy_daily_check`** (urządzenie × lokalna doba `Europe/Warsaw`, nad `energy_1h_calc`): `integral_wh`, `coverage` (ważone, z uwzględnieniem długości doby przy zmianie czasu), `counter_delta_wh`, `integral_extrapolated_wh` (= całka / pokrycie; NULL przy pokryciu < 0,5), `diff_wh` (= ekstrapolowana całka − przyrost licznika),
  `resolution_wh` (z `meta`), **`within_resolution`** (|`diff_wh`| ≤ `resolution_wh`), **`deviation_pct`** (tylko gdy `counter_delta_wh` ≥ 5 × `resolution_wh`, inaczej NULL), `day_complete` (doba zamknięta), `gap_before_count`.

**Kwantyzacja licznika (ważne dla odczytu widoku):** licznik zmienia stan co 100 Wh, a obecne obciążenie to ok. 7 W (ok. 170 Wh na dobę), więc przyrost dobowy to 1–2 kroki i błąd względny dochodzi do kilkudziesięciu procent. Dlatego pierwszą miarą zgodności jest `within_resolution` (różnica nie większa niż jeden krok licznika),
a procentowa odchyłka (U7) jest podawana tylko tam, gdzie ma sens (≥ 5 kroków), np. po kilku dobach lub przy większym obciążeniu. To doprecyzowanie U7; decyzja K6-e. Rejestry o podwyższonej rozdzielczości (30462–30485) zostają na etap 4, przed wyborem źródła kosztów.

### Polityki (K6-f)

| Obiekt | Odświeżanie (start_offset / end_offset / okres) | Kompresja | Retencja |
| --- | --- | --- | --- |
| `measurements` (bez zmian z k2) | n/d | po 1 dobie | 90 dni |
| `energy_1m` | 7 dni / 1 minuta / 1 minuta | po 14 dniach (`segmentby = device_id`) | **1 rok** |
| `energy_1h` | 30 dni / 1 godzina / 15 minut | po 60 dniach (`segmentby = device_id`) | **brak limitu** |

Uzasadnienie: okna odświeżania są **krótsze niż retencja surowych danych (90 dni)**, więc usunięcie starych surowych kawałków nie kasuje zmaterializowanych wiaderek, a kompresja następuje **po** oknie odświeżania (odświeżanie skompresowanego zakresu wymagałoby jego rozpakowania).
Wiaderka starsze niż okno odświeżania nie są odświeżane przez politykę: po zapisie danych z odległej przeszłości (np. wypełnianie historii w etapie 3) trzeba wywołać `CALL refresh_continuous_aggregate(...)` ręcznie; zapisane w `docs/ops` i w danych dla etapu 3.
Agregaty działają w trybie czasu rzeczywistego (`materialized_only = false`), żeby Grafana (k7) widziała bieżącą minutę. Pierwsze zmaterializowanie istniejących danych: jedno `CALL refresh_continuous_aggregate` w migracji.

### Migracje

`002_energy_aggregates.sql` (`-- migrate: no-transaction`, instrukcje rozdzielone `-- migrate: next`, bo agregatów ciągłych nie można tworzyć w transakcji; to **pierwsze prawdziwe użycie** tego trybu runnera, zweryfikowane testem z k2 tylko na `CREATE INDEX CONCURRENTLY`): tworzenie agregatów `WITH NO DATA`,
ustawienie trybu czasu rzeczywistego, polityki odświeżania, kompresji i retencji, pierwsze odświeżenie. `003_energy_views.sql` (transakcyjna): widoki i uprawnienia (`SELECT` dla `app_reader`, domyślne uprawnienia z k2 plus końcowy `GRANT` przez `migrate`; `app_writer` bez uprawnień do zmian).
Sumy kontrolne i kolejność jak dotąd; testy sprawdzają idempotencję ponownego `migrate`.

### Zmiana w ingeście (K6-d)

Synchronizacja `devices` dopisuje do `meta` licznika `poll_interval_s` (z `plc.poll_interval_s`) i `energy_resolution_wh` (z `devices.yaml`, profil `finder_7m24`, pole `resolution_wh` przy `energy_import_wh` i `energy_export_wh`, 100). Test `test_devices_sync.py` i parser configu zaktualizowane; kolektor ignoruje nowe pole.
Wdrożenie: `docker compose up -d --build ingest`; ingest synchronizuje `devices` przy starcie (K4-f), bez przerwy w danych poza kilkusekundowym restartem (wiadomości czekają w sesji trwałej).

## Testy pytest bez sprzętu (agregaty)

Dane syntetyczne wstawiane do `measurements` w świeżej bazie testowej (`aip-test`), po `CALL refresh_continuous_aggregate`; wyniki porównywane z zapytaniami po surowych danych.

| Plik | Co sprawdza |
| --- | --- |
| `test_energy_aggregates.py` | `active_power_n/_sum/_min/_max`, napięcie, prąd, `import_first/last/min/max` dokładnie jak z surowych danych; pivot nie wytwarza wierszy dla `plc-01`; **właściwość: `energy_1h` = przeliczenie z surowych danych** (losowe dane z lukami, kilka godzin); agregat godzinny złożony z minutowych równa się liczonemu wprost; czas rzeczywisty: najnowsze, jeszcze nieodświeżone wiaderko jest widoczne; dane z opóźnieniem po odświeżeniu → ponowne odświeżenie koryguje wiaderko; skompresowany surowy kawałek i odświeżenie dają ten sam wynik; usunięcie surowego kawałka (retencja) nie kasuje zmaterializowanych wiaderek przy odświeżeniu w oknie polityki |
| `test_energy_views.py` | całka = `suma × poll_interval_s / 3600` (dokładnie), `coverage` 1,0 przy pełnym minucie, 0,9333 przy 4 s luki, 0 przy braku próbek; brak interpolacji przez lukę (całka nie rośnie); przyrost licznika: zwykły, **reset** (`import_last` mniejsze od poprzedniego: przyrost = `import_last`, flaga), `gap_before`, pierwsze wiaderko; `meta` bez `poll_interval_s` → NULL, nie domysł; widok dobowy: `within_resolution` prawdziwe przy zgodnej dobie z pokryciem 0,95, fałszywe przy różnicy 300 Wh, `deviation_pct` NULL przy małym przyroście, `day_complete`, doba ze zmianą czasu (23 i 25 godzin) |
| `test_energy_policies.py` | polityki w `timescaledb_information.jobs` (odświeżanie 7 dni/1 min dla minutowego i 30 dni/1 h dla godzinowego, kompresja po 14 i 60 dniach, retencja 1 rok i brak retencji dla godzinowego); okna odświeżania krótsze niż 90 dni; `app_reader` czyta agregaty i widoki, `app_writer` nie może ich zmieniać; ponowny `migrate` nic nie zmienia; runner bez transakcji tworzy agregat |
| ingest, collector | jak w Kroku 0 |

## Kroki wykonania k6

1. **Krok 0** (collector): kod i testy na laptopie, commit, pełny zestaw na komputerze, `up -d --build collector`, obserwacja 20 minut. Hash i wyniki do raportu.
2. **Ingest:** meta urządzeń, test, wdrożenie ingestu.
3. **Spike** (w projekcie `aip-test`, bez śladu w produkcji): czy TimescaleDB 2.32.1 pozwala na `FILTER` z `first`/`last`, agregat hierarchiczny, kompresję agregatu ciągłego i tryb czasu rzeczywistego razem; wynik wpisuję do raportu, a przy ograniczeniu stosuję plan awaryjny (K6-h).
4. **Migracje 002 i 003**, testy agregatów i widoków na komputerze.
5. **Wdrożenie:** `docker compose up -d --build` (migrate stosuje migracje i pierwsze odświeżenie na prawdziwych danych), potem kontrola na prawdziwych danych (niżej).
6. **Dokumenty:** `docs/data-model.md`, `docs/status-codes.md`, `docs/ops`.
7. Raport `e2-k6-report.md`; commit; stop.

### Kontrola na prawdziwych danych (krok 5)

- liczba wiaderek `energy_1m` równa liczbie minut z danymi; suma `active_power_n` równa liczbie wierszy `active_power` w tym samym przedziale; suma `meter_error_seconds` w oknie referencyjnym k5 (22:41–22:51 UTC 23.11) równa **28** (28 sekund błędu licznika z raportu k5);
- `coverage` minut z epizodem 56/60 ≈ 0,933, minut bez epizodu 1,0 (zgodnie z modelem 13/4 z k5, bo dane sprzed poprawki collectora mają 4, nie 5, wierszy w sekundzie błędu);
- całka okna z widoku równa sumie z surowych danych liczonej bezpośrednio (do zaokrąglenia zmiennoprzecinkowego);
- `energy_daily_check` dla 23.11 i 24.11 jako informacja: obie doby niepełne, pokrycie wyraźnie poniżej 1 (zanik zasilania 7,6 godziny), `day_complete` fałszywe dla bieżącej doby; **nie traktuję wyniku jako kryterium zgodności** (kwantyzacja licznika, luki);
- polityki w katalogu, rozmiary agregatów, czas odświeżenia na obecnych danych (ok. 220 tys. wierszy), `app_reader` czyta widoki, `StartedAt` smartWARE bez zmian, `ss -ltn` bez nowych portów.

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| K6-a | Sposób usunięcia luk `link_status` | odczyt jako zadanie w tle, pętla co okres zgłasza „offline”, gdy odczyt trwa dłużej niż okres | Likwiduje wszystkie blokady (połączenie i odczyt), a nie tylko połączenie; reguły ważności bez zmian. Alternatywa (krótszy limit połączenia) zostawiłaby blokady rzędu limitu i nie pokryłaby timeoutu odczytu (przypadek Stop programu) |
| K6-b | Nazwy kodów błędów w logu | tablica trzech kodów w `status.py`, reszta liczbowo | Czytelny log przy 161/162/163; źródło (CODESYS `MB_ErrorCodes`) podane za review, nieweryfikowane przeze mnie |
| K6-c | Nazwy i podział | agregaty `energy_1m`, `energy_1h` z wartościami addytywnymi; kolumny pochodne w widokach `*_calc` | Zachowuje nazwy z architektury, a agregat godzinny można poprawnie złożyć z minutowego |
| K6-d | Okres próbkowania i rozdzielczość licznika | w `devices.meta` przez synchronizację ingestu z `devices.yaml` | Reguła 3: bez stałych w SQL; brak wartości daje NULL, a nie domysł |
| K6-e | Porównanie całki z licznikiem | `within_resolution` jako miara główna, `deviation_pct` tylko przy ≥ 5 krokach licznika; lokalna doba `Europe/Warsaw` jako stała widoku | Przy 7 W i 100 Wh dobowy błąd względny jest bezużyteczny; strefa jako stała widoku do czasu taryf w etapie 4 |
| K6-f | Polityki | 7 dni/1 min i kompresja 14 dni (minutowy); 30 dni/15 min i kompresja 60 dni (godzinowy); retencje 1 rok i brak | Okna odświeżania < 90 dni retencji surowych; kompresja po oknie odświeżania |
| K6-g | Czas rzeczywisty agregatów | włączony | Grafana (k7) widzi bieżącą minutę |
| K6-h | Gdyby agregat hierarchiczny lub `FILTER` z `first`/`last` były niedostępne | `energy_1h` liczony wprost z surowych danych | Plan awaryjny po spike'u; kolumny i widoki bez zmian |
| K6-i | Model wierszy po `meter_error_code` | 13 wierszy (sprawny), 5 (`meter_status` ≠ 0), 1 (PLC offline) | Wynika z K6-0.3; dokumenty i testy zaktualizowane |
| K6-j | Obserwacja collectora po poprawce | 20 minut, bez testów fizycznych; ścieżka błędu na żywo tylko jeśli epizod wystąpi | Bez odłączania nie wymuszę awarii; reszta pokryta atrapą |

## Przekazanie decyzji i uwag do tego planu

| Pozycja | Gdzie w planie |
| --- | --- |
| U-2 (luki `link_status`, ≥ 95% sekund, atrapa „czarna dziura”, wykrycie ≤ `timeout_s` + 1 s) | 0.1 |
| U-3 (Stop = kod 1, kod 2 nieobserwowany, Stop/Start gorący) | 0.4 |
| U-4 (wyciszenie pymodbus, `CRITICAL`) | 0.2 |
| `error_code` (log przy zmianie, metryka przy `meter_status` ≠ 0, w `devices.yaml`, z testem) | 0.3 |
| k6 z review k5: całka tylko z obecnych próbek, `coverage`, porównanie z licznikiem na dobie | Agregaty, widoki, `energy_daily_check` |
| D6 (przyrosty widokami z `LAG`, bez toolkit), D7 (całka i stan licznika), U7 (wzór całki, widok porównawczy z testem) | Widoki pochodne |
| Retencje z k0: `energy_1m` 1 rok, `energy_1h` bez limitu | Polityki |
| K2-U5, K3-U3, pasek stanu licznika | zadania k7, bez zmian |
| Logi Dockera po zaniku zasilania (`\x00`), autostart po zaniku zasilania | k8 (polecenie z `sudo` dla Grzegorza w planie k8) |
| E2-PLC1 (przyczyna błędów CRC) | odłożone decyzją Grzegorza; k6 obsługuje luki jako normalny stan danych |
| `.432`, `.gitignore ~$*` | wykonane przed planem (`4e5e95b`, `a8bb300`) |

## Ryzyka i założenia (bez potwierdzenia)

- **Ograniczenia agregatów ciągłych w TimescaleDB 2.32.1** (`FILTER` z `first`/`last`, agregat hierarchiczny, kompresja agregatu, czas rzeczywisty jednocześnie) nie są sprawdzone; stąd spike w kroku 3 i plan awaryjny K6-h.
- **Tryb migracji bez transakcji** był sprawdzony tylko na prostym przypadku; agregaty ciągłe to jego pierwsze prawdziwe użycie (rozdzielanie instrukcji znacznikiem `-- migrate: next`).
- **Źródło nazw kodów 161–163** to dokumentacja CODESYS podana w review plc1; w repo jej nie ma.
- Poprawki luk `link_status` na prawdziwym PLC nie sprawdzę na żywo bez testu fizycznego; zastępuje to atrapa „czarna dziura” i `SilentServer`. Jeśli epizod licznika nie wystąpi w 20 minutach, ścieżka błędu na żywo pozostanie nieobserwowana.
- Dane w prawdziwej bazie mają do czasu poprawki 4 wiersze w sekundzie błędu licznika (nie 5); agregaty nie zależą od `meter_error_code`.
- Kwantyzacja licznika (100 Wh) czyni dobową odchyłkę procentową nieinformatywną przy obecnym obciążeniu (K6-e).
- Wypełnianie historii w etapie 3 wymaga ręcznego odświeżenia agregatów (poza oknem polityki) i uwzględnienia retencji surowych danych 90 dni.
- Zmiana `devices.meta` zmienia dane w tabeli `devices` przy restarcie ingestu (aktualizacja istniejących wierszy); brak wpływu na pomiary.
- Przepustowość zapisu agregatów przy 13 wierszach na sekundę jest znikoma; pomiar czasu odświeżenia na obecnych danych w raporcie.

## Kryteria zaliczenia

| Kryterium | Wymóg |
| --- | --- |
| Luki `link_status` | w teście „czarna dziura” ≥ 95% okresów z wierszem, w awarii tylko `link_status`; wykrycie ≤ `timeout_s` + 1 s |
| pymodbus | brak linii pymodbus i `>>>>>` w wyjściu (test) |
| `meter_error_code` | metryka przy `meter_status` ≠ 0, log przy zmianie kodu, 5 wierszy w sekundzie błędu (test e2e) |
| Zasada 1 | testy k3 zielone: tylko FC04, brak zapisu |
| Agregaty | zgodność z zapytaniami po surowych danych (minutowy i godzinowy), czas rzeczywisty, korekta po opóźnionych danych |
| Całka i pokrycie | całka dokładnie `suma × poll_interval_s / 3600`; `coverage` zgodne z liczbą sekund z pomiarem; brak interpolacji przez luki |
| Licznik wzorcowy | przyrost zwykły, reset (flaga), `gap_before`; widok dobowy z `within_resolution` i warunkowym `deviation_pct` |
| Polityki | kompresja i retencja zgodne z tabelą; okna odświeżania < 90 dni |
| Uprawnienia i idempotencja | `app_reader` czyta, `app_writer` nie zmienia; ponowny `migrate` nic nie zmienia |
| Prawdziwe dane | sumy zgodne z surowymi, 28 s błędu w oknie referencyjnym, `app_reader` czyta widoki |
| Izolacja | `StartedAt` smartWARE bez zmian, brak nowych portów, kontrola praw po `pull` czysta |

## Poza zakresem

Testy fizyczne (odłączanie przewodów, kabli, Stop programu), przyczyna błędów CRC (E2-PLC1), zmiany w PLC i `docs/modbus-map.md`, Grafana (k7), restart komputera i naprawa logów Dockera (k8), wypełnianie historii i `pump_1m` (etap 3), taryfy, koszty i stany maszyn (etap 4), anomalie i alarmy (etap 5), źródło kosztów z rejestrów o podwyższonej rozdzielczości (etap 4).
