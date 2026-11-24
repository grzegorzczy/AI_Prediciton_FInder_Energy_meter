# e2-k6 report review: poprawki collectora i agregaty energii

Recenzent: architekt (czat projektu), 24.11.2026. Podstawa: `docs/handoff/e2-k6-report.md` (commit `5dffc89`), `e2-k6-review.md`.

## Werdykt: OK – krok k6 zaliczony

| Kryterium | Dowód | Ocena |
| --- | --- | --- |
| `link_status` bez luk w awarii | „czarna dziura”: wykrycie 0,50 s, 35/36 okresów; na żywo 0 brakujących sekund z 1247 | ✔ |
| Brak fałszywego offline (K6-U1) | test wolnej odpowiedzi < `timeout_s` | ✔ |
| Brak zawieszenia (K6-U2) | porzucenie po 3 × `timeout_s`, nowy klient, porzucone zadanie nie publikuje, powrót bez restartu | ✔ |
| Cisza pymodbus | 0 linii `>>>>>`/`pymodbus` w logu produkcyjnym | ✔ |
| `meter_error_code` | testy (atrapa); na żywo nieobserwowane – brak epizodów w oknie obserwacji | ✔ (testy) |
| Agregaty = surowe dane | testy z lukami i resetem; prawdziwe dane: `active_power_n` 28 642 i `meter_error_seconds` 188 zgodne w trzech źródłach; okno referencyjne k5: 28 s błędu, 572 próbki, całka 1,12614 Wh | ✔ |
| Całka, pokrycie, przyrost licznika | dokładne wzory, NULL zamiast domysłu, reset, `gap_before` | ✔ |
| Polityki, czas rzeczywisty | w katalogu zgodnie z tabelą; `materialized_only = f` | ✔ |
| Przerwana migracja (K6-U3) | 5 punktów przerwania, ten sam katalog | ✔ |
| Uprawnienia | `app_reader` czyta 5 obiektów, `app_writer` bez dostępu do agregatów | ✔ |
| Testy, izolacja | 319/319; smartWARE bez zmian; brak nowych portów; pamięć bazy 149 MiB / 1,5 GiB | ✔ |

Spike: wszystkie cztery cechy TimescaleDB 2.32.1 działają razem, więc plan awaryjny K6-h nie był potrzebny.

## Odstępstwa – ocena

1. **Publikacja `link_status = 1` w każdym cyklu, gdy PLC jest już „failing”** – akceptowane. To poprawne domknięcie K6-U1 + K6-U2. Ochrona przed fałszywym offline zostaje dla sprawnego PLC.
2. **`LEAST(1, NULL)` = 1** – dobrze, że testy to złapały przed produkcją; poprawka i testy akceptowane.
3. **Przyrost względem poprzedniego wiaderka z odczytem licznika** – akceptowane (poprawne doprecyzowanie).
4. **Wyłączenie retencji w teście ze zmianą czasu** – akceptowane (tylko baza testowa).
5. **Pliki skopiowane na komputer przez `ssh` zamiast `git pull`** – akceptowane jednorazowo, bo stan końcowy jest czysty, a suma kontrolna migracji 003 w bazie zgadza się z repo. **Na przyszłość:** na komputer trafia wyłącznie to, co jest w `origin/main` (`git pull --ff-only`). Kilka małych commitów jest lepsze niż kopiowanie poza gitem. `core.fileMode false` w klonie komputera – akceptowane; dopisać do `docs/ops`.
6. **Brak epizodów w obserwacji** – odnotowane. Epizody CRC (E2-PLC1) ustały na co najmniej 20 min; sprawa zostaje odłożona zgodnie z decyzją Grzegorza. `meter_error_code` potwierdzimy na żywo przy najbliższym naturalnym epizodzie.

## Decyzja K6-U4 (pytanie z raportu)

Zgadzam się z propozycją Claude Code: **k7 zaczyna się od pomiaru widoków `*_calc` na syntetycznym roku danych** (ok. 525 tys. wiaderek `energy_1m`), wyłącznie w bazie testowej `aip-test`. Próg: zapytania Grafany (24 h z `energy_1m_calc`, 30 dni z `energy_1h_calc`, `energy_daily_check`) < 1 s. Jeśli próg nie zostanie spełniony, panele Grafany liczą przyrost `LAG` w zapytaniu ograniczonym zakresem (z jednym wiaderkiem zapasu), a widoki zostają do analityki.

## Zakres k7 (dla `e2-k7-plan.md`)

1. Pomiar K6-U4 (wyżej).
2. **Grafana** w Compose:
   - przypięta wersja (digest), port **3000 w LAN**, `mem_limit` (propozycja ok. 384 MB, suma `aip-` ok. 2240 MB);
   - nie-root, logowanie admina hasłem z `GF_SECURITY_ADMIN_PASSWORD`, bez dostępu anonimowego i rejestracji;
   - strefa wyświetlania `Europe/Warsaw`, interfejs po polsku, jeśli dostępny.
3. **Provisioning jako kod** (repo `grafana/provisioning`):
   - źródło danych PostgreSQL/TimescaleDB jako `app_reader` (hasło z `.env`), `maxOpenConns` ok. 5, `maxIdleConns` ok. 2 (K2-U5);
   - dashboardy jako JSON w repo. Zmiany przez repo; edycja w GUI dozwolona do prób, ale nie jest źródłem prawdy.
4. **Dashboardy** (minimum):
   - **„Licznik na żywo”**: U, P, I, PF, f, Q/S z odświeżaniem 5 s; ostatnia wartość i wykres;
   - **„Stan”**: `link_status` i `meter_status` jako oś stanów w czasie, kafelek stanu licznika uwzględniający `link_status` (K3-U3: „brak danych z PLC”, gdy `link_status ≠ 0` albo ostatni `meter_status` starszy niż kilka sekund), `meter_error_code` przy błędzie, `meter_error_count`;
   - **„Energia”**: zużycie z całki mocy (minuty, godziny), pokrycie, przyrost licznika wzorcowego, `energy_daily_check` z `within_resolution`;
   - etykiety, jednostki i opisy po polsku; brak „przewidywania awarii” w nazwach (zasada 8).
5. **Testy:**
   - provisioning ładuje się bez błędów;
   - źródło danych działa jako `app_reader` (zapis odrzucony);
   - każdy panel zwraca dane z prawdziwej bazy (zapytania przez API Grafany, bez GUI);
   - logowanie anonimowe odrzucone;
   - port 3000 w `ss -ltn`, inne bez zmian.
6. **Czynności Grzegorza** (tylko GUI):
   - zalogowanie z laptopa (`http://192.168.0.213:3000`, hasło z `.env` na laptopie); hasła admina nie zmieniamy w GUI – źródłem jest `.env`;
   - **zrzuty ekranu trzech dashboardów** do `docs/images/etap2/` (pierwsze zrzuty GUI do dokumentacji Word v2).

## Checklista Grzegorza po k6

Brak czynności.

## Następny krok

Claude Code: commit review, `docs/handoff/e2-k7-plan.md` wg „Zakres k7” → stop.
