# e2-k6 review: poprawki collectora (krok 0) i agregaty energii

Recenzent: architekt (czat projektu), 24.11.2026. Podstawa: `docs/handoff/e2-k6-plan.md` (commit `be4ae2e`), `e2-k5-report-review.md`, `e2-plc1-diag-review.md`, `e2-k0-review.md` (D6, D7, U7), dokumenty projektu 00, 12 (decyzja Grzegorza 24.11: bez testów fizycznych, k5b w k6).

## Werdykt: OK Z UWAGAMI

Plan obejmuje cały zakres dawnego k5b i zadania przeniesione do k6. Mocne strony:
- **wartości addytywne w agregatach i pochodne w widokach** – dzięki temu `energy_1h` da się poprawnie złożyć z `energy_1m`;
- `poll_interval_s` i rozdzielczość licznika w `devices.meta` zamiast stałych w SQL;
- NULL zamiast domysłu;
- `within_resolution` jako uczciwa miara przy kwantyzacji 100 Wh;
- okna odświeżania krótsze niż retencja surowych danych i kompresja po oknie odświeżania;
- spike z planem awaryjnym K6-h;
- kontrola na prawdziwych danych przez 28 s błędu w oknie referencyjnym k5.

Uwagi K6-U1…U5 do uwzględnienia w wykonaniu, bez nowego planu.

## Decyzje K6-a…K6-j

| Id | Rozstrzygnięcie |
| --- | --- |
| K6-a | Odczyt jako zadanie w tle – **zatwierdzone z modyfikacją K6-U1** (próg „offline” = `timeout_s`, nie jeden okres) |
| K6-b | Tablica nazw 161/162/163 – zatwierdzone. Źródło zweryfikowane przez architekta 24.11.2026: dokumentacja CODESYS `MB_ErrorCodes` (helpme-codesys.com, IoDrvModbus) – A1 RESPONSE_TIMEOUT, A2 RESPONSE_CRC_FAIL, A3 RESPONSE_WRONG_SLAVE. W `docs/status-codes.md` podać to źródło |
| K6-c | `energy_1m`, `energy_1h` addytywne + widoki `*_calc` – zatwierdzone |
| K6-d | `poll_interval_s`, `energy_resolution_wh` w `devices.meta` przez ingest – zatwierdzone |
| K6-e | `within_resolution` główną miarą, `deviation_pct` od 5 kroków; doba `Europe/Warsaw` jako stała widoku do etapu 4 – zatwierdzone |
| K6-f | Polityki z tabeli – zatwierdzone |
| K6-g | Czas rzeczywisty – zatwierdzone |
| K6-h | Plan awaryjny `energy_1h` z surowych danych – zatwierdzone (w raporcie wynik spike'u) |
| K6-i | Model wierszy 13 / 5 / 1 – zatwierdzone; przenoszę do dokumentu projektu 12 |
| K6-j | Obserwacja 20 min bez testów fizycznych – zatwierdzone |

## Uwagi

### K6-U1 – kiedy zgłosić „offline”, gdy odczyt w tle jeszcze trwa

Plan zgłasza `link_status = 1`, gdy odczyt trwa dłużej niż **jeden okres** (1 s). Przy `timeout_s` = 2 s pojedynczy wolniejszy odczyt (np. 1,1 s – chwilowe obciążenie PLC lub sieci) dałby fałszywe „PLC offline”, zerowanie heartbeatu i rozgrzewkę, czyli lukę w pomiarach przy sprawnym PLC. Zmiana:
- odczyt zakończony błędem → `link_status = 1` od razu (jak dziś);
- odczyt wciąż trwa:
  - do upływu `timeout_s` od jego startu – cykl bez publikacji, tak jak dziś przy wolnej odpowiedzi;
  - po przekroczeniu `timeout_s` – `link_status = 1` w każdym kolejnym cyklu, aż odczyt się zakończy;
- wykrycie offline nadal ≤ `timeout_s` + 1 s; test „czarna dziura”: ≥ 95% okresów z wierszem **liczone od chwili wykrycia**;
- dodatkowy test: odczyt trwający 1,5 × okres, ale < `timeout_s`, **nie** daje `link_status = 1` ani rozgrzewki.

### K6-U2 – zadanie w tle musi mieć ograniczony czas

Atrapa „`connect()` nigdy się nie kończy” pokazuje ryzyko: jeśli zadanie w tle naprawdę zawiśnie, kolejny odczyt nigdy nie wystartuje (zasada „nie startuj drugiego”), a collector zostanie w „offline” na zawsze, nawet po powrocie PLC. Wymagania:
- łączenie i odczyt mają twardy limit (`timeout_s` w gnieździe i w kliencie);
- jeśli mimo to zadanie trwa dłużej niż np. 3 × `timeout_s`, collector porzuca je (log WARNING raz na epizod), tworzy nowego klienta i startuje nowy odczyt. Porzucone zadanie nie może później opublikować wyniku;
- test: atrapa wiszącego `connect()` → po zniknięciu awarii collector wraca do OK bez restartu kontenera.

### K6-U3 – migracja bez transakcji: odporność na przerwanie w połowie

Migracja `002` działa bez transakcji. Jeśli przerwie się po utworzeniu agregatu, a przed politykami, ponowny `migrate` musi przejść:
- `CREATE MATERIALIZED VIEW IF NOT EXISTS`;
- polityki z `if_not_exists => true`;
- `ALTER … SET (timescaledb.materialized_only = false)` idempotentnie.

Jak runner zapisuje sumę kontrolną migracji częściowo wykonanej? Zapis dopiero po całości, a ponowne wykonanie od początku. Test: symulacja przerwania po pierwszej instrukcji → ponowny `migrate` kończy się sukcesem i daje ten sam stan katalogu.

### K6-U4 – wydajność widoków z `LAG`

Widoki `*_calc` z funkcją okna nad całym agregatem: filtr po `bucket` z Grafany może nie zejść poniżej funkcji okna i Postgres policzy całość. Przy roku minut na urządzenie (ok. 525 tys. wierszy) to jeszcze akceptowalne, ale:
- w raporcie `EXPLAIN ANALYZE` dla typowego zapytania Grafany (ostatnie 24 h z `energy_1m_calc` i 30 dni z `energy_1h_calc`) na prawdziwych danych;
- jeśli czas > 1 s – zadanie dla k7: zapytania Grafany liczą przyrost bezpośrednio z agregatu z `LAG` w zapytaniu ograniczonym zakresem (z jednym wiaderkiem zapasu), a widoki zostają do analityki.

Pierwsze wiaderko w zakresie zapytania z takim zapasem nie dostaje sztucznego „pierwszego wiaderka urządzenia”.

### K6-U5 – drobne

- `coverage` bieżącego wiaderka < 1 z natury: w widokach dodać kolumnę `bucket_complete` (koniec wiaderka ≤ `now()`), żeby Grafana i analityka mogły odróżnić „trwa” od „brak danych”.
- `meter_error_seconds` liczy sekundy ze `meter_status ≠ 0`. Przy awarii PLC (`link_status = 1`) licznik nie publikuje statusu, więc te sekundy nie są błędem licznika. Opisać w `docs/data-model.md`: brak pokrycia ≠ błąd licznika.
- Raport: czas pierwszego odświeżenia na ok. 220 tys. wierszy i rozmiary obiektów.

## Kontrola reszty planu

- Zasady twarde:
  - tylko FC04, testy k3 bez zmiany oczekiwań;
  - brak testów fizycznych (decyzja Grzegorza);
  - reguła 3 (bez stałych urządzeń w SQL i kodzie);
  - `app_reader` tylko odczyt, `app_writer` bez zmian agregatów – ✔.
- Retencje z k0 (`energy_1m` 1 rok, `energy_1h` bez limitu) i D6/D7/U7 – ✔.
- Etap 3: ręczne odświeżanie agregatów po wypełnianiu historii opisane w `docs/ops` – ✔.
- „Gotowe, gdy” k6 sprawdzalne testami i zapytaniami na prawdziwych danych – ✔.

## Checklista Grzegorza po k6

Brak czynności.

## Następny krok

Po „ok” Grzegorza: Claude Code wykonuje k6 z uwagami K6-U1…U5 → `e2-k6-report.md` → stop. Potem k7 (Grafana).
