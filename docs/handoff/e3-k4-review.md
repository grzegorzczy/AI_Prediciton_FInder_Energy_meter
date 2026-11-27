# E3-k4 – review planu (architekt)

Data: 2026-11-27. Plan: `e3-k4-plan.md` (`64d04cd`). Review raportu k3: `e3-k3-report-review.md` (zapisany razem z tym plikiem).

**Werdykt: OK Z UWAGAMI – wykonuj po „ok” Grzegorza.** Agregat, znacznik pracy i limit danych sim zgodne z K0-D4, K2-U4, K2R-D2 i uwagami k3. Dwie uwagi dotyczą k5 (wgranie historii) i trzeba je zamknąć już teraz, bo k4 ustala zachowanie, na którym k5 się oprze.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K4-D1 | `INGEST_SIM_PENDING_MAX` = 3 000 | **Tak.** Ok. 100 s danych sim, ok. 1,3 MiB. Dane real nigdy nie są odrzucane – zgodnie z planem, z testem (c). |
| K4-D2 | Minuta pracy = wszystkie próbki obrotów w minucie > 0 | **Tak.** Częściowe minuty (start i koniec zmiany) wyłączone z trendu drgań – przy nagrzewaniu po starcie i tak nie są reprezentatywne. `run_share` w widoku zostaje (etap 5 może zdecydować inaczej bez zmiany agregatu). |
| K4-D3 | Bez `pump_1h` w k4 | **Tak.** Trend z 84 dni minut to ok. 120 tys. wierszy na pompę – mało dla bazy. Agregat godzinny tylko, jeśli etap 5 zmierzy, że jest potrzebny. |

## Uwagi

- **K4-U1 – historia (k5) nie może podlegać odrzucaniu danych sim.** Reguła z sekcji 3 odrzuca wiersze sim **dostarczone z QoS 0**. Przy wgrywaniu historii baza będzie wolniejsza, więc limit 3 000 zadziała – gdyby historia szła QoS 0, luki powstawałyby po cichu. Ustalenie na k5: **wgrywanie historii publikuje QoS 1 z ograniczoną liczbą wiadomości w locie** (naturalne dławienie, kolejka brokera nie rośnie przy działającym ingeście) albo QoS 0 z kontrolą kompletności w bazie i ponownym wysłaniem brakujących minut. Wybór i pomiar w planie k5; w k4 wystarczy test, że wiersz sim z QoS 1 nie jest odrzucany przy przekroczonym limicie.
- **K4-U2 – ręczne odświeżenie zakresu, w którym `pump_1m` jest już skompresowany.** Historia 84 dni sięga przed 14-dniową granicę kompresji agregatu, a surowe chunki z danymi prawdziwymi od 23.11 są skompresowane (U-3 z K0). Test z sekcji 1 („odświeżenie zakresu starszego niż 7 dni”) rozszerzyć o: (a) odświeżenie zakresu, w którym chunk `pump_1m` jest już skompresowany (dane testowe, `compress_chunk`), (b) wstawienie surowych wierszy pompy do skompresowanego chunku `measurements`. Wynik (działa / błąd i jaki) w raporcie – od tego zależy kolejność kroków w k5.
- **K4-U3 – `sim_backfill` a analityka.** Okno oznacza czas obciążenia komputera, nie czas danych historycznych. Ustawić `exclude_from_analytics = FALSE` (adnotacja w Grafanie), chyba że w tym oknie zginą dane prawdziwe – wtedy osobne okno jak przy przerwach. `sim_reset` – `TRUE`, zgodnie z planem.
- **K4-U4 – liczność próbek na żywo.** Minuta pracy z jedną próbką obrotów (np. pierwsza minuta po restarcie symulatora) liczy się jako „pracy”. Akceptuję; w widoku zostaje `speed_n`, żeby etap 5 mógł ustawić minimum (np. ≥ 30 próbek na żywo). Opisać w `docs/data-model.md`.
- **K4-U5 – kolumny agregatu ustalone na stałe.** Zestaw 5 metryk × n/sum/min/max + `run_n` – zgoda (ryzyko z sekcji 7). Nazwy kolumn w `docs/data-model.md` z jednostkami.

## Zrzuty

k4 bez GUI – zrzutów nie potrzeba. Dashboard pompy na `pump_1m_calc` w k6.

## Dalej

„Ok” Grzegorza → wykonanie k4 w worktree → pełne testy → `reviewer` → `e3-k4-report.md` → review.
