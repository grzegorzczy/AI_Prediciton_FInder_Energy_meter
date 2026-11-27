# E3-k5 – plan kroku (krótki): wgrywanie historii symulatora

Data: 2026-11-27. Podstawa: K0-D1 (liczniki 1 s × 14 dni, pompa 1 min × 84 dni), K0-D2, K4-U1, K4R-D2, U-4 (okno), K2R-U2 (pompa przez `devices`). Review k4 zacommitowane w `72b3c9e`. Produkcja bez zmian do k7.

## Narzędzie `python -m simulator.backfill`

Ten sam obraz, config i konto MQTT co usługa; uruchamiane jednorazowo: `docker compose run --rm simulator python -m simulator.backfill …`.
- **Zakres:** liczniki od `meter_anchor` co 1 s, pompa od `bearing_installed_at` co `history.pump_step_s` (60 s); koniec = podany `--to` (we wdrożeniu: start trybu na żywo). Pompa przez `samples_at(t, devices={pompa})` (liczniki istnieją dopiero od kotwicy).
- **Publikacja QoS 1 z ograniczeniem w locie** (K4R-D2): `max_inflight_messages` = 100 (parametr `--inflight`), czekanie na PUBACK przy pełnym oknie → naturalne dławienie tempem ingestu, kolejka brokera nie rośnie. Opcjonalny sufit `--rate` (wiadomości/s). Kolejność chronologiczna, postęp w logu co minutę (czas modelu, wiadomości/s, prognoza końca), przerwanie i wznowienie przez `--from` (idempotentne: `ON CONFLICT DO NOTHING`).
- **Tryb „uzupełnij luki w zakresie” `--fill-gaps`:** zapytanie **tylko do odczytu** (konto `app_reader`, z limitem czasu jak czat) o liczności w agregatach (`energy_1m`: `*_n` = 60 na minutę dla 6 metryk; `pump_1m`: `*_n` = 1 na minutę w historii, 60 na żywo) → lista niepełnych minut na urządzenie → publikacja tylko tych minut. Wynik: liczba brakujących minut przed i po (cel 0). **Do decyzji:** dostęp do bazy tylko do odczytu w trybie historii (nowa zależność symulatora; tryb na żywo bez bazy). Alternatywa bez bazy: ponowne wysłanie całego zakresu (29 mln wiadomości – godziny).

## Wielkości i tempo

Liczniki: 14 × 86 400 × 24 = **29,0 mln** wiadomości; pompa: 84 × 1 440 × 5 = **0,6 mln**. Przy 800 / 1 500 wiadomości/s: ok. 10 / 5,5 h → pełne wgranie w nocy (k7).
**Pilotaż 1 doby z pomiarem tempa:** w k5 na `aip-test` (2,07 mln wiadomości liczników + doba pompy; tempo, CPU/RAM ingestu, bazy, brokera, symulatora); na produkcji w k7 (1 doba przed pełnym wgraniem, z kontrolą 20 wierszy/s danych prawdziwych i liczby odrzuconych danych sim na żywo, `odrzucone_sim`). Uwaga: baza testowa jest w tmpfs, więc tempo z `aip-test` to górna granica.

## Po wgraniu

1. **Ręczne odświeżenie agregatów** dla zakresu historii (starszego niż okna polityk): `energy_1m`, `energy_ext_1m` → `energy_1h`, `energy_ext_1h` → `pump_1m` (`CALL refresh_continuous_aggregate(..., od, do)` w kolejności hierarchii); skrypt w `docs/ops`, test na bazie testowej.
2. **`--fill-gaps`** dla całego okna wgrywania → raport: brakujące minuty 0, odrzucone dane sim na żywo w czasie wgrywania (log ingestu).
3. **Okno `sim_backfill`** (migracja wg szablonu z k4, `exclude_from_analytics = FALSE`) z granicami z logu narzędzia – w k7.

## Testy

Jednostkowe: zakresy i kroki na urządzenie, chronologia, wznowienie od `--from`, QoS 1 i okno w locie (atrapa klienta), sufit tempa, wyliczenie niepełnych minut. Integracyjne (`aip-test`): 1 h liczników + 1 doba pompy → dokładne liczby wierszy; drugi przebieg → 0 nowych; usunięte wiersze → `--fill-gaps` wysyła tylko brakujące minuty; odświeżenie agregatów i `pump_1m` (krzywa rosnąca); równolegle tryb na żywo – dane real niezmienione. Pilotaż 1 doby w `run-perf.sh` (pomiar, nie w zwykłym zestawie). Pełny zestaw na końcu kroku, potem `reviewer` (nowy dostęp do bazy).

## Pliki

Nowe: `services/simulator/src/simulator/backfill.py`, `tests/simulator/test_sim_backfill*.py`. Zmieniane: `docker-compose.yml` (zmienne `DB_*` konta `app_reader` dla trybu historii, jeśli decyzja „tak”), `docs/ops` (procedura k7: pilotaż, pełne wgranie, odświeżenie, `--fill-gaps`, okno), `docs/data-model.md` (krótko).

## Do decyzji

1. Tryb `--fill-gaps` z odczytem bazy kontem `app_reader` (rekomendacja) czy bez bazy.
2. `--inflight 100` i brak sufitu tempa domyślnie (dławi ingest).

Plan e3-k5 gotowy do przeglądu.
