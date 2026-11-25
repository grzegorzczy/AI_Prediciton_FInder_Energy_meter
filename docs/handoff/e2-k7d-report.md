# e2-k7d raport: K7C-V1, panele z własnym zakresem czasu
Status: DO PRZEGLĄDU

Wykonanie 25.11.2026 wg `e2-k7c-visual-review.md` (K7C-V1) i `e2-k7c-report-review.md` (R-1). Bez `sudo`, bez ruszania smartWARE, PLC i `.env`. Na komputer trafiało tylko to, co jest w `origin/main`.
Commity: `ded07c8` (poprawka generatora i testów), `a9d3575` (review k7c, zrzuty, kolejność wdrożenia w `docs/ops`).

## Przyczyna: to nie regresja generatora

Objawy z recenzji (brak „Last 14 days”, godziny z zakresu pulpitu w profilu) wystąpiły, bo **zrzut 06 jest zrobiony przy zakresie bezwzględnym pulpitu** („2026-11-24 18:48:51 to 2026-11-25 06:48:51”), a **Grafana stosuje nadpisanie zakresu panelu (`timeFrom`) tylko przy względnym zakresie pulpitu** (np. „Ostatnie 3 godziny”). Przy bezwzględnym je pomija i panel pokazuje zakres pulpitu.
Sprawdziłem, że `timeFrom` jest w wygenerowanym JSON i w tym, co Grafana serwuje przez API (obie wersje `timeFrom` = 14d/28d, `hideTimeOverride` = false): generator niczego nie zgubił. Zrzut v2 (k7b) był zrobiony przy zakresie względnym, stąd znaczniki „Last 14/28 days”.
Mój wniosek o zasadzie działania Grafany opieram na tym, że zrzut 06 ma zakres bezwzględny i że JSON jest poprawny; samego kodu Grafany nie czytałem ani nie odtwarzałem zachowania w przeglądarce.

## Poprawka

Własny zakres jest liczony **w SQL od „teraz”**, a nie nadpisaniem `timeFrom`. Zapytania tych paneli nie używają już makr `$__timeFilter`, `$__timeFrom`, `$__timeTo`, więc zakres pulpitu (względny czy bezwzględny) nic w nich nie zmienia; `timeFrom` usunąłem (zbędny i zawodny; znacznik „Last N days” w nagłówku panelu zniknął, zakres jest w tytule i opisie).

**Panele z własnym zakresem (cztery, wszystkie w „Energia i profil”):**

| Panel | Zakres | Jak |
| --- | --- | --- |
| Zużycie na dobę (ostatnie 14d) | 14 dób lokalnych (dziś i 13 wcześniejszych) | `day >= (now() AT TIME ZONE 'Europe/Warsaw')::date - 13`; **zmieniony typ na wykres słupkowy z osią kategorii** (doba jako etykieta), bo wykres czasowy ma oś czasu pulpitu i dane spoza niej by ucinał |
| Profil: godzina × dzień tygodnia (ostatnie 28d) | 28 dni | `bucket >= now() - interval '28 days'` |
| Moc maks. profilu | 28 dni | jak profil |
| Kontrola całki mocy a licznik wzorcowy (doby, ostatnie 14d) | 14 dób lokalnych | jak „Zużycie na dobę” |

Poprzednio panele z `timeFrom` w k7b to dokładnie te cztery (żadnych innych nie było). **Zmiana w „Zużyciu na dobę”:** pokrycie doby nie jest już osobną serią (żółte punkty na prawej osi), tylko **procentem w etykiecie słupka** („24.11 (67%)”, dla doby w toku „25.11 (w toku, 31%)” z pokryciem samej upłyniętej części doby, definicja jak w W-4). To jedyna zmiana wyglądu poza zakresem; ocenią ją zrzuty (wykres słupkowy z kategoriami już działa w histogramie napięcia).

## Testy i wdrożenie

- **Test zakresu w JSON (żądany):** `test_panels_with_their_own_range_do_not_depend_on_the_dashboard_range` sprawdza dla każdego z czterech paneli (lista `OWN_RANGE_PANELS` w generatorze): obecność znacznika zakresu w SQL, brak makr zakresu pulpitu, opis „niezależnie od zakresu pulpitu”, a dla „Zużycia na dobę” typ słupkowy.
- **Test wykonawczy (dodatkowy):** te same panele dają **identyczny wynik** przy trzech zakresach pulpitu (względny 3 h, bezwzględny 10 min, bezwzględny sprzed 30 dni) na danych syntetycznych.
- Testy Grafany na komputerze: **96 z 96** (przed zmianą 90). Pełny zestaw nie był uruchamiany w tym kroku (zmiany tylko w generatorze, JSON, testach Grafany i dokumentach; nie ruszałem bazy, collectora ani ingestu).
- Wdrożenie: `git pull --ff-only`, `docker compose up -d --build` (`done: 0 applied, 5 already applied`, `schema_migrations` = 5 wierszy, 5 plików migracji). Grafana wczytała JSON sama.
- Produkcja: **208 zapytań paneli, 0 błędów**, 0 wpisów `level=error` w logu Grafany. Cztery panele z własnym zakresem: dla zakresu względnego 3 h i bezwzględnego sprzed doby ten sam wynik (doby: 3 wiersze, profil: 24, kafelek: 1, kontrola: 3), na prawdziwych danych z 23–25.11.

## R-1: kolejność wdrożenia

Dopisana do `docs/ops/jumo-ipc-setup.md` (sekcja „Kolejność wdrożenia zmian”): `git pull --ff-only` → `docker compose up -d --build` → sprawdzenie `schema_migrations` (i logu `aip-migrate`); `--build` obowiązkowe przy nowej migracji (D4).

## Czego nie sprawdziłem

Wyglądu: nowego wykresu słupkowego „Zużycie na dobę” z pokryciem w etykiecie (czy etykiety „DD.MM (xx%)” mieszczą się przy 14 słupkach) i czy profil i kontrola pokazują pełne 28 i 14 dni przy zakresie bezwzględnym. To oceniają zrzuty 06, 06b, 06c (zalecam zrobić je także przy zakresie bezwzględnym, żeby sprawdzić tę poprawkę).

## Dla Grzegorza

Nowe zrzuty 06, 06b, 06c (nazwy bez zmian); jeśli ma być sprawdzona poprawka, jeden zrzut przy zakresie bezwzględnym pulpitu.
