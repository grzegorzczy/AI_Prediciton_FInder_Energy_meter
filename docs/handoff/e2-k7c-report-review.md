# E2-k7c – review raportu (architekt)

Data: 2026-11-25. Raport: `e2-k7c-report.md` (commity `ebfd912`, `0e585b5`, komputer na `a5718ce`).

**Werdykt: OK** (raport). Ostateczna ocena wyglądu po zrzutach Grzegorza 05, 06, 06b, 06c, 07.

## Ocena

- W-1…W-9 i A-1 wykonane zgodnie z `e2-k7b-visual-review.md`; 420/420 testów, 208 zapytań paneli bez błędu,
  0 błędów w logu Grafany, 170/384 MiB.
- Wyjaśnienie „16” (ucięta etykieta) i brak wiersza zamykającego epizod przyjmuję. Poprawka jest
  właściwa: oś stanu wraca do „Brak błędu” po każdym epizodzie.
- A-1: granice z bazy (14:25:03,390–14:25:20,392 UTC, 18 wierszy). Rodzaj okna przez wzorzec, bez listy – OK.
- W-9: hipoteza o przycinaniu linii na brzegu wykresu jest rozsądna. Rozstrzygnie zrzut 05.

## Uwagi

- **R-1 (proces):** `docker compose up -d --build` przy nowej migracji to już ustalenie D4
  (dokument projektu 12). Pierwsza próba bez `--build` nic nie zepsuła, ale zasada ma trafić do
  `docs/ops` jako krok wdrożenia (lista: `git pull --ff-only` → `up -d --build` → sprawdzenie
  `schema_migrations`). Do zrobienia przy najbliższym kroku, bez osobnego commita.
- **R-2 (E2-PLC1, tylko zapis faktu):** cztery serie: 23.11 23:38–00:16, 24.11 12:01–13:08, 17:23–18:07, 25.11 00:35–01:00
  (czas lokalny). Odstęp w serii 64 lub 128 s. Rozbieżność 14 vs 15 epizodów w serii 4 wynika z ręcznego
  liczenia z wykresu (skok 18 → 32 = 14). Obowiązuje liczba z zapytania: 14.
  Do sprawdzenia przy diagnozie: czy początki serii pokrywają się z pracą Grzegorza w CODESYS
  (online/logowanie, download) lub z innymi zdarzeniami po jego stronie (np. włączane urządzenia w pobliżu
  przewodu RS485). Seria 1 zaczęła się przy pierwszym starcie collectora i testach k5. To pytanie, nie wniosek.

## Dalej

Zrzuty 05, 06, 06b, 06c, 07 → review wizualny v3 → decyzja Grzegorza: E2-PLC2 albo k8.
