# E3-k7b – review raportu pilotażu (architekt)

Data: 2026-11-28. Raport: `e3-k7b-pilot.md` (`96e51b0`). Review krótkie.

**Werdykt: OK – nocne wgrywanie dziś, po zbudowaniu i teście strażnika K7-U1.**

Potwierdzone: restart IPC – produkcja 17 s po starcie, luka real 42 s; R-1 `c299eaa` → `f767048`, migracje 012–013, 2 real + 5 sim, T0 = 2026-11-28T12:42:00Z, 49 wierszy/s; pilotaż 2 073 600 wiadomości w 1 350 s (ok. 1 536/s, z fsync – szybciej niż `aip-test`), real 20/s i sim 29/s w 59/59 próbkach, **0 odrzuconych sim na żywo (K5R-D2)**, `--fill-gaps` 4 → 0 minut; ok. 400 MB/dobę liczników; monitor sieci bez strat.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K7B-D1 | Termin nocnego wgrywania | **Dziś w nocy**, start ok. 22:00 czasu lokalnego (prognoza ok. 5,5 h), pod warunkiem: strażnik K7-U1 zbudowany i przetestowany na `aip-test` (wymuszone przekroczenie każdego progu → stop), kompresja wstrzymana tuż przed startem, zgoda Grzegorza na start. |
| K7B-D2 | TimescaleDB przy limicie 1 536 MiB | **Akceptuję** – to pamięć podręczna plików (1 456 MiB), procesy 26 MiB, 0 OOM; jądro odzyskuje ją w razie potrzeby. Strażnik i raport patrzą na pamięć anonimową i OOM, nie na sumę. Bez zmiany limitu w etapie 3. |
| K7B-D3 | Grafana 141 → 350 MiB (64 %) | **Obserwujemy.** Wzrost przy oglądaniu dashboardów (logowanie Grzegorza 14:0x). W raporcie k7 szczyt po wgraniu, przy otwartej „Flocie” 14 dni i „Pompie” 90 dni; powyżej 80 % – decyzja o limicie w k8. |

## Uwagi na noc

- Strażnik: progi K7-U1 (real < 18/s przez > 60 s, `aip-ingest` > 80 % limitu, wolne miejsce < 3 × pozostała prognoza, kolejka brokera > 20 000); po stopie – **wznowienie kompresji** (polityka) i wpis w logu z przyczyną.
- Kompresja: wstrzymać po zadaniu 18:53 UTC, wznowić po wgraniu i odświeżeniu agregatów; w raporcie rozmiar bazy i chunki przed/po.
- Po wgraniu: pompa, odświeżenie agregatów w kolejności hierarchii, `--fill-gaps` (0), dopiero potem zrzuty końcowe.
- Okna `data_windows` (restart 42 s, deploy 16 s, pilotaż, noc) jedną migracją w raporcie k7 – OK.
