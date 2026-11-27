# E3-k5 – raport (krótki): wgrywanie historii symulatora

Data: 2026-11-27. Commity: `a3f1a95` … `d76a3cb` (review planu w `1ff9fd0`). Produkcja bez zmian (c299eaa do k7).

## Wyniki

- **Narzędzie** `python -m simulator.backfill` w jednorazowej usłudze `simulator-tools` (profil `tools`, K5-D1): konto MQTT
  symulatora, odczyt bazy kontem `app_reader` (`statement_timeout` 10 s), wspólna pamięć sum dobowych (K5-U4). Usługa na żywo
  bez dostępu do bazy (test). QoS 1, okno w locie 100 ustawione w paho (`max_inflight_messages_set`), bez sufitu tempa (K5-D2).
- **Testy:** jednostkowe (`test_sim_backfill.py`, 10), integracyjne w `aip-test` (`test_sim_backfill_e2e.py`): 10 min
  liczników + pompy → dokładnie 14 450 wierszy; drugi przebieg → 0 wiadomości (50 pełnych minut urządzeń pominiętych); usunięte
  10 s jednej metryki licznika i 1 wiersz pompy → `--fill-gaps`: brakujących minut 2 → 0, wysłane tylko 365 wiadomości
  (K5-U1); ręczne odświeżenie agregatów w kolejności hierarchii → `energy_1m` 40 minut po 60 próbek, `pump_1m_calc` 10 minut
  (`vibration_n` = `speed_n` = 1). Konto narzędzia nie może pisać (test).
- **Pilotaż 1 doby** (`run-perf.sh -k backfill_pilot`; baza perf na dysku, ale `fsync=off` → górna granica; prawdziwy
  `python -m ingest.main` w osobnym procesie, ustawienia domyślne usługi):

  | Wielkość | Wynik |
  |---|---|
  | Wiadomości / czas / tempo | 2 080 800 / 1 553 s / **1 340 wiad./s** (288 porcji, czekanie na bazę 968 s) |
  | Wiersze w bazie, luki po przebiegu | 2 080 800 (= wysłane), 0 niepełnych minut |
  | Zaległość wysłane − w bazie (kolejka brokera + ingest, K5-U3), próbka co 10 s | maks. **3 888**, średnio 1 506 (limit kolejki 80 000) |
  | Ingest (osobny proces) | CPU 48 % rdzenia, szczyt RSS 45 MiB |
  | Narzędzie | CPU 40 % rdzenia, szczyt RSS procesu 65 MiB |
  | Kontenery (`docker stats` co 30 s, maks.) | baza 90 % CPU / 326 MiB; broker 10 % / 3 MiB; pytest (ingest + narzędzie) 99 % / 73 MiB |
  | Dysk (K5-U2) | przyrost bazy 400 MiB na dobę liczników; **199 B/wiersz** przed kompresją |
  | Kontrola luk jednej doby (29 zapytań) | 2,6 s |

  **Prognoza k7:** 14 dób liczników ok. 5,4 GiB + pompa 0,1 GiB przed kompresją → wolne miejsce **≥ 17 GB** (3×); czas
  ok. 6 h liczniki + kilka minut pompa przy 1 340/s (na produkcji z fsync wolniej – pilotaż k7 to zmierzy); kontrola luk
  14 dób ok. 40 s.

## Odstępstwa od planu

1. **Sterowanie przepływem end-to-end zamiast samego okna w locie.** PUBACK QoS 1 wysyła broker, nie ingest, więc okno
   ogranicza tylko wiadomości do brokera, a kolejka brokera dla ingestu (wspólna z danymi real, przepełnienie gubi
   najnowsze, także real) mogłaby rosnąć. Narzędzie wysyła **porcjami po 7 200 wiadomości** i przed kolejną czeka, aż ostatnia
   wysłana minuta jest w bazie kompletna (odczyt `app_reader`). Pilotaż: zaległość ≤ 3 888.
2. **Po przeglądzie `reviewer` jedna ścieżka dla wgrania, wznowienia i `--fill-gaps`:** każda doba jest najpierw sprawdzana
   w bazie (liczności minutowe każdej metryki, K5-U1), wysyłane są tylko niepełne minuty urządzeń. Usuwa to dwa błędy
   wykryte przez `reviewer`: `--fill-gaps` bez sterowania przepływem (duża luka = miliony wiadomości naraz) oraz brak
   czekania, gdy sprawdzany wiersz już był w bazie (wznowienie/powtórka). Wznowienie = to samo polecenie.
3. Liczność zapytania o luki z `measurements` (dobami), nie z agregatów – agregaty historii są nieodświeżone do kroku 7
   procedury.

Pozostałe poprawki po `reviewer`: porcja liczona w wiadomościach (pompa: doba na porcję zamiast 5 min), czekanie na CONNACK
i wyjątek przy braku PUBACK (zamiast cichych 60 s), losowy sufiks `client_id`, `--from`/`--to` w pełnych minutach,
`pump_step_s` = 60 wymagane, brak zapytań przed początkiem historii urządzenia, granice `--chunk-messages` i `--inflight`;
w procedurze k7 wstrzymanie kompresji `measurements` na czas wgrywania i poprawiona liczba wolnego miejsca.

## Do decyzji

1. **Budżet RAM (zasada 2):** stałe usługi mają już łącznie 2 560 MiB limitów; `simulator-tools` (128 MiB, zmierzone ok.
   65 MiB) podnosi sumę na czas wgrywania do 2 688 MiB. Proponuję zgodę na jednorazowe przekroczenie (test zapisuje to
   wprost) albo obniżenie limitu narzędzia do 96 MiB.
2. **Odrzucone dane sim na żywo w czasie wgrywania:** w pilotażu `aip-test` symulator na żywo nie działał, więc liczby nie
   ma – mierzy ją produkcyjny pilotaż k7 (`odrzucone_sim` w logu ingestu, procedura w `docs/ops/jumo-ipc-setup.md`).
3. Tempo: 62 % czasu narzędzie czeka na bazę (porcja → czekanie → porcja). Wystarcza (6 h w nocy); nakładanie porcji
   (czekanie na N−1 przy wysyłce N) dałoby ok. 1,5–2× – nie robię bez potrzeby.

## Testy

Pełny zestaw na `d76a3cb`: **735 passed, 6 skipped** (27 min; pominięte: pomiary perf i testy wymagające sprzętu). `reviewer`: 2 błędy, 4 ryzyka, 8 drobnych – poprawione jak wyżej; poza
zakresem zostaje pkt 4 (pilotaż w jednym kontenerze – rozwiązany osobnym procesem ingestu, pomiar per kontener w k7).

Raport e3-k5 gotowy do przeglądu.
