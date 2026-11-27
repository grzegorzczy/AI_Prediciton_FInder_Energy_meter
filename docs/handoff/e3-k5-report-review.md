# E3-k5 – review raportu (architekt)

Data: 2026-11-27. Raport: `e3-k5-report.md`. Review krótkie (dokument 04).

**Werdykt: OK.** Krok k5 zamknięty. Odstępstwo w sterowaniu przepływem jest trafne: PUBACK QoS 1 wysyła broker, nie ingest, więc samo okno w locie nie chroniło kolejki wspólnej z danymi real. Porcje 7 200 wiadomości z czekaniem na zapis ostatniej minuty w bazie, z zaległością najwyżej 3 888 wobec kolejki 80 000, rozwiązują to poprawnie.

## Decyzje

| Id | Sprawa | Decyzja |
| --- | --- | --- |
| K5R-D1 | `simulator-tools` podnosi sumę limitów do 2 688 MiB na czas wgrywania | **Jednorazowa zgoda, limit 128 MiB zostaje** (zmierzone ok. 65 MiB; obniżenie do 96 MiB zmniejszyłoby zapas bez zysku). Usługa działa tylko w profilu `tools` przez kilka godzin w nocy; komputer ma 16 GB. W teście budżetu wyjątek jawnie tylko dla profilu `tools`; stałe usługi nadal ≤ 2 560 MiB. Przegląd limitów przed Ollamą (etap 6) bez zmian. |
| K5R-D2 | Odrzucone dane sim na żywo w czasie wgrywania | **Pomiar w pilotażu produkcyjnym k7**, potem `--fill-gaps` dla okna wgrywania, cel 0 brakujących minut. |
| K5R-D3 | Nakładanie porcji (1,5–2× szybciej) | **Nie teraz.** 6 h w nocy wystarcza; prostsza ścieżka jest bezpieczniejsza dla danych real. |

## Uwagi do checklisty k7

- **Kompresja wstrzymana na czas wgrywania – obowiązkowe wznowienie** i sprawdzenie, że zadanie kompresji przeszło: rozmiar bazy przed i po, liczba skompresowanych chunków. Wstrzymanie dotyczy też danych real, więc nie dłużej niż jedna noc.
- Wolne miejsce ≥ 17 GB przed pełnym wgraniem (3 × 5,5 GiB).
- Tempo produkcyjne z pilotażu 1 doby (fsync włączony); jeśli pełne wgranie przekracza ok. 10 h, dzielimy je na dwie noce przez wznowienie.
- Kontrola 20 wierszy/s danych real w czasie pilotażu i pełnego wgrania.

## Dalej

Plan k6 (Grafana: dashboard „Flota” – 5 liczników, źródło real/sim, znacznik SYMULACJA; „Pompa P-101” na `pump_1m_calc`, trend tylko z minut pracy). Testy paneli tylko na `aip-test` z danymi z narzędzia historii. W k6 poproszę Grzegorza o zrzuty.
