# E3-k4 – plan kroku: agregat `pump_1m` (migracja 012), znacznik pracy pompy, okno `sim_reset`, limit danych sim w ingeście

Data: 2026-11-27. Podstawa: `e3-k0-plan.md` (k4, K0-D4), `e3-k2-review.md` (K2-U4: znacznik pracy w `pump_1m`), `e3-k2-report-review.md` (K2R-D2: okno `sim_reset`), `e3-k3-report.md` i review k3 (OK Z UWAGAMI: pełne testy na start, limit danych sim w ingeście, test brokera bez konta sim w checkliście k7).
**Sam plan, do review.** Produkcja się nie zmienia (`~/ai-predykcja` na `c299eaa`; migracja 012 i zmiana ingestu trafią na produkcję dopiero w k7). Testy z worktree `~/ai-predykcja-dev` w `aip-test`.

## 0. Pełne testy na start (uwaga 1 z review k3)

`tests/run-tests.sh` w worktree na obecnym `main` (`62cf284`, raport k3), 27.11.2026 10:14:45–10:39:52 UTC: **700 passed, 5 skipped, 0 failed** (1 492 s); pominięte: 3 testy wydajności etapu 2 i 2 testy pamięci sum (tylko `run-perf.sh`). Produkcja po przebiegu: `c299eaa`, katalog czysty.

## 1. Agregat `pump_1m` (migracja `012_pump_aggregates.sql`)

Agregat ciągły jak `energy_1m` (migracja 002/007): wiaderko 1 min, `device_id`, wyłącznie wartości addytywne lub odtwarzalne. Źródło: `measurements`, metryki pompy (`vibration_rms`, `bearing_temperature`, `motor_current`, `flow`, `speed`).

| Kolumny | Znaczenie |
| --- | --- |
| `<metryka>_n`, `_sum`, `_min`, `_max` dla 5 metryk | liczność, suma, min, max w minucie (średnia = sum / n w widoku) |
| **`run_n`** = `count(value) FILTER (WHERE metric = 'speed' AND value > 0)` | **znacznik pracy (K2-U4):** liczba sekund (próbek) z obrotami > 0 w minucie |

- **Minuta pracy** = `speed_n > 0 AND run_n = speed_n` (wszystkie próbki obrotów w minucie > 0). Minuty z postojem lub częściowe (start i koniec zmiany) nie są minutami pracy. Analityka trendu drgań w etapie 5 bierze tylko minuty pracy, nie tło 0,1 mm/s z postoju. Wiersz drgań nie zna obrotów z tej samej sekundy (osobne wiersze tabeli wąskiej), więc znacznik jest na poziomie minuty – przy próbkach co 1 s (na żywo) i co 1 min (historia k5) działa tak samo.
- Widok **`pump_1m_calc`**: średnie (`sum / nullif(n, 0)`), `run_share = run_n / speed_n`, `running = (speed_n > 0 AND run_n = speed_n)`; uprawnienia `SELECT` dla `app_reader` (agregat i widok).
- Polityki (jak `energy_1m`): odświeżanie okno 7 dni / koniec 1 min / co 1 min; `materialized_only = false`; kompresja po 14 dniach (`segmentby = device_id`); **retencja 1 rok** (dłużej niż 90 dni surowych: krzywa 84 dni historii zostaje po skasowaniu surowych danych).
- **Bez `pump_1h` w k4** (etap 5 zdecyduje, czy trend liczy z minut, czy potrzebny agregat godzinny); minutowy rok to ok. 525 600 wierszy na pompę.
- Odporność na przerwanie w połowie (jak K6-U3): każda instrukcja idempotentna (`IF NOT EXISTS`, `if_not_exists => true`), test przerwania po k-tej instrukcji.
- Historia pompy (k5) jest starsza niż okno odświeżania (7 dni): po jej wgraniu ręczne `CALL refresh_continuous_aggregate('pump_1m', …)` – procedura w k5, test odświeżenia starego zakresu już w k4.
- `docs/data-model.md`: tabela `pump_1m` zamiast „planowany w etapie 4”, opis minuty pracy.

## 2. Okno `sim_reset` (K2R-D2) i `sim_backfill` (U-4 z K0)

Wpisy w `data_windows` dodaje wyłącznie `migrate` (każde okno to nowa migracja z `INSERT`, jak 005/006/010/011). Wymiana łożyska i wgranie historii zdarzą się w nieznanej dziś chwili, więc w k4:
- `kind` `sim_reset` (wymiana łożyska: start = chwila, od której obowiązuje nowa `bearing_installed_at` we wdrożonym configu, koniec = start + 1 min; `exclude_from_analytics = TRUE`; etap 5 dzieli trend drgań na tej granicy) i `sim_backfill` (k5: od początku do końca wgrywania historii; nietypowe obciążenie);
- **szablon migracji** w `docs/ops/jumo-ipc-setup.md` (sekcja „Symulator”) dla obu rodzajów, z zapytaniem, które daje granice z bazy (jak przy `ipc_reboot`);
- **test** w `tests/db/test_data_windows.py`: oba rodzaje przechodzą ograniczenie `kind` i są widoczne dla `app_reader`; zapytanie adnotacji Grafany zwraca je w zakresie (wstawienie w bazie testowej, nie migracją – lista okien produkcyjnych bez zmian, 14).
- Ograniczenie `kind` (`^[a-z0-9_]+$`) nie wymaga zmiany.

## 3. Limit danych sim w pamięci ingestu (uwaga 2 z review k3)

Dziś (k3) ingest odrzuca wiadomości QoS 0, gdy baza jest niedostępna. W k4 reguła staje się jawna i ograniczona niezależnie od stanu bazy:

- **Co jest odrzucane:** wyłącznie wiersze urządzeń o `source = 'sim'` (z configu, po walidacji), dostarczone z QoS 0. **Dane real nigdy nie są odrzucane** – także gdyby przyszły z QoS 0 (np. błędna konfiguracja nadawcy): wtedy zostają w paczce jak dotąd.
- **Co włącza odrzucanie** (dowolny z warunków):
  1. baza niedostępna (`db_down`, po pierwszym nieudanym zapisie paczki);
  2. w pamięci (paczka oczekująca na zapis) jest już `INGEST_SIM_PENDING_MAX` wierszy sim – **domyślnie 3 000** (ok. 100 s danych symulatora przy 29/s, ok. 1,3 MiB wg pomiaru 436 B na wiadomość z przeglądu k3). Limit działa także przy powolnej, ale dostępnej bazie.
- **Epizod i log:** pierwsze odrzucenie = WARNING z przyczyną (baza niedostępna / limit `INGEST_SIM_PENDING_MAX`); kolejne odrzucenia liczone bez logowania; **koniec epizodu** = pierwszy udany zapis paczki, po którym liczba wierszy sim w pamięci jest poniżej limitu → jeden WARNING z liczbą odrzuconych w epizodzie i czasem trwania. Licznik od startu w podsumowaniu (`odrzucone_sim=…`), jak dziś.
- Odrzucona wiadomość QoS 0 jest „potwierdzana” (dla QoS 0 to nic nie robiący `ack`), więc nie wraca z brokera; lukę uzupełnia historia symulatora (k5, idempotentnie).
- Zmienna `INGEST_SIM_PENDING_MAX` w `docker-compose.yml` (usługa `ingest`); zmiana `docs/ops` (tabela przerw i opis zachowania ingestu).
- **Testy:** (a) baza niedostępna: 20 000 wiadomości sim → w pamięci 0 sim, wiadomości real czekają; (b) baza dostępna, ale paczki nie schodzą (atrapa wolnego zapisu): w pamięci najwyżej `INGEST_SIM_PENDING_MAX` sim, real bez limitu (do `max_inflight` brokera); (c) wiadomość urządzenia real z QoS 0 nigdy nie jest odrzucana; (d) jeden WARNING na początku i jeden na końcu epizodu z poprawną liczbą; (e) e2e: po epizodzie dane sim znowu się zapisują; (f) regresja: dotychczasowe testy odporności ingestu (QoS 1) bez zmian.

## 4. Do checklisty k7 (uwaga 3 z review k3)

Test brokera **bez konta symulatora** na produkcji przy wdrożeniu (przed dopisaniem konta albo z chwilowo usuniętymi zmiennymi – decyzja w planie k7): w logu `aip-mosquitto` WARNING „brak konta symulatora”, collector i ingest połączone, 20 wierszy/s danych prawdziwych, symulator odrzucany przy połączeniu (jeden ERROR w jego logu, bez pętli restartów). Zapisuję w `docs/stages/etap-3.md` (szkic checklisty, k8) i w planie k7.

## 5. Testy (razem)

| Obszar | Testy |
| --- | --- |
| `pump_1m` (baza testowa) | migracja na pustej bazie i po 001–011; kolumny i wartości z danych syntetycznych (sumy, liczności, min/max, `run_n`); minuta pracy / postoju / częściowa (start zmiany); dane co 1 min (jak historia k5) dają te same wnioski; tryb czasu rzeczywistego (bieżąca minuta widoczna); polityki (odświeżanie, kompresja 14 dni, retencja 1 rok) jak w testach `energy_1m`; ręczne odświeżenie zakresu starszego niż 7 dni; uprawnienia (`app_reader` czyta, `app_writer` nie może pisać); przerwanie migracji po k-tej instrukcji; idempotencja (`0 applied`) |
| Dane symulatora → `pump_1m` | e2e: próbki `samples_at` pompy przez MQTT i ingest → po odświeżeniu średnie w `pump_1m_calc` równe średnim z modelu; minuty postoju poza zmianą mają `running = false` |
| Okna | pkt 2 |
| Ingest | pkt 3 |
| Regresja | pełny zestaw (`run-tests.sh`), w tym widoki energii i harness Grafany (nowy agregat nie zmienia istniejących) |

Po k4: pełny zestaw w worktree, agent `reviewer`, raport `e3-k4-report.md`.

## 6. Lista plików

Nowe: `db/migrations/012_pump_aggregates.sql`, `tests/db/test_pump_aggregates.py`, `tests/ingest/test_sim_limit.py`, `docs/handoff/e3-k4-report.md`.
Zmieniane: `services/ingest/src/ingest/{pipeline,main}.py`, `docker-compose.yml` (`INGEST_SIM_PENDING_MAX`), `tests/ingest/test_pipeline_qos0.py` (na nową regułę), `tests/db/test_data_windows.py`, `tests/db/test_migrations.py` (lista migracji), `tests/simulator/test_sim_e2e.py` (lub nowy plik e2e pompy), `docs/data-model.md`, `docs/ops/jumo-ipc-setup.md`.
Bez zmian: collector, symulator (kod), Mosquitto, Grafana (dashboard pompy w k6), produkcja.

## 7. Ryzyka

| Ryzyko | Postępowanie |
| --- | --- |
| Zmiana ingestu (ścieżka produkcyjna) | dane real nigdy odrzucane (test), regresja wszystkich testów odporności, wdrożenie w k7 z kontrolą 20 wierszy/s |
| Agregat ciągły nie da się później rozszerzyć bez odtworzenia | zestaw kolumn uzgodniony teraz (5 metryk × n/sum/min/max + `run_n`); ewentualne dodatki – osobny agregat jak w 007 |
| Wiaderka bez danych pompy dla innych urządzeń | filtr po metrykach pompy; urządzenia bez tych metryk nie tworzą wierszy (test) |
| Historia 84 dni starsza niż okno odświeżania | ręczne odświeżenie w k5 (test w k4) |

## 8. Do decyzji

1. Limit `INGEST_SIM_PENDING_MAX` = 3 000 wierszy (ok. 100 s danych sim).
2. Minuta pracy = wszystkie próbki obrotów w minucie > 0 (częściowe minuty wyłączone z trendu).
3. Bez `pump_1h` w k4.

Plan e3-k4 gotowy do przeglądu.
