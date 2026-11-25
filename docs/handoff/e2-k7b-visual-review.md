# E2-k7b – review wizualny dashboardów (architekt)

Data: 2026-11-25, ok. 06:10 czasu lokalnego. Podstawa: 10 zrzutów Grzegorza z laptopa
(zakresy 3 h i 6 h, profil 28 d, kontrola 14 d), zapisane w `docs/images/etap2/`:
03, 04, 04b, 05, 05b, 06, 06b-profil, 06c-kontrola, 07, 07b.

**Werdykt: OK Z UWAGAMI.** Dane są spójne i wiarygodne, dashboardy nadają się do pracy.
Do poprawy jest krok **k7c**. Obejmuje usterki wizualne (W-1…W-9) i jedno okno adnotacji (A-1).
Krok jest mały, bez zmian w bazie poza migracją z oknem.

## Co jest dobrze (sprawdzone na zrzutach)

- Przegląd: stany licznika i PLC, moc 7,0 W, wiek odczytu 611 ms, pokrycie od północy 99,7 %.
  „Epizody błędu licznika dziś” = 14, zgodnie ze skokiem `meter_error_count` 18 → 32 na zrzucie 07.
- Jednostka „var” jest przy Q (kafelek, tabela i wykres). Ujemne Q przy PF 0,37 pasuje do obciążenia pojemnościowego (zasilacz).
- Wiersze na minutę ≈ 780, czyli 13/s. Na wykresie widać lekki spadek w czasie epizodów błędu (5/s).
- Kontrola całki za 24.11: całka 112,8 Wh przy pokryciu 66,8 %, ekstrapolacja 168,9 Wh, licznik +100 Wh.
  Wynik `within_resolution = true` jest zgodny z D7.
- Histogram napięcia, Q/P, odchyłka częstotliwości: czytelne.

## Obserwacja do E2-PLC1 (nie do poprawy w k7c)

Epizody błędu licznika 25.11 przyszły **seriami**: 15 epizodów między ok. 00:35 a 01:00 czasu lokalnego,
potem 5 h bez żadnego. Nie jest to stała siatka 64 s przez całą dobę.
Do zapisania w `e2-plc1` jako fakt. Proszę o zapytanie SQL z godzinowym rozkładem epizodów
za 23–25.11 w raporcie k7c (tylko odczyt).

## Uwagi do poprawy (k7c)

**W-1 (ważna) – mapa cieplna: brak danych wygląda jak wartość.** W panelu „Profil: godzina × dzień tygodnia”
komórki bez danych są zielone, tak samo jak niskie wartości. Przykład: wtorek 1–6 to zanik zasilania, a komórki są zielone.
Komórki z danymi (~99–100 %) są czerwone, więc stałe obciążenie wygląda jak alarm.
Poprawka:
- brak danych = przezroczysta lub szara komórka bez liczby;
- skala jednobarwna (sekwencyjna, np. jasny → ciemny niebieski), bez zieleni i czerwieni,
  bo to profil zużycia, nie ocena dobrze/źle;
- liczba w komórce zostaje.

**W-2 (ważna) – „Kod błędu komunikacji” (07).** Pasek „16 161 RESPONSE_TIMEOUT” ciągnie się przez cały zakres
do 06:10, choć od ok. 01:00 nie ma błędów, a `meter_error_code` = 0 przy sprawnym liczniku.
Wygląda to na trwający timeout. Poza tym 161 i 162 mają w legendzie ten sam niebieski kolor,
a prefiks „16” jest niejasny. Poprawka:
- oś stanów ma pokazywać kod tylko w czasie `meter_status ≠ 0`, a poza tym „Brak błędu” (zielony);
- 161, 162 i 163 dostają różne kolory;
- liczbę epizodów, jeśli to jest „16”, trzeba przenieść do opisu panelu albo osobnego kafelka.
W raporcie wyjaśnić, skąd było „16”.

**W-3 – Zużycie na minutę (06).** Na końcu wykresu linia spada, bo bieżąca minuta jest niepełna.
Wygląda to na spadek zużycia. Poprawka: niepełnego wiaderka nie rysujemy w linii energii.
Jego pokrycie zostaje jako pomarańczowy punkt. Oś: „125.000 mWh” → maks. 1 miejsce po przecinku
albo jednostka Wh z 3 miejscami, bez mieszania mWh/Wh.

**W-4 – Pomarańczowy punkt „w toku” (06).** Na godzinie i dobie stoi na 100 %, a tabela w Przeglądzie
podaje dla dziś 25 %. To dwie różne definicje: pokrycie upłynionej części albo pokrycie całego wiaderka.
Obie są poprawne, ale nie mogą stać obok siebie bez opisu. Poprawka: w opisie panelu i legendzie
„Pokrycie upłynionej części (w toku)”. W tabeli Przeglądu kolumnę nazwać „Pokrycie doby”.

**W-5 – Osie z powtórzonymi etykietami (06b).** Panele „Moc: bieżący zakres a poprzednia doba / tydzień”
mają trzy etykiety „7.1 W” (również 06c: „7.0 W” ×2). Poprawka: `decimals` = 2 dla mocy w tych panelach.

**W-6 – Moc bazowa (06c).** Jeden punkt na noc nie rysuje się jako linia, więc panel wygląda na pusty
(wartość widać tylko w dymku: 7,0 W). Poprawka: słupki albo punkty (`pointSize` ≥ 6, `showPoints: always`).

**W-7 – Obcięte tytuły i nagłówki.**
- 05: „Minuty poza pasme…”: krótszy tytuł („Minuty poza pasmem U”) albo szerszy kafelek.
- 06b: kafelek „M…” obok mapy cieplnej: szerszy albo tytuł „Moc maks.”.
- 06c: nagłówki tabeli kontrolnej („rzyrost licznika”, „łniona do doby”, „W granicach rozdziel”): krótsze nazwy
  (np. „Licznik [Wh]”, „Ekstrap. [Wh]”, „W rozdz.”) albo ustawione szerokości kolumn.
- 03: tabela „Zużycie dziś i wczoraj” ma poziomy pasek przewijania; zmieścić bez przewijania.

**W-8 – Tabela „Wartości w oknie” (04).** Wiersz napięcia jest ucięty i trzeba przewijać.
Panel ma pokazać wszystkie 7 wielkości bez przewijania (wyższy panel).

**W-9 – Granice pasma (05, 05b).** Legenda mówi „Górna granica pasma” na czerwono, a górna linia przerywana
jest szara (napięcie i częstotliwość). Dolna jest czerwona. Obie mają być w tym samym kolorze, zgodnie z legendą.

Drobne, bez zmian: PF na skali 0–1 jest płaski przy stałym obciążeniu; zostaje stała skala,
bo przy zmiennym obciążeniu porównanie jest czytelniejsze.

## A-1 – nowe okno adnotacji

Grzegorz potwierdził 25.11: **24.11 ok. 15:25 czasu lokalnego (ok. 14:25 UTC) wgrał program do PLC**
(download z CODESYS po poprawce `FB_EnergyMeter`). To wyjaśnia 18 s `link_status = 1` i wyzerowanie `meter_error_count`.
Dodać okno do `data_windows` nową migracją (bez zmiany starych):
- rodzaj `plc_program_download`;
- dokładne granice wziąć z bazy (pierwsza i ostatnia sekunda `link_status = 1` w tym epizodzie);
- opis: „Download programu PLC (Grzegorz), reset liczników FB”.

Jeśli w `data_windows` jest ograniczenie listy rodzajów, rozszerzyć je w tej samej migracji.

## Zakres k7c i kolejny krok

k7c = W-1…W-9 + A-1 + zapytanie o rozkład epizodów. Testy i zapytania paneli na produkcji jak w k7b.
Po wdrożeniu Grzegorz robi ponownie tylko zrzuty 05, 06, 06b, 06c, 07, z tymi samymi nazwami.
Plan k7c można pominąć (zakres zamknięty w tym pliku); raport `e2-k7c-report.md`.

Kolejność dalej (decyzja Grzegorza do podjęcia): E2-PLC2 albo k8.
