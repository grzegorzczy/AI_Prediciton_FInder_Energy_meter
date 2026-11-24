# e2-k6 raport: poprawki collectora (krok 0) i agregaty energii
Status: DO PRZEGLĄDU

Wykonanie 24.11.2026 wg `e2-k6-plan.md` i uwag K6-U1…U5 z `e2-k6-review.md` (czasy w UTC; logi kontenerów są w czasie lokalnym UTC+1). Polecenia na `jumo-ipc` przez `ssh`, **bez `sudo`**,
bez ruszania smartWARE, demona Dockera i `docker system prune`. Żadnych testów fizycznych, żadnych zapisów do PLC (collector czyta wyłącznie FC04). `.env` nie był czytany ani wypisywany; raport bez sekretów.

## Podsumowanie

Wszystkie elementy planu są wykonane i działają na prawdziwych danych:
- **Krok 0 (collector):** odczyt PLC w tle, `link_status` bez luk także w „czarnej dziurze”, wyciszony pymodbus, `meter_error_code` (log + metryka). 20-minutowa obserwacja po wdrożeniu: **0 brakujących sekund `link_status`**, 13,00 wiersza/s, 0 linii z ramkami `>>>>>`, 0 restartów.
- **Agregaty:** `energy_1m` i `energy_1h` (agregat hierarchiczny z `energy_1m`), widoki `energy_1m_calc`, `energy_1h_calc`, `energy_daily_check`, polityki odświeżania, kompresji i retencji. **Spike: wszystkie cztery wymagane cechy działają razem w TimescaleDB 2.32.1** (`FILTER` z `first`/`last`, agregat z agregatu, kompresja agregatu ciągłego, tryb czasu rzeczywistego), więc **plan awaryjny K6-h nie był potrzebny**.
- **Testy: 319 z 319** na komputerze (350 s), bez resztek `aip-test`; wcześniej w tym kroku 257 testów, dodane: 36 testów energii (agregaty, widoki, polityki, przerwanie migracji) i testy collectora/ingestu/dokumentów.
- Kontrola na prawdziwych danych: okno referencyjne k5 (22:41–22:51) daje **dokładnie 28 s błędu licznika** i 572 próbki mocy, tyle samo co surowe dane; całka z widoku równa sumie z surowych danych (1,12614 Wh).

W trakcie pracy znalazłem i naprawiłem **błąd w widokach** (niżej, odstępstwo 2) oraz dwie wady planu K6-U1 + K6-U2 w połączeniu (odstępstwo 1).

## Co zrobiono

| Hash | Zawartość |
| --- | --- |
| `efaf9d7` | review k6 (wcześniej) |
| `976a773` | collector: zadanie odczytu w tle, wyciszony pymodbus, `meter_error_code` (krok 0) |
| `a44e7ab` | ingest: `poll_interval_s` i `energy_resolution_wh` w `devices.meta` (K6-d) |
| `764e11d` | migracje 002 i 003, testy bazy |
| `408222b` | poprawka `coverage` bez okresu próbkowania (NULL zamiast 1,0), poprawki testów |
| `e6aedeb` | dokumenty: `status-codes.md`, `data-model.md`, `docs/ops` |

Raport w osobnym commicie po tym raporcie. Hash wdrożony na komputerze: patrz „Wdrożenie”.

## Wyniki względem kryteriów zaliczenia

| Kryterium | Wynik |
| --- | --- |
| `link_status` bez luk w awarii (K6-a) | test „czarna dziura”: wykrycie po 0,50 s, 35 z 36 okresów z wierszem (próg 95%); porzucenie zawieszonego odczytu co 3 x `timeout_s`, powrót do OK bez restartu |
| Wolna odpowiedź < `timeout_s` nie daje offline ani rozgrzewki (K6-U1) | test `test_slow_read_below_timeout_...` |
| Porzucone zadanie nie publikuje wyniku (K6-U2) | test `test_abandoned_task_never_publishes_its_late_result` + test z prawdziwym sterownikiem i serwerem, który przyjmuje połączenie i milczy |
| Cisza pymodbus (K6-0.2) | `logging.getLogger("pymodbus")` na CRITICAL usuwa wpisy i ramki `>>>>>`; test sprawdza logger i `capfd`; w logu produkcyjnym 0 takich linii |
| `meter_error_code` (K6-b) | metryka i wpis w logu tylko przy `meter_status` ≠ 0, raz na zmianę kodu; nazwy 161/162/163 ze źródłem w `docs/status-codes.md` |
| Agregaty zgodne z surowymi danymi | testy na losowych danych z lukami i resetem licznika: `energy_1m` i `energy_1h` równe przeliczeniu z surowych danych; na prawdziwych danych: suma `active_power_n` 28 642 w minutowym, godzinowym i surowych, `meter_error_seconds` 188 w trzech |
| Całka i pokrycie (K6-c) | całka = `suma x poll_interval_s / 3600` dokładnie; `coverage` 1,0 / 0,9333 przy 4 s luki / 0; brak interpolacji; w oknie referencyjnym minuty z epizodem mają 56/60 = 0,9333 |
| Przyrost licznika (K6-e) | zwykły, reset, `gap_before`, pierwsze wiaderko, minuty bez odczytu energii nie zerują następnego przyrostu |
| Polityki (K6-f) | w katalogu: odświeżanie 7 dni / 1 min / 1 min i 30 dni / 1 h / 15 min, kompresja po 14 i 60 dniach, retencja 1 rok i brak dla godzinowego; test: okna krótsze niż 90 dni, kompresja po oknie |
| Czas rzeczywisty (K6-g) | test: najnowsze, niezmaterializowane wiaderko jest widoczne; w katalogu `materialized_only = f` dla obu |
| Przerwana migracja (K6-U3) | test dla 5 punktów przerwania po k-tej instrukcji (1, 2, 4, 7, 11): ponowny `migrate` kończy się sukcesem i daje ten sam katalog (agregaty, polityki) co czysta baza |
| `app_reader` czyta, `app_writer` nie zmienia | testy + na prawdziwej bazie (`SET ROLE app_reader`): 486 / 11 / 486 / 11 / 2 wiersze z pięciu obiektów; `app_writer` nie ma nawet `SELECT` na agregatach |

## Wdrożenie i pomiary na prawdziwych danych

Wdrożenie: `docker compose up -d --build` o 14:33:59, koniec 14:34:10. Log `migrate`: `applied 002_energy_aggregates.sql`, `applied 003_energy_views.sql`, `done: 2 applied, 1 already applied`.
`schema_migrations`: wersje 1, 2, 3. Collector i ingest `healthy`, 0 restartów.

**Czas pierwszego odświeżenia (K6-U5):** od synchronizacji ról (14:34:11,78) do końca migracji 002 (14:34:15,94) **ok. 4,2 s**, razem z utworzeniem obiektów i polityk, na **371 tys. wierszy** `measurements` (plan zakładał ok. 220 tys.; dane urosły).

**Rozmiary (K6-U5):**

| Obiekt | Rozmiar | Wiersze |
| --- | --- | --- |
| `measurements` | 70 MB | 371 653 |
| `energy_1m` (tabela materializacji) | 272 kB | 486 |
| `energy_1h` (tabela materializacji) | 72 kB | 11 |

**`EXPLAIN ANALYZE` (K6-U4)**, prawdziwe dane (1 doba, 486 minut), zapytania typu Grafany:

| Zapytanie | Planowanie | Wykonanie |
| --- | --- | --- |
| `energy_1m_calc`, ostatnie 24 h (483 wiersze) | 15,0 ms | **8,7 ms** |
| `energy_1h_calc`, ostatnie 30 dni (11 wierszy) | 12,2 ms | **4,1 ms** |
| `energy_daily_check` | 17,1 ms | **3,6 ms** |

Wszystko poniżej progu 1 s. **Zastrzeżenie:** plan skanuje agregat w całości (funkcja okna `LAG` nad całym agregatem), więc czas rośnie z liczbą wiaderek; mierzyłem na jednej dobie, nie na roku (ok. 525 tys. wierszy `energy_1m`). Nie mam pomiaru dla roku i nie wnioskuję z jednej doby;
sprawdzę to syntetycznie na początku k7 albo od razu zastosuję rozwiązanie z K6-U4 (zapytania Grafany z `LAG` w zapytaniu ograniczonym zakresem, widoki do analityki), zależnie od decyzji architekta.

**Obserwacja collectora 20 min (K6-j), 14:34:30–14:55:20:** 16 251 wierszy, **13,00 wiersza/s**, 1 251 wierszy `link_status` (wszystkie = 0), **0 brakujących sekund z 1 247**, 0 błędów licznika, 0 linii `>>>>>`/`pymodbus` w logu, collector `healthy`. **Uwaga:** w tym oknie nie wystąpił żaden epizod błędu licznika (wcześniejsze epizody co 64 s ustały), więc ścieżka `meter_error_code` i model 5 wierszy/s **nie były sprawdzone na prawdziwych danych**, tylko testami z atrapą PLC. Nie wywoływałem błędu fizycznie (decyzja Grzegorza).

**Pamięć (zmierzona po obserwacji):**

| Kontener | Użycie | Limit |
| --- | --- | --- |
| `aip-collector` | 23,7 MiB | 128 MiB |
| `aip-ingest` | 26,8 MiB | 128 MiB |
| `aip-timescaledb` | 148,8 MiB | 1,5 GiB |
| `aip-mosquitto` | 7,4 MiB | 64 MiB |

smartWARE: `StartedAt` kontenerów `datastore`, `dataview`, `postgres-server` bez zmian (06:52:39 UTC); `ss -ltn`: brak nowych portów (22, 80, 443, 127.0.0.1:1883, drukowanie lokalne).

**`energy_daily_check` na prawdziwych danych (informacyjnie, nie kryterium):**

| Doba | całka | pokrycie | przyrost licznika | wnioskowanie |
| --- | --- | --- | --- | --- |
| 2026-11-23 | 2,01 Wh | 0,012 | 0 Wh | doba zamknięta (`day_complete` = t), dane tylko z końcówki (start 22:38 UTC) |
| 2026-11-24 | 53,9 Wh | 0,318 | 100 Wh | doba w toku; pokrycie < 0,5, więc brak ekstrapolacji i `within_resolution` = NULL |

Zgodność całki z licznikiem na prawdziwych danych będzie oceniana dopiero po kilku pełnych dobach (kwantyzacja 100 Wh i luki po zaniku zasilania).

## Odstępstwa od planu i dlaczego

1. **K6-U1 + K6-U2 w połączeniu dawały ok. 17% sekund bez `link_status` w „czarnej dziurze”.** Po porzuceniu zawieszonego odczytu nowy odczyt ma wiek 0, więc przez kolejne `timeout_s` byłby „wolną odpowiedzią” i nie publikowałby nic. Zmiana: gdy PLC jest już uznany za niedostępny (`failing`), **każdy cykl publikuje `link_status` = 1 niezależnie od wieku nowego odczytu**; wstrzymanie publikacji do `timeout_s` zostaje tylko dla sprawnego PLC (ochrona przed fałszywym offline). Test mierzy okres w samej awarii (ziarnistość timerów Windows ok. 15,6 ms zaniżała wynik); na Linuksie 35 z 36 okresów.
2. **Błąd znaleziony przez testy na komputerze: `LEAST(1, NULL)` zwraca 1,** więc brak `poll_interval_s` w `meta` dawał `coverage` = 1,0 zamiast NULL (a widok dobowy tak samo). Naprawione w migracji 003 **przed** zastosowaniem na produkcji (`CASE WHEN ... IS NOT NULL`), dodane testy (`test_missing_meta_gives_null_not_a_default`, `test_daily_check_without_sampling_interval_has_null_coverage`). Obowiązuje zasada K6-d „NULL, nie domysł”.
3. **Przyrost licznika względem poprzedniego wiaderka z odczytem licznika**, a nie po prostu poprzedniego wiaderka (doprecyzowanie planu): minuty, w których licznik jest w błędzie i nie publikuje energii, nie mogą zerować przyrostu następnego wiaderka. Stąd `gap_before` mierzy odstęp od poprzedniego wiaderka z energią.
4. **Test dnia ze zmianą czasu 29.03.2026** wymaga wyłączenia retencji surowych danych w bazie testowej (to dane sprzed ponad 90 dni, zadanie retencji je kasowało); w teście wywołuję `remove_retention_policy` na `measurements` (tylko w bazie testowej).
5. **Pliki na komputerze:** poprawioną migrację 003 i testy skopiowałem na komputer przez `ssh` (przed wdrożeniem), a nie przez `git pull`, żeby nie wypychać każdej poprawki osobno. Zawartość odpowiada commitom wyżej; po wypchnięciu przywracam czyste drzewo (`git checkout -- .` i `git pull --ff-only`) i sprawdzam, że `git status` jest czysty. Do tego czasu `git status` na komputerze pokazuje zmodyfikowane pliki.
6. **Obserwacja bez epizodów licznika** (patrz wyżej): ścieżka `meter_error_code` nie jest sprawdzona na prawdziwych danych.

## Uwagi K6-U1…U5

| Uwaga | Wynik |
| --- | --- |
| U1 | próg „offline” = `timeout_s`; wolna odpowiedź < `timeout_s` bez offline i rozgrzewki (test); test „czarna dziura” liczony od chwili wykrycia; patrz odstępstwo 1 |
| U2 | porzucenie po 3 x `timeout_s` (WARNING raz na epizod), nowy klient (`reset()` sterownika), nowy odczyt; porzucone zadanie nie publikuje (test z „upartym” sterownikiem); powrót do OK bez restartu (test) |
| U3 | wszystkie instrukcje 002 idempotentne; runner zapisuje sumę kontrolną po całości; test przerwania w 5 punktach |
| U4 | `EXPLAIN ANALYZE` wyżej; zastrzeżenie o skalowaniu; zadanie dla k7 do decyzji |
| U5 | `bucket_complete` w obu widokach `*_calc`; opis „brak pokrycia ≠ błąd licznika” w `docs/data-model.md`; czas pierwszego odświeżenia i rozmiary wyżej |

## Dokumenty

`docs/status-codes.md` (sekcja `meter_error_code` ze źródłem `MB_ErrorCodes`, model wierszy 13 / 5 / 1, zachowanie w czarnej dziurze; testy zgodności tabeli z kodem), `docs/data-model.md` (agregaty, widoki, polityki, kwantyzacja licznika, „brak pokrycia ≠ błąd licznika”), `docs/ops/jumo-ipc-setup.md` (ręczne odświeżanie po wypełnianiu historii, kontrola, przerwana migracja).

## Checklista dla Grzegorza

Brak czynności.

## Otwarte kwestie i propozycje

- **Decyzja:** czy w k7 od razu przejść na zapytania Grafany z `LAG` w zapytaniu (K6-U4), czy najpierw zmierzyć widoki na syntetycznym roku danych? Moja propozycja: najpierw krótki pomiar na syntetycznym roku (ok. 525 tys. wierszy), bo koszt jest mały, a wynik rozstrzyga.
- Ścieżka `meter_error_code` na prawdziwych danych: do sprawdzenia przy najbliższym naturalnym epizodzie błędu licznika (bez wywoływania go), albo w teście fizycznym, jeśli Grzegorz kiedyś na to pozwoli.
- Następny krok: k7 (Grafana) po przeglądzie architekta i „ok” Grzegorza.
