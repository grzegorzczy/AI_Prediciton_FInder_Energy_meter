# Model danych (projekt wstępny)

**Status: propozycja do zatwierdzenia na początku etapu 2.** Nazwy tabel, kompresja
i retencja pochodzą z ustaleń projektu. Kolumny i typy to propozycja: mogą się
zmienić, gdy powstanie `docs/modbus-map.md` i `docs/decisions.md`.

## Zasady

- Jedna wąska tabela pomiarów: wiersz = jedna wartość jednej metryki w chwili.
  Nowa metryka nie wymaga zmiany schematu.
- Czas zawsze `TIMESTAMPTZ` w UTC; strefa Europe/Warsaw tylko w prezentacji.
- Źródło każdej wartości: `real` (PLC) albo `sim` (symulator).
- Urządzenia definiuje `config/devices.yaml`; tabela `devices` jest jego odbiciem
  synchronizowanym przy starcie, a nie miejscem ręcznej edycji.
- Dwie role w bazie: `app_writer` (ingest, analytics) i `app_reader`
  (Grafana, czat; tylko SELECT, `statement_timeout`).

## Zgodność z MQTT

Temat `zaklad/linia/urzadzenie/metryka` → `device_id` = `urzadzenie`,
`metric` = `metryka`; `zaklad` i `linia` są atrybutami urządzenia w `devices`.
Ładunek `{ts, value, unit, source}` → kolumny `time, value, unit, source`.

## Tabele

### `devices`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| device_id | TEXT PK | np. `meter-01`, `p-101` |
| name | TEXT | nazwa po polsku |
| site | TEXT | zakład |
| line | TEXT | linia |
| kind | TEXT | `energy_meter`, `pump`, … |
| source | TEXT | `real` / `sim` |
| enabled | BOOLEAN | |
| meta | JSONB | dodatkowe atrybuty z configu |

### `measurements` (hypertable)

| Kolumna | Typ | Opis |
| --- | --- | --- |
| time | TIMESTAMPTZ | znacznik czasu z ładunku |
| device_id | TEXT FK → devices | |
| metric | TEXT | np. `voltage`, `active_power`, `energy_import` |
| value | DOUBLE PRECISION | |
| unit | TEXT | `V`, `W`, `Wh`, `mm/s`, … |
| source | TEXT | `real` / `sim` |

- Klucz unikalny: `(device_id, metric, time)` – chroni przed duplikatami po ponowieniu.
- Hypertable po `time`, kawałki 1 dzień.
- Kompresja po 1 dniu, `segmentby = device_id, metric`.
- Retencja 90 dni (surowe dane). Agregaty trzymane dłużej – do decyzji w etapie 2.

### Agregaty ciągłe

| Widok | Okno | Zawartość |
| --- | --- | --- |
| energy_1m | 1 min | śr./min/maks. mocy, napięcia, prądu; przyrost energii |
| energy_1h | 1 h | jak wyżej, na godzinę; podstawa kosztów |
| pump_1m | 1 min | śr./maks. wibracji RMS, temperatury łożyska, prądu, przepływu, obrotów |

### `machine_states`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| device_id | TEXT | |
| state | TEXT | `off` / `idle` / `run` |
| start_time | TIMESTAMPTZ | |
| end_time | TIMESTAMPTZ NULL | NULL = stan trwa |
| threshold_w | DOUBLE PRECISION | próg użyty do klasyfikacji |

### `anomaly_scores`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| time | TIMESTAMPTZ | koniec okna 10-minutowego |
| device_id | TEXT | |
| model_version | TEXT | |
| score | DOUBLE PRECISION | wynik Isolation Forest |
| is_anomaly | BOOLEAN | |
| features | JSONB | cechy okna (do objaśnień) |

### `events`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | BIGSERIAL PK | |
| time | TIMESTAMPTZ | |
| device_id | TEXT | |
| kind | TEXT | `threshold`, `anomaly`, `trend`, `comm_loss`, … |
| severity | TEXT | `info` / `warning` / `alarm` |
| message | TEXT | po polsku |
| details | JSONB | np. szacowane dni do progu z przedziałem |
| acknowledged_at | TIMESTAMPTZ NULL | |

### `tariffs`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | SERIAL PK | |
| name | TEXT | |
| valid_from | DATE | |
| valid_to | DATE NULL | |
| schedule | JSONB | strefy godzinowe i ceny zł/kWh |

### `chat_log`

| Kolumna | Typ | Opis |
| --- | --- | --- |
| id | BIGSERIAL PK | |
| time | TIMESTAMPTZ | |
| question | TEXT | |
| provider | TEXT | `ollama` / nazwa dostawcy chmurowego |
| model | TEXT | |
| path | TEXT | `tool` / `sql` |
| tool_or_sql | TEXT | użyte narzędzie z parametrami albo SQL |
| answer | TEXT | |
| confidence | TEXT | `high` / `medium` |
| sent_to_cloud | BOOLEAN | wymagane przez zasadę twardą nr 5 |
| latency_ms | INTEGER | |

## Do ustalenia w etapie 2

- Czy energię zapisujemy jako stan licznika (Wh) i liczymy przyrosty w agregatach,
  czy collector liczy przyrosty – zależy od mapy rejestrów z etapu 1.
- Retencja agregatów (propozycja: `energy_1h` bez limitu, `energy_1m` 1 rok).
- Zmierzone zużycie dysku po dobie pracy.
