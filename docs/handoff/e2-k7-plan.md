# e2-k7 plan: Grafana, pięć dashboardów z danych, które już zbieramy
Status: DO PRZEGLĄDU

Podstawa: `e2-k6-report-review.md` (K6-U4 i punkty 2–6 zakresu k7), **`e2-k7-zakres.md` (rozszerzony zakres, zastępuje „Zakres k7” z review)**, `e2-k6-report.md`, `docs/status-codes.md`, `docs/data-model.md`, `config/devices.yaml`, `docker-compose.yml`, `.env.example`, `CLAUDE.md`.
Zasady twarde bez zmian: Grafana czyta bazę wyłącznie rolą `app_reader` (zasada 4), sekrety tylko w `.env` (zasada 6), dane urządzeń w `config/devices.yaml` (zasada 3), żadnych „przewidywań awarii” w nazwach (zasada 8), mem_limit każdego kontenera (zasada 2).
**Bez testów fizycznych** i bez zapisu do PLC (collector nadal tylko FC04). Nic nie zmieniam w PLC, `docs/modbus-map.md` ani w collectorze; nowe dane z licznika to osobny krok E2-PLC2 po k7.

## Cel kroku

1. Pomiar K6-U4: czy widoki `*_calc` mieszczą się w 1 s na syntetycznym roku danych (rozstrzyga, skąd panele biorą przyrost licznika).
2. Grafana w Compose (przypięta wersja, port 3000 w LAN, nie-root, bez dostępu anonimowego, `mem_limit`), źródło danych `app_reader`, provisioning jako kod.
3. Pięć dashboardów jako JSON w repo: **Przegląd**, **Licznik na żywo**, **Jakość energii**, **Energia i profil**, **Stan i diagnostyka**; zmienna `$device`; adnotacje okien testów i przerw.
4. Testy: wszystkie panele wykonują zapytania przez API Grafany na bazie testowej i na prawdziwej bazie; zapis przez źródło danych odrzucony; anonim odrzucony.

**Sprawdzalny wynik:** pytest zielony na komputerze; `docker compose up -d --build` stawia Grafanę `healthy`; każdy panel każdego dashboardu zwraca dane z prawdziwej bazy (lub świadomie „brak danych”); `ss -ltn` pokazuje tylko nowy port 3000. Zrzuty ekranu i logowanie z laptopa robi Grzegorz.

## Tryb wykonania

Jak w k1–k6: `ssh jumo@192.168.0.213` (Git Bash, `bash -s`, `</dev/null`), **bez `sudo`**, bez ruszania smartWARE, demona Dockera i `docker system prune`; `docker compose down -v` tylko za zgodą. Nie wypisuję `.env` ani wyniku `docker compose config`; hasło admina Grafany używam tylko wewnątrz kontenera (`$GF_SECURITY_ADMIN_PASSWORD` rozwijane przez powłokę kontenera), nigdy w poleceniu ani raporcie.
**Wniosek z review k6 (pkt 5):** na komputer trafia wyłącznie to, co jest w `origin/main` (`git pull --ff-only`), bez kopiowania plików przez `ssh`; zamiast tego kilka małych commitów (każdy wypychany za Twoją zgodą). `core.fileMode false` w klonie komputera dopisuję do `docs/ops`.
Oczekiwanie na zdarzenia przez pętlę z warunkiem, długie operacje w tle przez `setsid`.

## Co powstaje / zmienia się (pliki)

```
docker-compose.yml                          usługa grafana (obraz z digestem, 127.0.0.1 → 0.0.0.0:3000, mem_limit 384m, wolumen aip_grafana_data)
docker-compose.test.yml                     usługa grafana dla projektu aip-test (losowe hasła, ta sama konfiguracja i provisioning)
docker-compose.perf.yml                     tymczasowa baza do pomiaru K6-U4 (poza tmpfs, większy limit); usuwana po pomiarze
grafana/provisioning/datasources/aip.yaml   źródło danych TimescaleDB jako app_reader (maxOpenConns 5, maxIdleConns 2)
grafana/provisioning/dashboards/aip.yaml    dostawca dashboardów: folder „AI Predykcja”
grafana/dashboards/*.json                   5 dashboardów (generowane, patrz G7-b)
grafana/generate.py                         generator JSON: zapytania, progi i mapowania kodów w jednym miejscu
db/migrations/004_data_windows.sql          tabela data_windows (okna testów i przerw) + wpisy z k5; tylko SELECT dla app_reader
docs/grafana.md                             opis dashboardów, definicje wielkości, progi i ich edycja, logowanie, odtwarzanie
docs/ops/jumo-ipc-setup.md                  Grafana: port, hasło z .env, core.fileMode, kontrola praw po pull
docs/data-model.md                          tabela data_windows
.env.example                                GF_SECURITY_SECRET_KEY (jeśli G7-g zatwierdzone)
tests/db/test_energy_perf.py                pomiar K6-U4 (oznaczony slow, bez udziału w zwykłym przebiegu)
tests/grafana/…                             provisioning, uprawnienia, zapytania paneli, adnotacje, $device przy dwóch licznikach
docs/handoff/e2-k7-report.md
```

## Decyzje do podjęcia

| Id | Decyzja | Propozycja | Dlaczego |
| --- | --- | --- | --- |
| G7-a | Wersja Grafany | najnowsza stabilna wersja główna (nie `latest`), tag + digest wybrane i wpisane w kroku 2 po `docker pull` na komputerze | Nie zgaduję numeru i digestu (zasada 7); digest sprawdzam na komputerze i wpisuję do raportu. Plugin nie jest potrzebny: PostgreSQL, state timeline, heatmapa, histogram i tabela są wbudowane (komputer bez internetu) |
| G7-b | Źródło prawdy dla JSON | `grafana/generate.py` generuje 5 plików; **JSON jest commitowany**, test sprawdza, że wynik generatora równa się plikom w repo | Progi (230 V, ±10%, 50 Hz, ±0,2 Hz), mapowania kodów i wspólne fragmenty zapytań są w jednym miejscu; ręczne pięć dużych JSON-ów rozjeżdża się. Alternatywa: ręczny JSON, tańsza na starcie, droższa w utrzymaniu |
| G7-c | Mapa cieplna godzina × dzień tygodnia | transformacja „Grouping to matrix” + tabela z kolorowaniem komórek (wbudowane) | Panel „heatmap” Grafany wymaga osi czasu, a tu osie to godzina i dzień tygodnia; wtyczka (Business Charts) wymaga instalacji z internetu. Wygląd potwierdzę zrzutem (ryzyko niżej) |
| G7-d | Adnotacje okien | tabela `data_windows` (migracja 004, wpisy z tabeli „Okna testów” w `e2-k5-report.md`), zapytanie adnotacji po `$__timeFilter` | `config/annotations.yaml` nie jest źródłem, które Grafana umie czytać bez dodatkowej usługi; tabela jest tylko do odczytu dla `app_reader`, wpisy dodaje `migrate` (nowa migracja na każde nowe okno). Tabela `events` zostaje dla alarmów etapu 5 |
| G7-e | Gdzie testy paneli | pytest w `aip-test` uruchamia własną Grafanę (losowe hasła) na syntetycznych danych; na prawdziwej bazie ten sam przebieg przez `docker exec aip-grafana` z hasłem z env kontenera | Test deterministyczny (dwa liczniki, rok danych), a produkcja bez wypisywania hasła |
| G7-f | Progi i stałe jakości | zmienne dashboardu (tekstowe: `u_nom` 230, `u_band_pct` 10, `f_nom` 50, `f_band_hz` 0,2, `stale_s` 10), wartości domyślne z `generate.py`, opis w `docs/grafana.md` | Zmiana bez edycji zapytań; pasmo ±10% to wartość orientacyjna, nie ocena zgodności z normą (opis panelu) |
| G7-g | `GF_SECURITY_SECRET_KEY` | nowy sekret w `.env` na komputerze, wygenerowany `openssl rand -hex 16` i dopisany bez wypisywania | Bez niego Grafana szyfruje dane wrażliwe domyślnym, publicznie znanym kluczem. Zmiana `.env` za Twoją zgodą; hasło `app_reader` i tak jest podawane z env przy każdym starcie |
| G7-h | Ekspozycja portu | `3000:3000` na wszystkich interfejsach hosta, bez TLS (LAN przemysłowy) | Wymóg zakresu (port 3000 w LAN). Ruch i hasło idą jawnie po LAN; to ryzyko do świadomej akceptacji, TLS dopiero w etapie 7 |
| G7-i | Strefa i język | `GF_DATE_FORMATS_DEFAULT_TIMEZONE=Europe/Warsaw`, `timezone` w JSON, `GF_USERS_DEFAULT_LANGUAGE=pl-PL` | Polski interfejs, jeśli wybrana wersja go ma (sprawdzam w kroku 2; w razie braku zostaje angielski, a treści paneli są i tak po polsku) |
| G7-j | Wyłączenia sieciowe | wyłączone: sprawdzanie aktualizacji, telemetria, wiadomości, gravatar, rejestracja, anonim, osadzanie | Komputer działa bez internetu; mniej powierzchni i mniej prób połączeń na zewnątrz |

## Krok 1: pomiar K6-U4 (przed jakąkolwiek Grafaną)

- Tymczasowy `docker-compose.perf.yml` w projekcie `aip-test`: baza bez tmpfs (wolumen usuwany po teście), `mem_limit` 1 GiB (zwykła baza testowa ma 512 MB w tmpfs, a rok danych się w niej nie zmieści).
- Dane syntetyczne po stronie serwera (`generate_series`): **jeden wiersz na minutę** na metrykę (moc czynna i bierna, pozorna, napięcie, prąd, cos φ, częstotliwość, energia pobrana i oddana, `meter_status`) przez 365 dni dla jednego licznika, z losowymi lukami, kilkoma resetami licznika i dobą ze zmianą czasu; po tym odświeżenie agregatów. Daje to ok. 525 tys. wiaderek `energy_1m` i ok. 8,8 tys. `energy_1h`.
  Ponieważ jeden wiersz na minutę oznacza `coverage` ≈ 1/60, pomiar dotyczy **kosztu zapytań**, nie wartości energii; wartości pokrycia w tym teście nie są kryterium.
- Mierzone zapytania (z `EXPLAIN (ANALYZE)` i czasem całkowitym): 24 h z `energy_1m_calc`, 30 dni z `energy_1h_calc`, `energy_daily_check` (cały rok), a po zbudowaniu dashboardów także zapytania paneli „Jakość energii” i „Energia i profil” na tym roku (< 1 s każde, wymóg zakresu).
- **Reguła decyzji:** wszystkie < 1 s → panele mogą czytać widoki `*_calc`. Którekolwiek ≥ 1 s → panele liczą przyrost `LAG` w zapytaniu ograniczonym zakresem z jednym wiaderkiem zapasu (pierwsze wiaderko zakresu nie dostaje sztucznego „pierwszego wiaderka urządzenia”), a widoki zostają dla analityki. Wynik i rozmiar bazy syntetycznej trafiają do raportu; baza perf jest usuwana.
- Jeśli rok się nie zmieści w pamięci lub czasie, zmniejszam do 6 miesięcy i **piszę to w raporcie** (pomiar skalowania, nie wniosek z jednej doby).

## Krok 2: Grafana w Compose

- Usługa `grafana`: obraz z G7-a (tag + digest), `container_name: aip-grafana`, sieć `backend`, `restart: unless-stopped`, `mem_limit: 384m` (suma limitów `aip-` po k7 ≈ 2240 MB bez jednorazowego `migrate`), `logging` jak pozostałe, healthcheck na `/api/health`.
- Nie-root: obraz domyślnie działa jako użytkownik 472; wolumen `aip_grafana_data` (SQLite Grafany), provisioning i dashboardy montowane tylko do odczytu z repo (`./grafana/...`), prawa 644/755 (kontrola po `pull` jak dotąd).
- Zmienne środowiska: `GF_SECURITY_ADMIN_USER/PASSWORD` z `.env` (`${…:?ustaw w .env}`), brak anonima (`GF_AUTH_ANONYMOUS_ENABLED=false`), brak rejestracji, osadzanie wyłączone, `GF_ANALYTICS_*`, `GF_NEWS_*`, aktualizacje i gravatar wyłączone (G7-j), strefa i język (G7-i), strona startowa = dashboard „Przegląd”, `APP_READER_PASSWORD` przekazane tylko po to, by provisioning podstawił je do źródła danych.
- Hasło admina z `.env` obowiązuje **przy pierwszym utworzeniu wolumenu** (jak hasło Postgresa); zmiana później wymaga `grafana cli` w kontenerze, nie edycji `.env`. To trafia do `docs/ops` (analogia do uwagi o `POSTGRES_PASSWORD`).
- Źródło danych (`provisioning/datasources/aip.yaml`): typ PostgreSQL z włączonym trybem TimescaleDB, host `timescaledb:5432`, baza i użytkownik `app_reader`, hasło z `$APP_READER_PASSWORD` (`secureJsonData`), `sslmode: disable` (sieć wewnętrzna Compose), `maxOpenConns` 5, `maxIdleConns` 2, `connMaxLifetime` 14400 s (K2-U5: rola ma `CONNECTION LIMIT 10`, a do czatu w etapie 6 zostaje zapas), `timeInterval` 1 s.
- Dostawca dashboardów: folder „AI Predykcja”, `updateIntervalSeconds` 30 (zmiana JSON po `git pull` pojawia się sama), `allowUiUpdates: true` (edycja w GUI do prób, **nie jest źródłem prawdy**, po restarcie wraca wersja z repo), `disableDeletion: true`.
- Wdrożenie: `docker compose up -d --build`, kontrola `healthy`, `ss -ltn` (nowy tylko port 3000), `StartedAt` smartWARE bez zmian, pomiar pamięci Grafany po 10 minutach.

## Krok 3: migracja `004_data_windows.sql` (adnotacje)

Tabela `data_windows (id BIGSERIAL PK, start_time TIMESTAMPTZ NOT NULL, end_time TIMESTAMPTZ NOT NULL CHECK (end_time >= start_time), kind TEXT NOT NULL, description TEXT NOT NULL)` z indeksem po `start_time`. Uprawnienia: `SELECT` dla `app_reader` (domyślne uprawnienia z k2 plus końcowy `GRANT` w `migrate`), `app_writer` bez dostępu.
Wpisy początkowe: **siedem okien z tabeli „Okna testów” w `e2-k5-report.md`** (`collector_start`, `calm_window`, `mqtt_broker_restart`, `collector_stopped`, `rs485_break`, `plc_lan1_unplugged`, `plc_program_stop`) oraz zanik zasilania (przedział wyznaczę z luki w `measurements`, w migracji wpisany jako stałe wartości po zweryfikowaniu na danych) i wdrożenie k6 (14:33:59–14:34:12 UTC, restart collectora i ingestu). Opisy po polsku.
**Pytanie do architekta:** czy tabela „Okna testów…” w dokumencie projektu 12 zawiera więcej okien niż w raporcie k5? Zakres k7 odwołuje się do dokumentu 12, którego nie mam w repo. Jeśli tak, proszę o wklejenie, a dopiszę je w migracji.
Dopisywanie okien w przyszłości: nowa migracja `INSERT` (przez `migrate`); to samo miejsce na okna E2-PLC2.

## Krok 4: dashboardy (`grafana/generate.py` → `grafana/dashboards/*.json`)

**Wspólne:** folder „AI Predykcja”; `uid` stałe (`aip-przeglad`, `aip-na-zywo`, `aip-jakosc`, `aip-energia`, `aip-diagnostyka`); `timezone: Europe/Warsaw`; zmienna `$device` (`SELECT device_id AS __value, name AS __text FROM devices WHERE kind = 'energy_meter' AND enabled ORDER BY 1`); linki między dashboardami z zachowaniem czasu i `$device`; tytuły, jednostki SI i `description` po polsku, z definicją wielkości; filtr czasu `$__timeFilter(...)`, grupowanie `$__timeGroupAlias(...)`; długie zakresy z `energy_1m` / `energy_1h`, nie z `measurements`.
**Luki:** wykresy nie łączą punktów przez luki (próg „Connect null values”: 5 s dla danych sekundowych, 150 s dla `energy_1m`, 2,5 h dla `energy_1h`), a zapytania nie zamieniają braku danych na zero (`NULLIF`, brak `COALESCE(…, 0)` dla wartości fizycznych).
**Stan PLC** (jedno `plc-01` w `devices`, `kind = 'plc'`; panele biorą je z tabeli, nie z literału). **Nazwy kodów:** `generate.py` czyta kody i komunikaty z `docs/status-codes.md` i `ERROR_CODE_NAMES`, więc mapowania w JSON nie rozjadą się z kodem; test porównuje je z dokumentem.
**Kafelek stanu licznika (K3-U3):** zapytanie bierze ostatni `link_status` i jego wiek oraz ostatni `meter_status` i jego wiek; wynik: **„Brak danych z PLC”**, gdy `link_status ≠ 0` albo ostatni `link_status` starszy niż `$stale_s` (10 s); w przeciwnym razie nazwa stanu licznika z `meter_status`, a „brak danych”, gdy ostatni `meter_status` jest starszy niż `$stale_s`. Wiek ostatniego `link_status` jest właściwą miarą świeżości, bo collector publikuje go co cykl także w awarii (k6).

| # | Dashboard i panele | Źródło i zapytanie (skrót) |
| --- | --- | --- |
| 1 | **Przegląd** (strona startowa, odświeżanie 30 s): moc czynna teraz; zużycie dziś i wczoraj z pokryciem; moc maksymalna dziś z godziną; średni cos φ dziś; stan PLC i licznika (kafelek K3-U3); pokrycie dziś; wiek ostatniego odczytu; liczba epizodów błędu licznika dziś | ostatnia wartość mocy z `measurements` (zakres 1 h); zużycie i pokrycie z `energy_daily_check` (doba `Europe/Warsaw`, zużycie to energia z obecnych próbek, **dolna granica przy pokryciu < 1**, opisane w panelu; obok `counter_delta_wh` licznika); maksimum: wiersz z największym `active_power_max` w `energy_1m` od północy lokalnej (czas z dokładnością do minuty); cos φ = `sum(power_factor_sum)/sum(power_factor_n)` z `energy_1m` od północy; wiek = `now() - max(time)`; epizody = liczba przejść `meter_status` 0 → ≠ 0 od północy (`LAG` po jednej metryce z jednej doby) |
| 2 | **Licznik na żywo** (odświeżanie 5 s, domyślnie 15 min): U, I, P, Q, S, PF, f jako wykresy i kafelki ostatniej wartości z min/maks./średnią w oknie | `measurements`, `$__timeGroupAlias(time, $__interval)` ze średnią; przy zakresach dłuższych niż 6 h opis kieruje do dashboardów „Jakość” i „Energia” |
| 3 | **Jakość energii:** napięcie (min/maks./średnia z `energy_1m`) ze strefami kolorów 230 V ±10%; odchyłka częstotliwości od 50 Hz; cos φ i stosunek Q/P; histogram napięcia; liczba minut z napięciem poza pasmem | `energy_1m` (`voltage_min/max`, `voltage_sum/voltage_n`, `frequency_sum/frequency_n − $f_nom`, `reactive_power_sum`/`active_power_sum` z `NULLIF`); histogram: koszyki 0,5 V liczone w SQL z średnich minutowych i wykres słupkowy; minuty poza pasmem: `count(*) WHERE voltage_min < u_nom·(1−p) OR voltage_max > u_nom·(1+p)`; opis: pasmo orientacyjne, nie ocena zgodności z normą |
| 4 | **Energia i profil:** zużycie na minutę / godzinę / dobę z pokryciem; mapa cieplna godzina × dzień tygodnia; dziś vs wczoraj i bieżący tydzień vs poprzedni; moc bazowa; tabela `energy_daily_check` | minuta: `energy_1m_calc`, godzina: `energy_1h_calc`, doba: `energy_daily_check` (wersje z wyborem źródła po zakresie, oddzielne panele, nie jeden przełącznik); mapa: `energy_1h` → dzień tygodnia i godzina lokalna, średnia moc, transformacja „Grouping to matrix”; porównania: druga seria z jawnym przesunięciem czasu w SQL (`bucket + interval '1 day'` / `'7 days'`, filtr `bucket BETWEEN $__timeFrom() − …`); **moc bazowa = 5. percentyl** średniej minutowej mocy w godzinach lokalnych 00:00–05:00 na dobę (definicja w opisie panelu); tabela: wszystkie kolumny widoku z `within_resolution`, `coverage`, `day_complete` |
| 5 | **Stan i diagnostyka:** oś stanów `link_status` i `meter_status` (kolory i nazwy z `docs/status-codes.md`); `meter_error_code` z nazwą (161/162/163); `meter_error_count`; `meter_data_age_ms`; sekundy bez danych na godzinę; adnotacje; (opcjonalnie) wiersze na minutę | state timeline z `measurements` (zmiany wartości); `meter_error_code` i `meter_error_count` z `measurements` (zakresy do doby); sekundy bez danych = `3600·(1 − coverage)` z `energy_1h_calc`, bieżąca godzina oznaczona przez `bucket_complete`; adnotacje z `data_windows`; wiersze na minutę: `count(*)` po minutach z `measurements`, zakres ograniczony do 24 h, pokazuje model 13 / 5 / 1 |

Epizod błędu licznika w panelu 1 odpowiada `meter_status` ≠ 0 (kod z PLC), bez rozróżniania przyczyny; brak pokrycia z powodu awarii PLC nie jest błędem licznika (opis jak w `docs/data-model.md`).

## Testy

**Bez sprzętu, w `aip-test` (pytest, osobny katalog `tests/grafana/`):** własna Grafana z provisioningiem z repo, baza z danymi syntetycznymi (dwa liczniki, kilka dni danych sekundowych i rok minutowych w bazie perf).

| Obszar | Co sprawdza |
| --- | --- |
| Provisioning | Grafana startuje `healthy`, 5 dashboardów w folderze „AI Predykcja”, źródło danych przechodzi „test połączenia”, w logu brak błędów provisioningu |
| Generator | wynik `generate.py` równa się JSON w repo (brak dryfu); mapowania kodów w JSON równają się `docs/status-codes.md` i `ERROR_CODE_NAMES`; w JSON brak fraz z zasady 8 („przewidywanie awarii”, „predykcja awarii”); każdy panel ma `description` i jednostkę |
| Uprawnienia | źródło danych jako `app_reader`: `INSERT`/`DELETE`/`CREATE` przez `/api/ds/query` odrzucone; `data_windows` czytelna, bez zapisu |
| Zapytania paneli | harness czyta każdy dashboard, podstawia zmienne (`$device`, progi, `from`/`to`), wysyła każdy target przez `/api/ds/query` i wymaga braku błędu oraz niepustej ramki lub świadomego „brak danych”; zakresy: 15 min, 6 h, 24 h, 7 dni, 30 dni |
| Dwa liczniki | `$device` wylicza dwa liczniki; zapytania dla drugiego zwracają jego dane i nie mieszają z pierwszym |
| Kafelek K3-U3 | przypadki: `link_status` 0 i świeży, `link_status` 1, ostatni `link_status` starszy niż 10 s, `meter_status` ≠ 0, ostatni `meter_status` starszy niż 10 s |
| Adnotacje | zapytanie adnotacji zwraca oczekiwane okna dla zakresu 23.11 22:30–23:10 UTC |
| Wydajność | zapytania paneli „Jakość” i „Energia i profil” na roku z kroku 1 < 1 s każde (test `slow`); „Licznik na żywo” na dobie danych sekundowych < 1 s |
| Dostęp | `/api/health` bez logowania działa, `/api/dashboards/home` i `/api/search` bez logowania zwracają 401, rejestracja wyłączona |

**Na komputerze (prawdziwa baza):** ten sam harness przez `docker exec aip-grafana` (hasło z env kontenera, bez wypisywania) dla każdego panelu każdego dashboardu na zakresach 15 min, 6 h, 24 h i 7 dni; wyniki w tabeli raportu (panel, czas, liczba wierszy). `ss -ltn` (tylko nowy port 3000), `docker stats` (pamięć Grafany względem 384 MB), `StartedAt` smartWARE bez zmian, kontrola praw po `pull`.

## Kroki wykonania k7

1. Commit review i zakresu (wykonany), po „ok” Grzegorza do tego planu: baza perf i pomiar K6-U4 (krok 1); wynik w commicie.
2. Usługa Grafana, provisioning źródła danych i pusty dostawca dashboardów, testy provisioningu i uprawnień, wdrożenie na komputerze (po `git pull --ff-only`), kontrola portów i pamięci. Dopisanie `GF_SECURITY_SECRET_KEY` do `.env` tylko za zgodą (G7-g).
3. Migracja 004 i testy adnotacji.
4. `generate.py` i dashboardy po kolei (Przegląd, Na żywo, Stan i diagnostyka, Jakość, Energia i profil), po każdym test harnessu zapytań i osobny mały commit.
5. Pomiar wydajności paneli na roku (krok 1), korekta zapytań, jeśli któreś ≥ 1 s.
6. Wdrożenie, harness na prawdziwej bazie, sprawdzenie wizualne w przeglądarce (jeśli panel przeglądarki ma dostęp do `192.168.0.213:3000`; w przeciwnym razie zostaje na zrzutach Grzegorza).
7. Dokumenty (`docs/grafana.md`, `docs/ops`, `docs/data-model.md`), raport `e2-k7-report.md`, commit, stop.

## Ryzyka i założenia (bez potwierdzenia)

- **Numer wersji i digest Grafany** nie są wybrane; wybór po `docker pull` na komputerze (G7-a). Zakładam, że komputer ma dostęp do rejestru obrazów przy kroku 2 (tak jak przy poprzednich obrazach); jeśli nie, zatrzymuję się i pytam.
- **Rozwijanie zmiennych środowiska w provisioningu** (`$APP_READER_PASSWORD`) i wersja pól źródła danych TimescaleDB zależą od wersji Grafany; sprawdzam testem „test połączenia”.
- **`/api/ds/query` z makrami** (`$__timeFilter`, `$__timeGroupAlias`) rozwija makra po stronie serwera, ale **nie** zmienne dashboardu: harness podstawia je sam, więc test nie wykryje błędu w zmiennych, które Grafana w GUI rozwija inaczej (np. wielokrotny wybór). Dlatego `$device` jest jednokrotnego wyboru.
- **Mapa cieplna przez „Grouping to matrix” + tabela** nie jest sprawdzona w żadnej wersji; jeśli nie zadziała, zamieniam na tabelę godzina × dzień z kolorowaniem komórek z danych już w macierzy (SQL `crosstab` niedostępny bez rozszerzenia, więc pivot w SQL przez `FILTER`) i opisuję w raporcie.
- **Język polski** interfejsu zależy od wersji.
- **Próg „Connect null values”** jest w panelach stały, a rzeczywisty odstęp zależy od `$__interval`; przy bardzo krótkich lub długich zakresach linia może się łączyć lub rwać inaczej, niż zakładam. Ocena wizualna na zrzutach.
- **Hasło admina z `.env` działa tylko przy pierwszym starcie wolumenu** Grafany; jeśli kiedyś wolumen zostanie utworzony ze starym hasłem, nie zadziała zmiana w `.env` (opis w `docs/ops`).
- **Jedno źródło danych, jedna rola `app_reader` z limitem 10 połączeń i `statement_timeout` 10 s:** dashboardy z wieloma zapytaniami mogą w złym przypadku trafić na limit; `maxOpenConns` 5 chroni czat z etapu 6 przed zagłodzeniem, a zapytania wolniejsze niż 10 s kończą się błędem w panelu (wykryje to test zakresów).
- **Tabela `data_windows` ma wpisy tylko z raportu k5**, a nie z dokumentu 12 (patrz pytanie wyżej).
- **Zużycie dziś/wczoraj z całki** jest dolną granicą przy braku pokrycia (zanik zasilania, luki); przyrost licznika (kwantyzacja 100 Wh) jest tylko uzupełnieniem, nie wartością główną.
- Ruch do Grafany jest jawny (HTTP) w LAN (G7-h).
- Szczegóły E2-PLC2 (THD, temperatura, czas pracy, energia bierna n2/n4) nie wchodzą do k7; dashboardy mają zostawić miejsce na te panele, bez pustych paneli „na zapas”.

## Kryteria zaliczenia

| Kryterium | Wymóg |
| --- | --- |
| Pomiar K6-U4 | czasy czterech zapytań na roku danych w raporcie, decyzja o widokach vs `LAG` zgodnie z regułą |
| Grafana | `healthy`, wersja z digestem, nie-root, `mem_limit` 384m, pamięć zmierzona, hasło admina tylko z `.env`, anonim i rejestracja wyłączone |
| Źródło danych | rola `app_reader`, `maxOpenConns` 5 i `maxIdleConns` 2, zapis odrzucony (test) |
| Provisioning | 5 dashboardów w folderze „AI Predykcja”, JSON w repo równy wynikowi generatora, edycja w GUI nie jest źródłem prawdy |
| Panele | każdy panel każdego dashboardu na prawdziwej bazie zwraca dane lub świadomie „brak danych”, bez błędów (tabela w raporcie) |
| Wydajność | zapytania paneli „Jakość” i „Energia i profil” na roku < 1 s; „Licznik na żywo” na dobie < 1 s |
| Stan licznika (K3-U3) | „Brak danych z PLC” przy `link_status ≠ 0` lub starych danych (test) |
| `$device` | działa przy dwóch licznikach (test) |
| Adnotacje | okna z `data_windows` zwracane dla zakresu testowego |
| Zasada 8 i język | brak fraz „przewidywanie awarii”; tytuły, opisy i jednostki po polsku |
| Izolacja | w `ss -ltn` tylko nowy port 3000, `StartedAt` smartWARE bez zmian, `git status` na komputerze czysty po `pull` |

## Czynności Grzegorza (po wdrożeniu)

1. Zalogować się z laptopa na `http://192.168.0.213:3000` (użytkownik i hasło z `GF_SECURITY_ADMIN_*` w `.env`; hasła w GUI nie zmieniamy).
2. Zrobić **zrzuty ekranu pięciu dashboardów** i zapisać w `docs/images/etap2/` (przy dłuższym zakresie czasu, np. ostatnie 24 h, żeby były dane).
3. Zgodzić się lub nie na dopisanie `GF_SECURITY_SECRET_KEY` do `.env` na komputerze (G7-g).

## Decyzje i pytania do architekta

1. G7-a…j (tabela wyżej), w szczególności **G7-b** (generator vs ręczny JSON), **G7-c** (mapa cieplna bez wtyczki), **G7-d** (tabela `data_windows`), **G7-h** (HTTP w LAN).
2. Czy dokument projektu 12 ma więcej „Okien testów…” niż tabela w `e2-k5-report.md` (patrz krok 3)?
3. Czy „zużycie dziś / wczoraj” ma być pokazywane jako energia z obecnych próbek (dolna granica, z pokryciem), czy dodatkowo jako wartość uzupełniona do pełnej doby (całka / pokrycie, tylko przy pokryciu ≥ 0,5, jak w `energy_daily_check`)? Proponuję pierwsze jako wartość główną i drugie jako wartość pomocnicza z opisem.

## Poza zakresem

Nowe dane z licznika i zmiany w PLC (E2-PLC2), alarmy i reguły Grafany (etap 5), koszty i taryfy w zł (etap 4), stany maszyn, anomalie i szacowanie dni do progu (etap 4), czat (etap 6), `pump_1m` i dane pomp (etap 3), TLS i odtwarzanie po zaniku zasilania (k8, etap 7), dokumentacja Word v2 (k8), testy fizyczne.
