# e2-k7 visual review: wygląd dashboardów (zrzuty Grzegorza 24.11.2026, ok. 23:05)

Architekt, 24.11.2026. Zrzuty (zakres „Ostatnie 3 godziny”, przed poprawkami): `docs/images/etap2/03-grafana-przeglad.png`, `04-grafana-na-zywo.png`, `04b-…-dol.png`, `05-grafana-jakosc.png`, `05b-…-dol.png`, `06-grafana-energia.png`, `07-grafana-diagnostyka.png`, `07b-…-dol.png`.

## Ocena ogólna

**Dobrze:**
- logowanie z laptopa działa (port 3000 przechodzi przez sieć);
- interfejs po polsku;
- dane się zgadzają (U ok. 237 V, P 7,0 W, PF 0,37, f 49,98 Hz);
- kafelki stanu („Licznik działa”, „PLC działa”), osie stanów, linki między dashboardami, przełącznik „Okna testów i przerw”, histogram napięcia, odchyłka częstotliwości z pasmem.

Poniżej poprawki wyglądu. Wszystkie dotyczą `grafana/generate.py` i zapytań paneli, bez zmian schematu bazy.

## Poprawki (K7-V1…V14)

### Błędy (mylą odczyt – obowiązkowe)

- **K7-V1 – mapa cieplna („Energia i profil”).** Komórki są kolorowane **kolumnami** (każdy dzień inny kolor), a nie wartością. Puste komórki też są kolorowe. Wymagane:
  - jedna skala ciągła dla wszystkich komórek według wartości (wspólne min i maks. całej tabeli, np. schemat od zielonego przez żółty do czerwonego);
  - puste komórki bez koloru;
  - panel ma **własny zakres czasu niezależny od pulpitu** (np. ostatnie 4 tygodnie, opisany w tytule). Przy 3 h pokazuje tylko 3 wiersze godzin.
- **K7-V2 – „Zużycie na dobę”** pokazuje „Dane poza zakresem czasu” przy zakresie 3 h. Panel ma własny zakres (np. ostatnie 14 dni), podobnie jak tabela „Zużycie dziś i wczoraj” w „Przeglądzie”, która ma zawsze pokazywać obie doby.
- **K7-V3 – „Sekundy bez pomiaru mocy na godzinę”.** Bieżąca godzina pokazuje ok. 55 min braku, bo nieupłynięta część godziny liczy się jako brak. Liczyć brak tylko względem upłyniętej części wiaderka (`LEAST(now(), bucket + 1h) − bucket`) albo nie pokazywać wiaderka w toku. Oś w sekundach albo minutach z czytelnymi podziałkami.
- **K7-V4 – „Kod błędu komunikacji PLC–licznik”:** „Dane nie mają pola czasu”, gdy w zakresie nie ma błędów. Pusty wynik ma mieć kolumnę czasu albo panel ma pokazywać „Brak błędów w zakresie” (`noValue`), a nie komunikat techniczny.
- **K7-V5 – „Zużycie na godzinę”:** słupki są przesunięte o pół godziny względem osi (wiaderko 21:00 rysowane na 20:45–21:15). Wyrównać słupki do początku wiaderka. Pokrycie wiaderka w toku oznaczyć (np. przerywaną linią lub innym kolorem jak w „Diagnostyce”), żeby spadek do zera na końcu nie wyglądał na awarię.
- **K7-V6 – „Zużycie na minutę”:** oś Y zaczyna się od ok. 85 mWh, a oś pokrycia od 75%, więc słupki wyglądają na mocno zmienne. Obie osie od 0. Przy zakresach > 6 h rozważyć linię zamiast setek słupków.

### Czytelność (zalecane)

- **K7-V7 – jednostka mocy biernej:** „reactivevoltamp” to surowy identyfikator jednostki. Użyć jednostki, która wyświetla `var`. Jeśli wybrana wersja Grafany jej nie ma, ustawić własny sufiks ` var`. Dotyczy kafelka i wykresu „Moc bierna Q”.
- **K7-V8 – obcięte tytuły kafelków:** „Napięcie …”, „Moc czyn…”, „Zużycie dziś (z po…”, „Minuty z napięciem…”, „Minuty z danymi na…”. Skrócić tytuły (np. „U”, „I”, „P”, „Q”, „S”, „PF”, „f” z opisem w `description`; „Zużycie dziś”, „Minuty poza pasmem U”, „Minuty z danymi”) albo poszerzyć kafelki.
- **K7-V9 – „Zużycie dziś i wczoraj” (tabela):**
  - kolumna „Doba” pokazuje `2026-11-24 01:00:00` (północ UTC w czasie lokalnym) – pokazywać samą datę lokalną;
  - nagłówki są obcięte i jest przewijanie poziome – krótsze nagłówki („Z pomiarów”, „Pokrycie”, „Ekstrapolacja”, „Licznik”) z jednostką w opisie.
- **K7-V10 – „Współczynnik mocy PF” (wykres):** oś z samymi „0.37” – ustawić 3 miejsca po przecinku lub automatyczne podziałki.
- **K7-V11 – „Współczynnik mocy (cos φ) i stosunek Q/P”:**
  - kolorowe tła progów (zielone i żółte) nic nie znaczą – usunąć;
  - cos φ (0–1) i Q/P (ok. −1,2) na osobnych osiach albo w osobnych panelach.
- **K7-V12 – „Napięcie (min, średnia, maks.)”:** całe tło jest zabarwione. Kolorować tylko obszary **poza** pasmem (na czerwono), a pasmo zostawić neutralne.
- **K7-V13 – „Odchyłka częstotliwości”:** oś „200.000 mHz” – jednostka mHz bez miejsc po przecinku albo Hz z 2 miejscami.
- **K7-V14 – układ:** puste miejsca po prawej w „Przeglądzie” (drugi rząd), w „Jakości” (obok histogramu i obok odchyłki częstotliwości) – panele rozciągnąć do pełnej szerokości siatki (24 kolumny).
- **K7-V15 – „Wiersze na minutę w bazie”:** spadek na końcu to minuta w toku. Pomijać bieżącą minutę.

## Sprawdzenie spójności (nie błąd wyglądu)

- „Epizody błędu licznika dziś” = 41, a `meter_error_count` z PLC = 18. Sprawdzić i opisać w raporcie, skąd różnica. Prawdopodobnie liczba epizodów od północy lokalnej obejmuje też dane sprzed zaniku zasilania (23.11, 23:00–23:16 UTC) i wcześniejsze epizody z 24.11, a licznik PLC wyzerował się przy powrocie zasilania o 06:52 UTC. Jeśli tak – dopisać to do opisu kafelka.

## Tryb wykonania (krok k7b)

Lista jest zamknięta, więc **bez osobnego planu**:
- Claude Code poprawia generator i panele;
- uruchamia testy (generator bez dryfu, harness zapytań na produkcji);
- wdraża (`git pull`, Grafana sama wczyta JSON po 30 s);
- pisze krótki `e2-k7b-report.md` z listą V1–V15 (zrobione / nie, z powodem) → stop.

Grzegorz robi potem nowe zrzuty pięciu dashboardów z zakresem **„Ostatnie 24 godziny”** (te same nazwy plików – nadpisują wersję sprzed poprawek; obecne zrzuty zostają w historii gita).
