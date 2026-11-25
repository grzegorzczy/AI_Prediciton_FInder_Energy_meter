# E2-k8 – review planu (architekt)

Data: 2026-11-25. Plan: `e2-k8-plan.md` (`8078c21`).

**Werdykt: OK Z UWAGAMI.** Wykonuj część A po „ok” Grzegorza.

## Korekta mojego review k4

Restart Grafany 10:38:14 UTC to **OOM-kill przy limicie 384 MiB**, nie „czysty stop”. Mój wniosek z `ExitCode=0`
był błędny – dziennik jądra rozstrzyga. Dziękuję za sprawdzenie. To samo 24.11 23:05 i 23:06 lokalnie.

## Decyzje (odpowiedzi na sekcję 11)

1. **Podział A/B: TAK.**
   - **Część A (dziś):** pełne testy → naprawa logów → wdrożenie zmian Compose (Grafana, logging) → test restartu
     (Grzegorz) → checklista `etap-2.md` (szkic) → raport `e2-k8a-report.md`.
   - **Część B (26.11, po kompresji chunków 24.11 i 25.11):** kompresja i rozmiar, RAM po dobie od wdrożenia z części A,
     krok n4, uzupełnienie `etap-2.md`, raport `e2-k8b-report.md`.
2. **Grafana – podnieś limit od razu, bez odtwarzania OOM na produkcji:** `mem_limit` 512 MiB, `GOMEMLIMIT=400MiB`.
   Budżet: suma 2432 MiB z 16 GB – OK. Nie robimy celowego testu „5 dashboardów, rok, 5 s” na produkcji
   (obciąża bazę i drugi raz zabija Grafanę). Zamiast tego:
   - **sprawdź, czy OOM 10:38:14 UTC zbiegł się z harnessem paneli na produkcji** (testy 11:37 lokalnie, 276 zapytań
     przez API Grafany). Jeśli tak – harness ma ograniczyć współbieżność (np. maks. 2–4 zapytania naraz) i nie uruchamiać
     zakresów rocznych na produkcji; zakresy roczne tylko na `aip-test`;
   - to samo dla 24.11 23:05–23:06 (k7: testy wizualne / harness?);
   - w części B: `memory.peak` i `memory.events` (`oom_kill`) Grafany po dobie. Kryterium: 0 OOM, szczyt ≤ 80 % limitu.
3. **Okno `ipc_reboot` (migracja 011): TAK.** Okno naprawy logów tylko wtedy, gdy powstanie luka (patrz pkt 4).
4. **Logi:**
   - naprawa **bez zatrzymywania kontenerów**: kopia `cp -a` + skrócenie pliku (`: > plik`) przy działającym kontenerze
     (sterownik `json-file` pisze w trybie dopisywania, skrócenie jest bezpieczne). Brak luki w danych.
     Jeśli po skróceniu `docker logs` nadal zawodzi – dopiero wtedy wariant ze `stop`/`start` z planu;
   - **prewencja: TAK**, `logging` dla wszystkich usług `aip-*` w `docker-compose.yml`: sterownik `local`,
     `max-size: 10m`, `max-file: 5` (rotacja, ograniczony dysk). Wdrożenie przez R-1 (odtworzenie kontenerów –
     krótka luka, wpis do raportu). Bez zmian w `daemon.json` i bez restartu demona.
5. **`etap-2.md` – pozycje 1–14: TAK, z poprawkami:**
   - pkt 5: usuń „koszt” – taryf i kosztów nie ma w etapie 2 (etap 4);
   - pkt 6 (stany błędów RS485 / PLC offline): **nie powtarzamy testów fizycznych** (decyzja Grzegorza 24.11).
     Odwołanie do wyników k5 (zrzuty i liczby) + opcjonalna pozycja „jeśli chcesz powtórzyć”;
   - pkt 13: dopisz E2-PLC1 (błędy CRC seriami, odłożone), drugi licznik wymaga nowej mapy, `energy_1m_calc` i
     `reactive_1h_calc` wolne (etap 4);
   - pkt 12: zamiast `grep` po kodach funkcji – wskazanie testu `test_no_write` i jego wyniku (grep może dać fałszywe
     trafienia).

## Uwagi dodatkowe

- **Restart komputera restartuje też smartWARE.** Grzegorz wybiera porę; w raporcie: stan smartWARE przed i po
  (tylko odczyt), czas jego powrotu.
- **Test pełny i tmpfs:** OOM Postgresa w `aip-test` 24.11 17:57 – sprawdź, czy limit pamięci kontenera testowego
  i rozmiar tmpfs nie zagrażają RAM komputera (16 GB, smartWARE). Jeśli trzeba – obniż równoległość testów.
- Polecenie „przed” w sekcji 6 używa `psql -U postgres -d aip` – użyj konta i bazy z `docs/ops` (bez czytania `.env`),
  albo zrób ten odczyt sam.
- Sekcja 3: nazwa metryki n4 to `reactive_neg_varh` (mapa v2, potwierdzone).

## Dalej

Po „ok” Grzegorza: część A. Grzegorz dostaje od Claude Code gotowe polecenia (logi z `sudo`, `sudo reboot`)
i wykonuje je w wybranej porze.
