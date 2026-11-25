# E2-k8c – raport (poprawki po review wizualnym k8a: K8-V1…V7)

Data: 2026-11-25. Review: `e2-k8a-visual-review.md` (z dopiskiem 13:40). Bez osobnego planu (jak uzgodniono). Wdrożone jednym R-1; bez sudo, bez ruszania smartWARE, bez czytania `.env`.
Commity: `ebf7c2d` (V1–V3 + zrzuty z review), `6104ad0` (V5–V7, review 13:40, zrzuty 06/06b/06c), `e64c57f` (poprawka testu 009), ten raport. Pliki z `docs/handoff` i `docs/images` zapisane przez architekta commitowałem takie, jakie są na dysku (bez `checkout`/`restore`); przed każdym commitem sprawdzałem `git status`. Nietknięty, niedodany do repo: `AI_Predykcja_dokumentacja_v2.docx` (nie był w zakresie).

## K8-V1 – oś stanów „Brak danych” po luce (ważna)

Hipoteza architekta była trafna. `_states` wstawiał wiersz „Brak danych” (100) na początku luki, ale wiersze stanu wybierał tylko przy **zmianie** wartości (`prev IS DISTINCT FROM value`), więc po luce ze stanem 0 → 0 nie było wiersza powrotu i oś zostawała w „Brak danych” do końca zakresu.
Poprawka (`grafana/generate.py`, `_states`): dodany `lag(time)` i warunek `OR time - prev_time > make_interval(secs => $stale_s)`, czyli pierwszy wiersz po luce dłuższej niż próg jest zawsze wierszem stanu.
Testy: (a) `test_state_timeline_resumes_after_a_gap_without_a_change_of_state` (2 osie) na danych z 10-minutową luką ze stanem 0 przed i po (luka sprzed 3 godzin w danych testowych): po każdym „100” następny wiersz to stan, a oś nie kończy się w „Brak danych”; (b) test struktury zapytania.
**Sprawdzenie na produkcji** (API Grafany, ostatnie 3 h): `link_status` i `meter_status` mają po każdym „100” powrót do 0: 11:58:09 → 100, 11:58:15 → 0 (wdrożenie) oraz 12:03:57 → 100, **12:04:24 → 0** (restart). Przed poprawką brakowało drugiego wiersza w obu parach.

## K8-V2 – pełne nazwy w kafelkach Licznika na żywo

Tytuły: Napięcie U, Prąd I, Moc czynna P, Moc bierna Q, Moc pozorna S, Współczynnik mocy PF, Częstotliwość f, THD napięcia, THD prądu, Kąt U–I, Temperatura licznika. Test `test_live_tiles_have_full_names_and_fit_their_width` (dokładna lista i górny limit długości względem szerokości kafelka: 4 + 6 znaków na kolumnę; najwęższe kafelki mają 3 kolumny). Wykresy poniżej mają te same tytuły co kafelki (jak wcześniej, np. „Kąt U–I”); testy kluczowane tytułem biorą wtedy wykres.

## K8-V3 – tabela „Wartości w oknie”

Wysokość panelu 12 → 14 jednostek (524 px). Test `test_live_values_table_height_fits_all_rows_without_scrolling` liczy z SQL liczbę wielkości (11) i wymaga wysokości ≥ (11 + 1) × 36 px + 56 px. Wiersz 36 px to moje założenie dla `cellHeight: sm` w Grafanie 13 – **do potwierdzenia zrzutem** (nie mam podglądu przeglądarki użytkownika).

## K8-V4 – „Epizody błędu licznika dziś” = 36 (tylko opis)

Zapytanie jak kafelek, od północy lokalnej: **36 przejść `meter_status` 0 → ≠ 0**, wszystkie z okresu **mapy v1** (mapa v2 od 10:43 UTC = 11:43 lokalnie):

| Seria (czas lokalny) | Epizody | Odstęp |
| --- | --- | --- |
| 00:24:06 – 00:49:42 | 13 | co 128 s |
| 00:56:06 | 1 | (po 6,4 min) |
| 08:23:02 – 09:09:58 | 22 | co 128 s |

Każdy epizod trwa ok. 4 s (średnia i maksimum 4,0 s). Kody błędu od północy: 162 (123 wiersze) i 161 (20 wierszy). Po 09:10 lokalnie żadnego epizodu; **pod mapą v2 zero** (ponad 2 godziny). Zgodne z E2-PLC1 (błędy CRC seriami, odstęp 128 s zamiast 64 s z k5); fakty dopisane do `docs/stages/etap-2.md`, sekcja „Znane ograniczenia”. Link_status ≠ 0: 20 wierszy od 09:16 lokalnie (przerwy wdrożeń/PLC), niezwiązane z epizodami licznika.

## K8-V5 – etykiety osi „Energia bierna na dobę: całka i licznik”

Przyczyna jak w opisie: „23.11” było odczytywane jako liczba 23,11 i dostawało jednostkę „varh”. Etykieta doby jest teraz tekstem z dniem tygodnia: „23.11 Pon”, „25.11 Śr” (`_day_label`, jednoznacznie nie-liczbowa, dodatkowo informacyjna); jednostka tylko na osi wartości. Opis panelu wyjaśnia pustą serię licznika (dane od 25.11.2026 10:43 UTC; do pierwszego kroku n4, co 100 varh, seria jest pusta lub zerowa). Test na bazie testowej: żadna z etykiet nie daje się odczytać jako liczba (`float()` zgłasza błąd), format „DD.MM Dzień”; test opisu i jednostki.
Uwaga: nie mogę wizualnie potwierdzić, że Grafana nie zinterpretuje tekstu inaczej – **do potwierdzenia zrzutem**.

## K8-V6 – „Moc bazowa” z własnym zakresem

Panel zmieniony z wykresu czasowego na **wykres słupkowy z osią kategorii** (jak „Zużycie na dobę”: wykres czasowy zawsze przycina oś do zakresu pulpitu, więc przy 1 h nie byłoby nocy nawet z zakresem w SQL). Tytuł: „Moc bazowa (5. percentyl nocą, ostatnie 14 nocy)”, zakres liczony w SQL od „teraz” (`OWN_RANGE_MARKER['daily']`), niezależny od pulpitu; etykiety „DD.MM Dzień”. Panel dopisany do `OWN_RANGE_PANELS` (test: bez `$__timeFilter`, opis „niezależnie od zakresu pulpitu”, ten sam wynik dla trzech zakresów pulpitu) i do testu danych: przy zakresie 15 min zwraca 10–15 słupków. Na produkcji są dziś 2 noce (dane od 23.11 wieczorem), więc 2 słupki; liczba wzrośnie z czasem do 14.

## K8-V7 – profil bez poziomego przewijania

Kolumny: `custom.minWidth` 40 px (Grafana domyślnie 150 px na kolumnę, 8 kolumn = 1200 px, więcej niż mieści panel 18 z 24 kolumn na węższym ekranie), wyrównanie do środka. Test: `minWidth ≤ 60` i `8 × minWidth ≤ 480`, siedem kolumn dni obecnych w SQL. Panel nie został poszerzony (kafelek „Moc maks. profilu” zostaje). **Do potwierdzenia zrzutem** (06b).

## Testy

- **Pierwszy pełny przebieg (po V1–V3, `ebf7c2d`):** 500 passed, 3 skipped, **1 failed, 3 errors** (692 s). Błędy to awaria bazy testowej w środku przebiegu („server closed the connection unexpectedly”, potem „database system is not yet accepting connections” – baza testowa w `aip-test` przeszła crash recovery); w dzienniku jądra **brak** wpisu OOM w tym oknie. Przyczyny nie ustaliłem; w kolejnym pełnym przebiegu się nie powtórzyło.
- **Drugi pełny przebieg (po V1–V7, `6104ad0`):** 506 passed, 3 skipped, **1 failed** (691 s): `test_hourly_rows_are_identical_before_and_after_for_data_without_null_edges` (z k4). Przyczyna: dokładne porównanie sum zmiennoprzecinkowych agregatu, które różnią się w ostatniej cyfrze zależnie od kolejności sumowania (np. 4676772.487360175 i …174). To flaky test w moim kodzie, nie błąd agregatu (liczby całkowite, NULL i czasy identyczne). Poprawka: porównanie do 9 cyfr znaczących (`rounded`), bez rozluźniania pozostałych kolumn.
- Po poprawce `tests/db/test_energy_1h_filter.py`: **10 passed × 3 uruchomienia**. Pełnego zestawu po tej jednej zmianie testowej nie powtarzałem (zmiana dotyczy tylko tego pliku).
- Łącznie nowych testów w k8c: 8 (generator: 5 + struktura osi stanów + panele; harness paneli: 2).

## Wdrożenie R-1

`git pull --ff-only` na IPC (HEAD `e64c57f`), kontrola praw (puste), `docker compose up -d --build`: **bez odtwarzania kontenerów** (zmieniły się tylko pliki dashboardów montowane z repo; `migrate` uruchomiony ponownie: `0 applied, 11 already applied`, `schema_migrations` = 11). Sumy kontrolne plików dashboardów w kontenerze i w repo identyczne. Grafana wczytała nowe wersje (provisioning, API): `na-zywo` v5 z 11 nowymi tytułami kafelków i tabelą h = 14, `energia` v7 z panelami „Moc bazowa…” i „Energia bierna…” jako wykresy słupkowe, `diagnostyka` v5 z zapytaniem z `prev_time`. Bez luki w danych (kolektor, ingest, baza, Mosquitto niezmienione).
Harness produkcyjny (`prod_panels.py`, 15m/6h/24h, pojedynczo, przerwa 0,2 s): **207 zapytań, 0 błędów**; log Grafany: 0 błędów od startu. Pamięć Grafany podczas harnessu nie przekroczyła limitu (bez OOM; pomiar po dobie w części B).

## Do zrobienia przez Grzegorza (zrzuty po wdrożeniu)

Dashboard „Licznik na żywo” (kafelki z pełnymi nazwami, tabela bez przewijania), „Stan i diagnostyka” (osie stanów po luce z restartu 12:04 i wdrożenia 11:58), „Energia i profil” (etykiety osi energii biernej „DD.MM Dzień”, moc bazowa 14 nocy, profil z 7 dniami bez przewijania). Zrzuty 04, 04b/04c, 07, 06, 06b, 06c do wymiany; jeśli któryś punkt nadal wygląda źle, opisz co – poprawię.

## Dalej

Część B (po 26.11 12:00 UTC): kompresja, RAM po dobie (szczególnie Grafana), n4, `e2-k8b-report.md`.
Stop: czekam na review architekta k8c.
