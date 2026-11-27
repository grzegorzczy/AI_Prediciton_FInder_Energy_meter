# E3-k4 – review raportu (architekt)

Data: 2026-11-27. Raport: `e3-k4-report.md` (`b08ced9`). Review krótkie (dokument 04, „Oszczędzanie tokenów”).

**Werdykt: OK.** Krok k4 zamknięty.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K4R-D1 | Limit sim w kolejce MQTT ingestu i w paczce osobno (2 × 3 000) | **Tak.** Słuszne odstępstwo: przy wolnej bazie zaległość rosła w kolejce wejściowej (5 000) i jej zapełnienie zablokowałoby dane prawdziwe. 2 × 3 000 wierszy to ok. 2,6 MiB – bez znaczenia dla limitu 128 MiB. Dane real i sim z QoS 1 nigdy nieodrzucane. |
| K4R-D2 | QoS wgrywania historii (k5) | **QoS 1 z ograniczeniem w locie** (K4-U1). To, że wiersze historii zajmują limit paczki i w tym czasie ingest odrzuca dane sim na żywo (QoS 0), jest akceptowalne: dane prawdziwe nienaruszone, a luki sim są odtwarzalne. Wymaganie na k5: narzędzie historii ma tryb „uzupełnij luki w zakresie” (idempotentny) i po wgraniu uruchamiamy je dla okna `sim_backfill`; w raporcie k5 liczba odrzuconych wierszy sim na żywo w czasie wgrywania i wynik uzupełnienia (0 brakujących minut/sekund). |

## Uwagi

- K4-U2 rozstrzygnięte: TimescaleDB 2.32.1 odświeża zakres ze skompresowanym `pump_1m` i przyjmuje wiersze do skompresowanego chunku `measurements` – k5 bez obchodzenia kompresji.
- Po poprawce jednego testu (lista agregatów) przeszły tylko `tests/db` (118/118); zmiana dotyczyła wyłącznie pliku testu – akceptuję. Pełny zestaw na końcu k5 obejmie ją.
- Migracja 012 zmieniona w miejscu (`vibration_n` w widoku) – w porządku, bo nie była zastosowana na produkcji.

## Dalej

Plan k5 (wgrywanie historii: liczniki 1 s × 14 dni, pompa 1 min × 84 dni, QoS 1 z ograniczeniem w locie, tryb uzupełniania luk, pilotaż 1 doby, pomiar tempa, okno `sim_backfill`, ręczne odświeżenie agregatów) → review.
