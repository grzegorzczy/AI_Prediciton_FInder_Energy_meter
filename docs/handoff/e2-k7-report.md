# e2-k7 raport: Grafana, pięć dashboardów z danych, które już zbieramy
Status: DO PRZEGLĄDU

Wykonanie 24.11.2026 wg `e2-k7-plan.md`, `e2-k7-zakres.md` i `e2-k7-review.md` (czasy w UTC). Polecenia na `jumo-ipc` przez `ssh`, **bez `sudo`**, bez ruszania smartWARE, demona Dockera i `docker system prune`;
bez testów fizycznych i bez zapisu do PLC. **Na komputer trafiało wyłącznie to, co jest w `origin/main`** (`git pull --ff-only`; uwaga review k6 pkt 5), każdy push za Twoją zgodą (zgoda na cały k7 udzielona na początku).
`.env` nie był czytany ani wypisywany (tylko nazwy i długości zmiennych); hasło admina Grafany było używane wyłącznie wewnątrz kontenera (`docker exec`). Raport bez sekretów.

## Podsumowanie

Grafana 13.0.2 działa na komputerze (`healthy`, port 3000), z pięcioma dashboardami jako kod, źródłem danych `app_reader` i adnotacjami okien testów i przerw. **Wszystkie 200 zapytań paneli
(5 dashboardów × 4 zakresy) wykonało się na prawdziwej bazie bez błędu**, najwolniejsze w 0,33 s (łącznie z narzutem `docker exec`, ok. 0,13 s na zapytanie). Pełny zestaw testów: **407 z 407** (3 testy wydajnościowe są pomijane w zwykłym przebiegu, patrz niżej).

Najważniejsze ustalenia:
- **Pomiar K6-U4:** widok `energy_1m_calc` na roku danych trwa **ok. 17 s**, a `app_reader` ma limit 10 s, więc widok minutowy jest bezużyteczny dla Grafany; panele liczą więc przyrost licznika `LAG` w zapytaniu (**29 ms** dla 24 h). Reguła decyzji z planu zadziałała.
- **Na żywo potwierdzone `meter_error_code`:** w czasie k7 wróciły epizody błędu licznika (18 w ciągu 3 h, od 16:23 UTC); kod 161 w pierwszej sekundzie, potem 162 przez trzy sekundy, dokładnie 5 wierszy na sekundę błędu i wpisy w logu collectora zgodne z `docs/status-codes.md` (zamyka punkt otwarty z k6).
- **Nie sprawdziłem wyglądu paneli w przeglądarce** (patrz „Czego nie sprawdziłem”): wymagałoby to logowania hasłem admina, którego nie czytam.

## Co zrobiono

| Hash | Zawartość |
| --- | --- |
| `003c673` | review k7 |
| `6adc3f7`, `c8700cc` | pomiar K6-U4: `docker-compose.perf.yml`, `tests/run-perf.sh`, `tests/db/test_energy_perf.py` |
| `e968b7c` | usługa `grafana` w Compose (obraz z digestem), provisioning źródła danych i dostawcy dashboardów, `.env.example` |
| `b5411d7`, `9cb9d79`, `7951edd` | migracja 004, `grafana/generate.py`, 5 dashboardów, harness `tests/grafana/`, Grafana w `docker-compose.test.yml` |
| `d57ce25`, `2e76aa1`, `a863cb9` | poprawki testów, zapytania paneli na roku danych |
| `38e9d7a`, `fabc25c` | `docs/grafana.md`, sekcja w `docs/ops`, `data_windows` w `docs/data-model.md`; `last()` w tabeli „Wartości w oknie” |
| `30ca9f1`, `faab4a5`, `7869e6b` | sprawdzenie paneli na produkcji przez `docker exec`, symulacja otwartego dashboardu |
| `fe979cd`, `6a72da0`, `5bc40ed` | puste katalogi provisioningu, ponawianie odświeżenia w testach, ścisły test strony startowej |

Stan komputera po k7: `5bc40ed`, `git status` czysty, prawa plików poprawne (`.env` 600), obraz Grafany z digestem poniżej.

## Wyniki względem kryteriów zaliczenia

| Kryterium | Wynik |
| --- | --- |
| Pomiar K6-U4 | patrz tabela niżej; decyzja: panele liczą `LAG` w zapytaniu z zapasem 3 dni, widok minutowy zostaje (nieużywany przez panele) |
| Grafana | wersja **13.0.2**, `grafana/grafana-oss:13.0.2@sha256:5dad0df181cb644a14e13617b913b261a54f7d4fd4510721dba420929f35bea2`; `healthy`; użytkownik 472 (nie-root); `mem_limit` 384 MB; anonim (`/api/search`, `/api/dashboards/home`) zwraca 401; rejestracja wyłączona; hasło admina i klucz tylko z `.env` |
| Pamięć Grafany | po starcie 152 MiB; **po 10 min z symulacją otwartego „Licznik na żywo” (odświeżanie 5 s, 120 cykli × 15 zapytań): 164 → 175 MiB z 384 MiB**, stabilnie od 3. minuty, 0 błędów, najwolniejsze zapytanie 239 ms; po dalszych 40 min 137 MiB |
| Źródło danych | rola `app_reader`, `maxOpenConns` 5, `maxIdleConns` 2, TimescaleDB włączone, tylko do odczytu w Grafanie; „Database Connection OK” na produkcji; zapis przez źródło odrzucony (6 przypadków: `INSERT`, `DELETE`, `UPDATE`, `CREATE`, `DROP`, `CALL refresh…`) |
| Provisioning | 5 dashboardów w folderze „AI Predykcja”, JSON w repo równy wynikowi generatora (test), strona startowa = „Przegląd” (na produkcji i w teście) |
| Panele | na prawdziwej bazie: **200 zapytań, 0 błędów** (zakresy 15 min, 6 h, 24 h, 7 d); w teście na danych syntetycznych także 30 dni i drugi licznik |
| Wydajność na roku | zapytania paneli „Jakość”, „Energia i profil”, „Przegląd”, „Diagnostyka” na roku: **najwolniejsze 339 ms**; „Licznik na żywo” na dobie danych sekundowych: **najwolniejsze 202 ms** (tabela „Wartości w oknie”) |
| Kafelek K3-U3 | 12 przypadków (PLC offline, zatrzymany, zła mapa, stary `link_status`, brak `link_status`, stary `meter_status`, brak `meter_status` itd.) + zmiana progu zmienną |
| `$device` | lista zwraca dwa liczniki; moc licznika 2 (500 W) nie miesza się z licznikiem 1; zapytania wszystkich paneli przechodzą dla obu |
| Adnotacje | zapytanie zwraca 7 okien z k5 dla zakresu 22:30–23:10 (test); 10 okien w `data_windows` |
| Zasada 8 i język | test sprawdza brak fraz „przewidywanie/predykcja awarii”, każdy panel ma opis; polskie tytuły, jednostki SI |
| Izolacja | w `ss -ltn` nowy tylko port **3000** (`0.0.0.0` i `[::]`), `StartedAt` smartWARE bez zmian (06:52:39 UTC), pamięć kontenerów `aip-` w tabeli niżej |
| Testy | **407 z 407** (8 min 42 s), bez resztek `aip-test`; w tym 83 testy Grafany, 5 testów `data_windows`, 36 testów energii |

## Pomiar K6-U4 (rok danych syntetycznych)

Baza testowa poza tmpfs (`docker-compose.perf.yml`, wolumen znikał razem z projektem `aip-test`, limit 1 GiB): **365 dni, jeden wiersz na minutę na metrykę (9 metryk), ok. 2% losowych luk, jedna luka ok. 3 dni, jeden reset licznika.**
Zbiór: **4,22 mln wierszy surowych, 521 599 wiaderek `energy_1m`, 8 695 `energy_1h`, baza 961 MB**; ładowanie 146 s, **pierwsze odświeżenie agregatów na roku: 234 s**. Ponieważ jest jeden wiersz na minutę, `coverage` to ok. 1/60 (w teście okres próbkowania ustawiłem na 60 s); pomiar dotyczy **kosztu zapytań**, nie wartości energii.

| Zapytanie (rok danych) | Wiersze | Czas |
| --- | --- | --- |
| `energy_1m_calc`, ostatnie 24 h (widok) | 1 432 | **ok. 16,6–17,2 s** (bez progu: powyżej limitu 10 s `app_reader`) |
| `energy_1m_calc`, 7 dni (widok) | 10 071 | ok. 16,8–17,2 s |
| minuty 24 h, `LAG` w zapytaniu z zapasem 3 dni | 1 406 | **29 ms** |
| minuty 7 dni, `LAG` w zapytaniu z zapasem 3 dni | 9 891 | **84 ms** |
| `energy_1h_calc`, 30 dni | 720 | 53 ms |
| `energy_1h_calc`, cały rok | 8 695 | 99 ms |
| `energy_daily_check`, cały rok | 364 | 104 ms |
| `energy_daily_check`, 30 dni | 31 | 66 ms |

**Przyczyna:** `LAG` nad całym agregatem; filtr po `bucket` nie schodzi pod funkcję okna. Próba widoku z `LATERAL` nie pomogła (zapytanie nie skończyło się w ok. 10 minut, a połączenie zostało zerwane; podejrzewam, że podzapytanie po agregacie w czasie rzeczywistym przechodzi przez cały agregat dla każdego wiersza, ale planu nie obejrzałem). Pomogło dopiero **ograniczenie wyszukania poprzedniego wiaderka do 3 dni wstecz**
(bez ograniczenia ta sama konstrukcja trwała 658 ms, z ograniczeniem 12,6 ms). Skutek uboczny: gdy poprzednie wiaderko z odczytem licznika jest starsze niż 3 dni, pierwsze wiaderko zakresu liczy przyrost jako `last − first` (nie jako różnicę względem poprzedniego); wpływa to tylko na pierwszy punkt zakresu, nie na całkę.
Panele minutowe w ogóle nie potrzebują przyrostu (pokazują całkę i pokrycie), więc w dashboardach `LAG` w zapytaniu nie został użyty; jest w teście jako sprawdzona recepta dla etapu 4.

Zapytania paneli na roku (najwolniejsze, `best of 2`): „Moc: bieżący zakres a poprzednia doba” 339 ms, „…tydzień” 297 ms, „Napięcie” 215 ms, „cos φ i Q/P” 244 ms, „Zużycie na godzinę” 78 ms, „Moc bazowa” 123 ms; wszystkie pozostałe poniżej 220 ms.

## Wdrożenie i pomiary na prawdziwych danych

`docker compose up -d --build` o 17:20:30, koniec 17:20:35. Log `migrate`: `applied 004_data_windows.sql`, `done: 1 applied, 3 already applied`. Pierwszy start Grafany po wpisaniu klucza przez Grzegorza (32 znaki, `.env` 600).
W logu startowym były dwa błędy o braku opcjonalnych katalogów `provisioning/plugins` i `provisioning/alerting`; dodałem do repo puste katalogi (`fe979cd`), efekt zobaczę po następnym restarcie Grafany (nie restartowałem jej dodatkowo).

**Kontrola paneli na produkcji** (`python3 tests/grafana/prod_panels.py`, transport `docker exec`): 200 zapytań, 0 błędów. Przykłady (zakres 24 h): „Napięcie U” 651 punktów, „Wartości w oknie” 7 wierszy, „Zużycie na dobę” 2 wiersze, „Wiersze na minutę” 655, „Kod błędu komunikacji” 72 punkty.
Pełna tabela (dashboard, zakres, wiersze, czas) jest wynikiem polecenia; powtarzalna.

**Pamięć wszystkich kontenerów `aip-` (po ok. 40 min pracy Grafany):**

| Kontener | Użycie | Limit |
| --- | --- | --- |
| `aip-grafana` | 136,6 MiB (maks. 175 MiB przy otwartym „Na żywo”) | 384 MiB |
| `aip-timescaledb` | 182,7 MiB | 1,5 GiB |
| `aip-ingest` | 27,3 MiB | 128 MiB |
| `aip-collector` | 24,7 MiB | 128 MiB |
| `aip-mosquitto` | 7,5 MiB | 64 MiB |

**Potwierdzenie `meter_error_code` na żywo (zamyka punkt z k6):** od 16:23 UTC do 18:07 UTC wystąpiło 18 epizodów (`meter_status` 0 → 1), 72 wiersze `meter_error_code`: **18 × kod 161 (RESPONSE_TIMEOUT) i 54 × kod 162 (RESPONSE_CRC_FAIL)**, w każdym epizodzie 161 w pierwszej sekundzie, potem 162. W sekundach błędu baza ma **dokładnie 5 wierszy na sekundę**, w pozostałych 13 (model z `docs/status-codes.md`).
Log collectora: `OK -> COMM_ERROR (error_code=161, 0xA1, RESPONSE_TIMEOUT)`, następnie `-> COMM_ERROR (error_code=162, 0xA2, RESPONSE_CRC_FAIL)`, po 3 s `-> OK`. Epizody ustały w k6 na co najmniej 20 min, a teraz wróciły; przyczyny (E2-PLC1) nadal nie badam (decyzja Grzegorza).

## Odstępstwa od planu i dlaczego

1. **G7-c: mapa cieplna jako pivot w SQL, nie „Grouping to matrix”.** Review dopuszczał to jako zapas. Powód: nie mam jak sprawdzić renderowania transformacji bez zalogowania się w interfejsie; pivot (`FILTER` po dniu tygodnia, 24 wiersze × 7 kolumn) jest deterministyczny i sprawdzany przez harness (kolorowanie komórek to ustawienie panelu, wygląd oceni zrzut).
2. **Panele nie używają widoku `energy_1m_calc`** (wynik K6-U4); używają `energy_1m` z własną całką i pokryciem, a godzinowe i dobowe czytają `energy_1h_calc` i `energy_daily_check`. Widok minutowy zostaje w bazie, ale **na roku danych jest nieużywalny dla `app_reader`** (otwarta sprawa niżej).
3. **Zapas „3 dni” w przyroście `LAG`** (patrz wyżej) zamiast „jednego wiaderka zapasu”: jedno wiaderko poprzedzające zakres wyszukuję, ale tylko do 3 dni wstecz.
4. **Baza testowa większa:** `mem_limit` 896 MB (było 512) i `max_wal_size` 192 MB, bo WAL leży w tmpfs; bez tego dane panelowe (ok. 0,8 mln wierszy) wywracały bazę testową (Postgres zabity, `Consistent recovery state has not been yet reached`).
5. **Hasło `app_reader` w klastrze testowym jest wspólne** (`TEST_APP_READER_PASSWORD` z `run-tests.sh`), bo korzysta z niego też testowa Grafana; wcześniej było losowe w sesji pytest. `test_roles` nadal sprawdza zmianę hasła i działa.
6. **Wyścig w teście `test_compressed_raw_chunk_...` (k6):** pełny przebieg raz padł, bo zadanie polityki odświeżania w tle trzymało blokadę (`LockNotAvailable: concurrent refresh`). Pomocnik `refresh_all` ponawia teraz próbę (do 10 razy co 1 s). Wyścig dotyczył tylko testu, nie produkcji.
7. **Zapytanie „Wartości w oknie” zamieniłem na `last(value, time)`**, bo ordered `array_agg` na dobie danych sekundowych trwał 2,3 s (teraz 202 ms).
8. **Hasło admina Grafany z `.env` na laptopie:** z ustaleń review wynika, że Grzegorz loguje się własnym hasłem; ja nie logowałem się w przeglądarce (patrz niżej), a testy robię przez API w kontenerze.
9. **Dodałem do repo `tests/grafana/prod_panels.py` i `prod_live_load.py`** (sprawdzenie paneli na produkcji i symulacja otwartego dashboardu, oba przez `docker exec`), bo harness w `aip-test` nie dotyka produkcji.

## Czego nie sprawdziłem

- **Wyglądu dashboardów** (kolory stanów, mapa cieplna, rwanie linii na lukach, czytelność opisów po polsku, układ paneli): nie logowałem się w przeglądarce. Zalogowanie wymagałoby hasła admina (nie czytam `.env`) lub założenia konta w Grafanie, co wymaga Twojej zgody;
  bez tego mam pewność co do zapytań i danych, ale nie co do **renderowania**. Zrzuty Grzegorza są więc jedyną oceną wizualną.
- **Języka interfejsu `pl-PL`:** ustawiony zmienną, dostępność w obrazie sprawdziłem (katalog tłumaczeń), ale nie widziałem interfejsu.
- **Zachowania progu „Connect null values”** na prawdziwych lukach (próg w ms jest ustawiony w każdym panelu; test sprawdza dane, nie rysunek).
- **Restartu Grafany po zmianie** (puste katalogi provisioningu): nie restartowałem jej.
- **Zakresu 30 dni na prawdziwej bazie**: produkcja ma dopiero ok. 1 dobę danych (harness 30 dni działa na danych syntetycznych).
- **Kopii zapasowych woluminu `aip_grafana_data`:** etap 7.

## Dokumenty

`docs/grafana.md` (ściąga dla Grzegorza: logowanie, gdzie co jest, kolory stanów, pokrycie, zmiana progów, „zmiany w interfejsie nie są trwałe”, definicje wielkości), `docs/ops/jumo-ipc-setup.md` (sekcja Grafana: wersja i digest, klucz G7-g z poleceniem, hasło admina, kontrola, ryzyko HTTP, zasada „tylko `git pull`”, `core.fileMode false`),
`docs/data-model.md` (`data_windows`), `.env.example` (`GF_SECURITY_SECRET_KEY`).

## Checklista dla Grzegorza

1. Zalogować się z laptopa: `http://192.168.0.213:3000` (`GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` z `.env`; hasła w GUI nie zmieniamy). Jeśli strona się nie otwiera, daj znać: nie wiem, czy firewall komputera przepuszcza port 3000 z laptopa (z komputera port nasłuchuje na wszystkich interfejsach).
2. Zrobić **zrzuty ekranu pięciu dashboardów** (zakres ostatnie 24 h) do `docs/images/etap2/`.
3. Ocenić wizualnie w szczególności: mapę cieplną („Energia i profil”), osie stanów i kolory („Stan i diagnostyka”), luki na wykresach oraz czytelność kafelków w „Przeglądzie”.
4. Przenieść linię `GF_SECURITY_SECRET_KEY` do kopii `.env` na laptopie (jeśli jeszcze nie zrobione).

## Otwarte kwestie i propozycje

- **Widok `energy_1m_calc` jest bezużyteczny na roku danych (17 s > limit 10 s `app_reader`).** Dla analityki z etapu 4 proponuję funkcję SQL z zakresem czasu (`energy_1m_calc_range(device, od, do)`) liczącą `LAG` z zapasem, albo przepisanie widoku; do decyzji, bo to zmiana schematu (migracja 005). Do tego czasu analityka musi korzystać z zapytania z zapasem jak w teście.
- **Ryzyko jawnego HTTP w LAN** (G7-h): hasło admina i ruch przechodzą bez szyfrowania; do etapu 7 nie używać tego hasła nigdzie indziej.
- **Epizody błędu licznika wróciły** (18 w 3 h); k6 sądził, że ustały. `meter_error_code` i dashboardy je pokazują; diagnoza E2-PLC1 pozostaje odłożona zgodnie z decyzją Grzegorza.
- **E2-PLC2** (nowe kanały z licznika, mapa v2) to następny krok po k7; dashboardy nie mają „pustych paneli na zapas”: dojdą z nowymi danymi (THD w „Jakości energii”, temperatura i czas pracy w „Diagnostyce”).
- Czy zrobić jednorazowe konto Grafany do oceny wizualnej przez przeglądarkę w panelu Claude (wymaga Twojej zgody na utworzenie konta tylko do odczytu)?
- Następny krok: po przeglądzie architekta i „ok” Grzegorza: E2-PLC2 albo k8 (decyzja Grzegorza).
