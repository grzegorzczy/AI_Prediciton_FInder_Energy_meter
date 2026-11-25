# e2-k7c raport: poprawki wyglądu W-1…W-9, okno A-1 i rozkład epizodów
Status: DO PRZEGLĄDU

Wykonanie 25.11.2026 wg `e2-k7b-visual-review.md` (zakres zamknięty, bez osobnego planu). Zmiany: `grafana/generate.py` i wygenerowane JSON, migracja `005`, testy, dokumenty. Na komputer trafiało tylko to, co jest w `origin/main`
(`git pull --ff-only`); bez `sudo`, bez ruszania smartWARE, PLC i `.env`. Commity: `ebfd912` (review i zrzuty), `0e585b5` (W-1…W-9 i A-1), raport w osobnym commicie po nim.

## Wynik

| Id | Status | Co zrobiono |
| --- | --- | --- |
| W-1 mapa cieplna | zrobione | skala jednobarwna `continuous-blues` (jasny → ciemny niebieski), liczba w komórce zostaje; brak danych = przezroczysta komórka bez liczby (mapowanie specjalne `null+nan` z kolorem `transparent`); opis panelu: „profil zużycia, nie ocena dobrze/źle”. Kafelek obok skrócony do „Moc maks. profilu” i poszerzony (6 z 24 kolumn) |
| W-2 kod błędu | zrobione | oś pokazuje kod tylko w czasie błędu, a po każdym epizodzie wiersz „0” = **„Brak błędu” (zielony)**; 161, 162, 163 mają różne kolory (pomarańczowy, czerwony, fioletowy). Test na danych: ciąg zaczyna i kończy się zerem, a kody 162 przeplatają się z zerami |
| W-3 minuta | zrobione | energia niepełnej, bieżącej minuty nie jest rysowana (jej pokrycie zostaje jako pomarańczowy punkt); oś w jednostce `suffix: Wh` z 3 miejscami, bez mieszania mWh i Wh |
| W-4 definicje pokrycia | zrobione | jedna nazwa „**Pokrycie upłynionej części (w toku)**” na minucie, godzinie i dobie i w opisach tych paneli; w tabelach kolumna „**Pokrycie doby**” (cała doba), opis tabeli „Zużycie dziś i wczoraj” odróżnia ją od kafelka „Pokrycie danych od północy” |
| W-5 osie | zrobione | `decimals` = 2 w obu panelach porównań „bieżący zakres a poprzednia doba / tydzień” i w mocy bazowej |
| W-6 moc bazowa | zrobione | słupki (jedna wartość na dobę jest teraz widoczna) |
| W-7 tytuły i nagłówki | zrobione | „Poza pasmem U [min]” i „Z danymi U [min]” (kafelki 5 z 24 kolumn zamiast 4), „Moc maks. profilu”; tabela kontrolna: „Licznik [Wh]”, „Ekstrap. [Wh]”, „Rozdz. [Wh]”, „W rozdz.”, „Zakończona”, „Luki” (skróty objaśnione w opisie), `minWidth` 50 i wyrównanie do prawej; tabela „Zużycie dziś i wczoraj” w Przeglądzie poszerzona do 16 z 24 kolumn |
| W-8 „Wartości w oknie” | zrobione | wysokość 9 zamiast 7 |
| W-9 granice pasma | **zrobione, przyczyny nie ustaliłem** | obie granice (napięcie i częstotliwość) mają ten sam kolor czerwony i grubość 2 (poprzednio 1). Dlaczego górna wyglądała na szarą, nie wiem: nie widzę renderowania. Hipoteza: linia leżąca dokładnie na brzegu obszaru wykresu jest przycinana. Dlatego dodałem **niewidoczne serie „Zakres osi”** (poza pasmem o 2 V i o 10%), które dają oś z zapasem; są ukryte w legendzie, dymku i wykresie (grubość 0). Jeśli na nowym zrzucie górna linia nadal jest szara, hipoteza jest błędna |
| A-1 okno | zrobione | migracja `005_data_windows_plc_program_download.sql` (nowa, stare bez zmian); rodzaj `plc_program_download`, granice z bazy **2026-11-24 14:25:03,390 – 14:25:20,392 UTC** (pierwszy i ostatni wiersz `link_status` = 1: 18 wierszy, 17,002 s; pierwszy wiersz OK po nim 14:25:22,514), opis „Download programu PLC (Grzegorz), reset liczników FB”, `exclude_from_analytics` = TRUE. Ograniczenie rodzaju w tabeli to tylko wzorzec `^[a-z0-9_]+$`, więc listy rodzajów nie trzeba było rozszerzać. Na produkcji: 11 okien, wiersz zgodny z bazą (18 wierszy `link_status` = 1 w tych granicach) |

**Skąd „16” w pasku kodu błędu:** to nie epizody ani kod, tylko **ucięty tekst**. Epizody trwają ok. 4 s, więc przy zakresie 6 h to wąskie paski, a ich opis („161 RESPONSE_TIMEOUT”, „162 RESPONSE_CRC_FAIL”) jest przycinany do pierwszych znaków; tekst „16” widać więc z paska, który się nie mieści. Brak długiego paska kodu po 01:00 wynikał z błędu zapytania: nie było wiersza zamykającego, więc stan ostatniego kodu ciągnął się do końca zakresu (naprawione w W-2). Opis panelu mówi teraz, że etykiety wąskich pasków bywają ucięte i że trzeba przybliżyć wykres.

## Testy i wdrożenie

- Pełny zestaw na komputerze: **420 z 420** (3 testy wydajnościowe pomijane w zwykłym przebiegu), 8 min 47 s, bez resztek `aip-test`. Nowe testy: kolor i przezroczystość mapy cieplnej, kolory kodów, zamykanie epizodów na danych (przez API Grafany), nazwy pokrycia, `decimals`, nagłówki, wysokość, kolor i zapas osi pasm, dokładne granice okna A-1.
- Wdrożenie: `git pull --ff-only` i **`docker compose up -d --build`** (sam `up -d` nie zastosował migracji `005`: pliki migracji są wbudowane w obraz `migrate`, więc potrzebny jest `--build`; zauważyłem to po pierwszej próbie, nic się nie zepsuło: `done: 0 applied, 4 already applied`). Po drugiej próbie: `applied 005_data_windows_plc_program_download.sql`. Przy okazji Compose odtworzył kontener Grafany (restart ok. 5 s); dashboardy wczytały się same.
- Produkcja: **208 zapytań paneli (zakresy 15 min, 6 h, 24 h, 7 d, z własnymi zakresami paneli), 0 błędów**; Grafana `healthy`, **0 wpisów `level=error` w logu** (dwa błędy o brakujących katalogach provisioningu z k7 zniknęły po dodaniu pustych katalogów), pamięć 170 MiB z 384 MiB; w `ss -ltn` tylko port 3000 jako nowy, `StartedAt` smartWARE bez zmian.

## Zapytanie o rozkład epizodów (tylko odczyt)

Epizod = przejście `meter_status` z 0 na wartość ≠ 0; godziny w czasie lokalnym `Europe/Warsaw`; liczba wierszy `link_status` pokazuje, czy w danej godzinie były dane (3600 = pełna godzina):

```sql
WITH s AS (
  SELECT time, value, lag(value) OVER (ORDER BY time) AS prev
  FROM measurements
  WHERE device_id = 'finder_7m24_1' AND metric = 'meter_status' AND time >= '2026-11-22 23:00+00'
),
e AS (SELECT time FROM s WHERE value <> 0 AND prev = 0),
hours AS (
  SELECT h FROM generate_series(date_trunc('hour', timestamptz '2026-11-22 23:00+00'), date_trunc('hour', now()), interval '1 hour') h
)
SELECT to_char(h AT TIME ZONE 'Europe/Warsaw', 'YYYY-MM-DD HH24:00') AS godzina_lokalna,
       count(e.time) AS epizody,
       (SELECT count(*) FROM measurements m WHERE m.device_id = 'plc-01' AND m.metric = 'link_status'
          AND m.time >= h AND m.time < h + interval '1 hour') AS wiersze_link_status
FROM hours LEFT JOIN e ON e.time >= h AND e.time < h + interval '1 hour'
GROUP BY h ORDER BY h;
```

Wynik za 23.11 00:00 – 25.11 06:00 (55 godzin; w 48 godzinach nie było żadnego epizodu, wypisuję godziny z epizodami):

| godzina lokalna | epizody | wiersze `link_status` w godzinie |
| --- | --- | --- |
| 2026-11-23 23:00 | 12 | 1 165 (dane od 23:38, zanik zasilania o 00:16) |
| 2026-11-24 00:00 | 5 | 988 (zanik zasilania od 00:16) |
| 2026-11-24 12:00 | 17 | 2 697 (przerwa diagnostyczna 12:03–12:18) |
| 2026-11-24 13:00 | 1 | 3 600 |
| 2026-11-24 17:00 | 16 | 3 600 |
| 2026-11-24 18:00 | 2 | 3 600 |
| 2026-11-25 00:00 | 14 | 3 600 |

**Fakty do `e2-plc1`:** epizody przychodzą **seriami** w czterech odcinkach: (1) 23.11 ok. 23:38–00:16 lokalnie (17 epizodów przed zanikiem zasilania), (2) 24.11 ok. 12:01–13:08 lokalnie (18), (3) 24.11 ok. 17:23–18:07 lokalnie (18), (4) 25.11 ok. 00:35–01:00 lokalnie (14, a architekt przy ręcznym liczeniu widział 15).
W seriach epizody mają odstęp 64 lub 128 s (co drugi punkt siatki 64 s); między seriami są godziny bez żadnego epizodu (np. 01:00–06:00 lokalnie 25.11, ok. 14:00–17:00 lokalnie 24.11). Ani stałej siatki przez całą dobę, ani zależności od pory dnia nie widzę. Zakres danych to ok. 2 doby, więc to opis, a nie wniosek o przyczynie.

## Czego nie sprawdziłem

Wyglądu po zmianach (nadal bez logowania w przeglądarce): przede wszystkim **przezroczystość pustych komórek** mapy cieplnej (kolor `transparent` w mapowaniu specjalnym), **ciągłą skalę niebieską**, **kolory 161/162/163 i napisy na wąskich paskach**, **czerwony kolor górnej granicy pasma** (W-9, hipoteza opisana wyżej) oraz to, czy tabele (Przegląd i kontrola) mieszczą się bez przewijania poziomego. Ocenią to nowe zrzuty.

## Dla Grzegorza

Nowe zrzuty **05, 06, 06b, 06c, 07** (te same nazwy plików, zakres jak poprzednio), po wdrożeniu nic więcej nie trzeba robić na komputerze.
Następny krok po przeglądzie: E2-PLC2 albo k8 (decyzja Grzegorza).
