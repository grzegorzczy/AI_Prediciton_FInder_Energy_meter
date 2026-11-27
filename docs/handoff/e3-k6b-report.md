# E3-k6b – raport (krótki): poprawki wizualne V1–V6

Data: 2026-11-28. Commity: `da8dd5c` (review + zrzuty k6), `0c9fdd1`, `5668bfc`, `781b79c`, `2c38543`, raport. Zmiany tylko
w `grafana/generate.py`, wygenerowanych `flota.json` / `pompa.json` i testach Grafany. Produkcja bez zmian (c299eaa do k7).
**Push nadal odrzucony (403 jako GreJa-Vision)** – commity od `c8f108d` tylko lokalnie; testy na IPC z łatek (`git am`).

## Poprawki

| Id | Zmiana | Sprawdzenie |
| --- | --- | --- |
| V1 | Trend drgań: `timeFrom: 90d` (oś 90 dni) + zakres 90 dni w SQL jak dotąd | test `slow` przy 6 h, 24 h, 7 d i zakresie bezwzględnym (30 dni temu, 1 h): ten sam wynik 65–74 dób |
| V2 | Oś świeżości: kubełki w całości przed pierwszym odczytem urządzenia = NULL (przezroczyste); czerwień tylko po pierwszych danych | test `slow`: przed historią sim `{None}`, w historii „Dane” |
| V3 | Etykiety osi kategorii (oś świeżości, „Udział w energii zakresu”) z dwiema spacjami cyfrowymi (U+2007) z przodu | test generatora; **wizualnie do potwierdzenia na zrzutach k7** |
| V4 | Panel „Dane symulowane”: wysokość 2 → 3, tekst skrócony do 1 zdania (119 znaków) | test generatora (h ≥ 3, ≤ 130 znaków) |
| V5 | Obroty (kafelek i wykres): jednostka `suffix: obr/min`, pełna liczba bez „K”; dane nadal w rpm | test generatora |
| V6 | Flota: jednostka `suffix: kWh` (bez przełączania na Wh) w tabeli (3 miejsca), „Udział w energii zakresu” i „Energia na godzinę” | test generatora |

**V3 – przyczyna:** w kodzie Grafany 13 oś kategorii (oś wierszy osi stanów i oś kategorii wykresu słupkowego) mierzy
szerokość każdej etykiety, ale o kilka pikseli za mało, a szerokości tych osi nie da się ustawić opcją (`axisWidth` działa
tylko na oś wartości). Odstęp z przodu poszerza wyliczoną oś; etykieta jest wyrównana do prawej, więc odstępu nie widać.
Ucięcie mogło się zdarzyć tylko najszerszej etykiecie; nie mogę tego potwierdzić bez podglądu – sprawdzimy na zrzutach w k7.

**V6 – rozszerzenie:** poza kolumną tabeli zmieniłem też jednostkę dwóch wykresów floty, bo na zrzucie 7 dni słupek Findera
w „Udział w energii zakresu” miał „814.26 Wh” obok wartości w kWh.

## Wydajność (V2)

Pierwsza wersja V2 (podzapytanie `min(bucket)` z `energy_1m` w każdym wierszu osi) dawała 8,5 s przy 6 h i timeout przy
24 h. Z `EXPLAIN ANALYZE` (jednorazowy test diagnostyczny na IPC, nie w repo): podzapytanie wykonywało się 2 × 5 005 razy.
Teraz pierwszy odczyt jest liczony **raz na urządzenie** w CTE `MATERIALIZED`: godzina z `energy_1h` (2 ms), dokładny kubełek
z danych zakresu, gdy pierwsza godzina w nim wypada. Oś świeżości: **0,13 s** (w k6: 0,14 s).

## Testy

Grafana z `slow` (`AIP_SLOW_PANELS=1 sh tests/run-tests.sh tests/grafana`): **140 passed** (13,5 min). Wszystkie 16 paneli
≤ 0,24 s, żaden > 1 s. Pełnego zestawu nie uruchamiałem (zmiany tylko w Grafanie).

## Uwagi

1. Urządzenie, które nigdy nie miało danych, ma teraz pustą oś świeżości (a nie czerwoną); w tabeli floty nadal „Brak danych”.
2. Zakres bezwzględny w trendzie drgań: Grafana pomija `timeFrom`, więc oś to zakres pulpitu (dane nadal 90 dni w SQL).
   Dotyczy np. zaznaczenia fragmentu wykresu myszą; zakresy z listy (względne) mają oś 90 dni.
3. Sieć IPC: w czasie k6b połączenia ssh z laptopa kilka razy zrywały się („Connection reset”). Testy szły w tle (`nohup`),
   więc wyniki są pełne, ale to pasuje do zdarzenia z 27.11 do wyjaśnienia w k7.

Raport e3-k6b gotowy do przeglądu.
