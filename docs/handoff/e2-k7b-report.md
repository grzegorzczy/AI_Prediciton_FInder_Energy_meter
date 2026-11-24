# e2-k7b raport: poprawki wyglądu dashboardów K7-V1…V15
Status: DO PRZEGLĄDU

Wykonanie 24.11.2026 wg `e2-k7-visual-review.md` i `e2-k7-report-review.md`, bez osobnego planu. Zmiany wyłącznie w `grafana/generate.py`, wygenerowanych JSON, testach i dokumentach; bez zmian schematu bazy.
Na komputer trafiało tylko to, co jest w `origin/main` (`git pull --ff-only`); Grafana wczytała nowe JSON sama (sprawdzone przez API: nowe tytuły i `timeFrom` w `aip-energia`). Bez `sudo`, bez ruszania smartWARE; `.env` nie czytany.
Commity: `c95ad65` (review i zrzuty), `4633698` (poprawki V1–V15), `6c3d198` (kontrola produkcyjna z własnymi zakresami paneli); komputer na `6c3d198`, `git status` czysty.

## Wynik

| Id | Status | Co zrobiono |
| --- | --- | --- |
| V1 mapa cieplna | **zrobione, z odstępstwem** | jedna skala ciągła zielony → żółty → czerwony dla wszystkich komórek, puste komórki bez koloru, własny zakres panelu **ostatnie 28 dni** (w tytule). Przyczyna błędu: domyślny tryb koloru `palette-classic` kolorował każdą kolumnę (serię) osobno. **Odstępstwo:** komórki pokazują **procent największej średniej mocy w profilu** (0–100%), a nie waty, bo tabela Grafany normalizuje skalę kolorów osobno dla każdej kolumny i nie umiem (bez możliwości sprawdzenia w GUI) wymusić wspólnego zakresu w watach; obok jest kafelek „Maks. średnia moc profilu” [W] = 100% skali |
| V2 „Zużycie na dobę” | zrobione | własny zakres **14 dni** (tytuł), tak samo tabela „Kontrola całki mocy a licznik wzorcowy”; tabela „Zużycie dziś i wczoraj” w „Przeglądzie” czyta daty, nie zakres pulpitu |
| V3 sekundy bez pomiaru | zrobione | brak liczony względem upłyniętej części godziny (`least(now(), bucket + 1 h) − bucket`), godzina w toku jako osobna, jasna seria; oś w sekundach z automatycznymi podziałkami |
| V4 kod błędu przy braku błędów | zrobione | zapytanie dodaje wiersz-wartownik z polem czasu (`UNION ALL SELECT $__timeFrom(), NULL`), panel ma `noValue` „Brak błędów w zakresie”; to samo dla osi stanów |
| V5 „Zużycie na godzinę” | zrobione | słupki wyrównane do początku wiaderka (`barAlignment` = 1); pokrycie godziny w toku liczone względem upłyniętej części, pomarańczowe punkty zamiast spadku do zera |
| V6 „Zużycie na minutę” | zrobione | obie osie od zera (energia i pokrycie 0–100%), panel jako linia zamiast setek słupków; pokrycie bieżącej minuty oznaczone osobno |
| V7 jednostka mocy biernej | zrobione | własny sufiks `suffix: var` (kafelek i wykres „Q”); nie sprawdziłem renderowania |
| V8 obcięte tytuły | zrobione | kafelki na żywo: „U”, „I”, „P”, „Q”, „S”, „PF”, „f” (pełna nazwa w opisie), „Zużycie dziś”, „Zużycie wczoraj”, „Minuty poza pasmem U”, „Minuty z danymi”; test pilnuje długości tytułów kafelków |
| V9 tabela dzisiaj/wczoraj | zrobione | doba jako data `YYYY-MM-DD`, nagłówki „Z pomiarów”, „Pokrycie”, „Ekstrapolacja”, „Licznik”, „Zakończona” (jednostki w opisie), tabela 14 z 24 kolumn |
| V10 oś PF | zrobione | zakres 0–1, 2 miejsca po przecinku (wykres i kafelek) |
| V11 cos φ i Q/P | zrobione | dwa osobne panele; kolorowe tła usunięte: przyczyną było domyślne wypełnienie (8%) linii, teraz **wszystkie linie bez wypełnienia** (test) |
| V12 „Napięcie (min, średnia, maks.)” | **zrobione częściowo** | tło usunięte (neutralne), granice pasma jako czerwone przerywane linie. **Nie zrobiłem czerwonych obszarów poza pasmem:** progi kolorów w Grafanie są stałymi liczbami i nie podążają za zmiennymi `u_nom` i `u_band_pct`; wyjście poza pasmo widać po linii napięcia względem czerwonych linii oraz w kafelku „Minuty poza pasmem U” |
| V13 odchyłka częstotliwości | zrobione | jednostka `suffix: Hz`, 2 miejsca po przecinku (np. 0,20 Hz) |
| V14 układ | zrobione | każdy rząd każdego dashboardu ma szerokość 24 z 24 kolumn (test `test_every_row_of_every_dashboard_spans_the_full_grid_width`); kafelki „Jakości” mają wysokość napięcia; ostatni wykres „Na żywo” na pełną szerokość |
| V15 „Wiersze na minutę” | zrobione | bieżąca, niepełna minuta pomijana (`time < date_trunc('minute', now())`) |

## Spójność: „Epizody błędu licznika dziś” = 41 a `meter_error_count` = 18

Różnica ma dwie, sprawdzone w bazie przyczyny:
1. **41 = 5 + 36.** 5 epizodów było od północy lokalnej do zaniku zasilania (23:00–23:16 UTC 23.11, licznik PLC doszedł wtedy do 62) i 36 po powrocie zasilania. Kafelek liczy przejścia `meter_status` 0 → ≠ 0 w bazie od północy lokalnej, więc obejmuje oba okresy.
2. **Licznik PLC wyzerował się drugi raz, najpewniej przy restarcie PLC o 14:25 UTC.** Po powrocie zasilania licznik doszedł do 25 (ostatni epizod 12:08), a od 16:23 liczy od 1; w bazie w 14:25:03–14:25:20 jest `link_status` = 1 przez 18 s, co wskazuje na restart PLC (to wnioskuję z danych, nie mam potwierdzenia).
   Epizody trwały do 17:07, więc w chwili zrzutów licznik pokazywał 18 (od 16:23), a w bazie jest 36 epizodów po powrocie zasilania (18 do 12:08 i 18 od 16:23). Restart PLC nie był moją czynnością (nie dotykam PLC); przyczyna nieznana.
Opis kafelka dopisałem: liczba z bazy od północy, także sprzed zaniku zasilania lub restartu PLC; `meter_error_count` zeruje się przy restarcie PLC i nie musi się z nią zgadzać.

## Testy i wdrożenie

- Pełny zestaw na komputerze: **414 z 414** (3 testy wydajnościowe pomijane w zwykłym przebiegu), 8 min 43 s, bez resztek `aip-test`. Nowe testy statyczne dla V1–V15 (7) w `tests/grafana/test_grafana_generator.py`; harness paneli uwzględnia własne zakresy paneli (`timeFrom`) i wiersze-wartowniki; generator bez dryfu.
- Produkcja: **156 zapytań paneli (zakresy 15 min, 24 h, 7 d), 0 błędów**; panele z własnym zakresem zwracają dane (profil 18 komórek, doby 2 wiersze).
- Wydajność na roku danych po zmianach (powtórzony pomiar): wszystkie panele < 1 s, najwolniejszy 346 ms; profil (28 dni) i „Maks. średnia moc profilu” 31 ms.

## Czego nie sprawdziłem

Wyglądu po zmianach (nadal bez logowania w przeglądarce): w szczególności jak Grafana narysuje **mapę cieplną z kolorem ciągłym**, **jednostkę `suffix: var`**, **pomarańczowe punkty pokrycia w toku**, **osie stanów z wierszem-wartownikiem** i **szerokości kafelków** (czy nic się nie obcina). To oceniają nowe zrzuty Grzegorza.

## Dla Grzegorza

Nowe zrzuty pięciu dashboardów z zakresem **„Ostatnie 24 godziny”**, te same nazwy plików w `docs/images/etap2/` (nadpiszą wersje sprzed poprawek; stare zostają w historii gita).
Po ewentualnych uwagach z nowych zrzutów: następny krok to **E2-PLC2** albo **k8** (decyzja Grzegorza).
