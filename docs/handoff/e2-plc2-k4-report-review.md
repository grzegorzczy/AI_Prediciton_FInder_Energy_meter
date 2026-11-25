# E2-PLC2 krok 4 – review raportu (architekt)

Data: 2026-11-25. Raport: `e2-plc2-k4-report.md` (komputer na `b1dda8b`).

**Werdykt: OK – E2-PLC2 zamknięty.** Mapa v2 działa na prawdziwym PLC; przełączenie v1 → v2 bez restartu collectora
(8 s `link_status` 1, log `1 -> 2`); 20,000 wiersza/s w 1 200 z 1 200 s; wartości zgodne z PLC-1;
spójność PF = cos(kąt)/√(1+THD_I²): 0,3704 wobec 0,3699; `energy_ext_1m` = przeliczenie z surowych.
Znak energii biernej potwierdzony (n4 45 → 48 od 23.11 przy n2 = 0).

## Uwagi

- **009 – różnica sum kontrolnych na produkcji:** akceptuję. Rozstrzyga niezależne przeliczenie `energy_1h`
  z `energy_1m` (31/31 godzin, różnice ~1e-10) i niezmienione doby (2,013 Wh, 112,829 Wh). Wniosek na przyszłość:
  przed migracją zmieniającą agregat zapisz **wiersze** (np. `\copy` do pliku w `/tmp`), nie tylko sumy.
- **Restart Grafany 10:38:15 UTC (exit 0):** czyste zatrzymanie, nie awaria. Do sprawdzenia w k8: `docker events`
  / log Compose z tego czasu, czy to nie było odtworzenie kontenera przez nasze `up -d`. Jeśli powtórzy się bez naszej
  akcji – osobne zgłoszenie.
- **Pełny zestaw testów po poprawce niestabilnego testu** – uruchomić na początku k8.
- **Okno PLC-2:** 11:43:01 lokalnie zamiast mojego „11:41–11:42” – granice z bazy są właściwe.
- Otwarte: pierwszy krok n4 4 800 → 4 900 varh, pomiar kompresji (po 26.11 00:00) – do k8.

## Dalej

**k8 (zamknięcie etapu 2), nie etap 3.** Etap 3 dopiero po akceptacji `etap-2.md` przez Grzegorza.
