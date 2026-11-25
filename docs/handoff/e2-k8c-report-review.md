# E2-k8c – review raportu (architekt)

Data: 2026-11-25. Raport: `e2-k8c-report.md` (`dc3178b`).

**Werdykt: OK (kod i wdrożenie); wygląd – po zrzutach Grzegorza.** K8-V1…V7 wykonane jednym R-1 bez odtwarzania
kontenerów (brak luki); 207 zapytań paneli, 0 błędów. Przyczyna V1 (brak wiersza powrotu po luce 0 → 0) zgodna
z hipotezą z review. V4: 36 epizodów tylko na mapie v1, pod v2 zero – zapisane w faktach E2-PLC1.

## Uwagi

- **Testy:** pierwszy pełny przebieg – awaria bazy testowej bez OOM w dzienniku i bez ustalonej przyczyny; po poprawce
  testu k4 nie było pełnego przebiegu. **Na start części B: pełny zestaw.** Jeśli awaria bazy testowej się powtórzy –
  zebrać `docker logs` kontenera testowego i `journalctl -k` z tego czasu, opisać w raporcie k8b (nie blokuje etapu,
  jeśli drugi przebieg jest czysty).
- Test k4 z porównaniem sum zmiennoprzecinkowych: 9 cyfr znaczących – OK.
- V3 i V7 (wysokość tabeli, szerokość kolumn profilu) – potwierdzenie zrzutami 04 i 06b.

## Dalej

Zrzuty 04, 04b, 04c, 06, 06b, 06c, 07, 07b (Grzegorz) → review wizualny → część B jutro po 13:00 UTC+1.
