-- migrate: no-transaction
-- 002_energy_aggregates: agregaty ciągłe energy_1m i energy_1h (etap 2, k6).
-- Agregaty ciągłe nie mogą powstać w transakcji, więc plik działa bez niej (instrukcje rozdzielone znacznikiem next).
-- Odporność na przerwanie w połowie (K6-U3): każda instrukcja jest idempotentna (IF NOT EXISTS, if_not_exists => true),
-- a runner zapisuje sumę kontrolną dopiero po ostatniej instrukcji, więc ponowny `migrate` wykonuje plik od początku.
-- Agregaty zawierają wyłącznie wartości addytywne lub odtwarzalne (liczności, sumy, min, max, first, last):
-- wartości pochodne (średnie, całka, pokrycie, przyrost licznika) liczą widoki w 003_energy_views.sql.
-- Nie edytuj tego pliku po zastosowaniu: zmianę wprowadza nowa migracja (suma kontrolna).

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', time) AS bucket,
    device_id,
    count(value) FILTER (WHERE metric = 'active_power')   AS active_power_n,
    sum(value)   FILTER (WHERE metric = 'active_power')   AS active_power_sum,
    min(value)   FILTER (WHERE metric = 'active_power')   AS active_power_min,
    max(value)   FILTER (WHERE metric = 'active_power')   AS active_power_max,
    count(value) FILTER (WHERE metric = 'voltage')        AS voltage_n,
    sum(value)   FILTER (WHERE metric = 'voltage')        AS voltage_sum,
    min(value)   FILTER (WHERE metric = 'voltage')        AS voltage_min,
    max(value)   FILTER (WHERE metric = 'voltage')        AS voltage_max,
    count(value) FILTER (WHERE metric = 'current')        AS current_n,
    sum(value)   FILTER (WHERE metric = 'current')        AS current_sum,
    min(value)   FILTER (WHERE metric = 'current')        AS current_min,
    max(value)   FILTER (WHERE metric = 'current')        AS current_max,
    count(value) FILTER (WHERE metric = 'reactive_power') AS reactive_power_n,
    sum(value)   FILTER (WHERE metric = 'reactive_power') AS reactive_power_sum,
    count(value) FILTER (WHERE metric = 'apparent_power') AS apparent_power_n,
    sum(value)   FILTER (WHERE metric = 'apparent_power') AS apparent_power_sum,
    count(value) FILTER (WHERE metric = 'power_factor')   AS power_factor_n,
    sum(value)   FILTER (WHERE metric = 'power_factor')   AS power_factor_sum,
    count(value) FILTER (WHERE metric = 'frequency')      AS frequency_n,
    sum(value)   FILTER (WHERE metric = 'frequency')      AS frequency_sum,
    first(value, time) FILTER (WHERE metric = 'energy_import_wh') AS import_first,
    last(value, time)  FILTER (WHERE metric = 'energy_import_wh') AS import_last,
    min(value)         FILTER (WHERE metric = 'energy_import_wh') AS import_min,
    max(value)         FILTER (WHERE metric = 'energy_import_wh') AS import_max,
    first(value, time) FILTER (WHERE metric = 'energy_export_wh') AS export_first,
    last(value, time)  FILTER (WHERE metric = 'energy_export_wh') AS export_last,
    min(value)         FILTER (WHERE metric = 'energy_export_wh') AS export_min,
    max(value)         FILTER (WHERE metric = 'energy_export_wh') AS export_max,
    count(value) FILTER (WHERE metric = 'meter_status' AND value <> 0) AS meter_error_seconds,
    count(value) FILTER (WHERE metric = 'meter_status')   AS meter_status_n
FROM measurements
WHERE metric IN ('active_power', 'voltage', 'current', 'reactive_power', 'apparent_power', 'power_factor', 'frequency',
                 'energy_import_wh', 'energy_export_wh', 'meter_status')
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

-- Agregat hierarchiczny: składa się wyłącznie z kolumn addytywnych lub odtwarzalnych energy_1m.
CREATE MATERIALIZED VIEW IF NOT EXISTS energy_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', bucket) AS bucket,
    device_id,
    sum(active_power_n)::bigint   AS active_power_n,
    sum(active_power_sum)         AS active_power_sum,
    min(active_power_min)         AS active_power_min,
    max(active_power_max)         AS active_power_max,
    sum(voltage_n)::bigint        AS voltage_n,
    sum(voltage_sum)              AS voltage_sum,
    min(voltage_min)              AS voltage_min,
    max(voltage_max)              AS voltage_max,
    sum(current_n)::bigint        AS current_n,
    sum(current_sum)              AS current_sum,
    min(current_min)              AS current_min,
    max(current_max)              AS current_max,
    sum(reactive_power_n)::bigint AS reactive_power_n,
    sum(reactive_power_sum)       AS reactive_power_sum,
    sum(apparent_power_n)::bigint AS apparent_power_n,
    sum(apparent_power_sum)       AS apparent_power_sum,
    sum(power_factor_n)::bigint   AS power_factor_n,
    sum(power_factor_sum)         AS power_factor_sum,
    sum(frequency_n)::bigint      AS frequency_n,
    sum(frequency_sum)            AS frequency_sum,
    first(import_first, bucket)   AS import_first,
    last(import_last, bucket)     AS import_last,
    min(import_min)               AS import_min,
    max(import_max)               AS import_max,
    first(export_first, bucket)   AS export_first,
    last(export_last, bucket)     AS export_last,
    min(export_min)               AS export_min,
    max(export_max)               AS export_max,
    sum(meter_error_seconds)::bigint AS meter_error_seconds,
    sum(meter_status_n)::bigint   AS meter_status_n
FROM energy_1m
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

-- Tryb czasu rzeczywistego (K6-g): najnowsze, jeszcze niezmaterializowane wiaderko jest widoczne w zapytaniach.
ALTER MATERIALIZED VIEW energy_1m SET (timescaledb.materialized_only = false);

-- migrate: next

ALTER MATERIALIZED VIEW energy_1h SET (timescaledb.materialized_only = false);

-- migrate: next

-- Okna odświeżania są krótsze niż retencja surowych danych (90 dni), a kompresja następuje po oknie odświeżania.
SELECT add_continuous_aggregate_policy('energy_1m',
    start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => true);

-- migrate: next

SELECT add_continuous_aggregate_policy('energy_1h',
    start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => true);

-- migrate: next

ALTER MATERIALIZED VIEW energy_1m SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

ALTER MATERIALIZED VIEW energy_1h SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

SELECT add_compression_policy('energy_1m', INTERVAL '14 days', if_not_exists => true);

-- migrate: next

SELECT add_compression_policy('energy_1h', INTERVAL '60 days', if_not_exists => true);

-- migrate: next

-- Retencja: minutowe 1 rok; godzinowe bez limitu (decyzje z k0).
SELECT add_retention_policy('energy_1m', INTERVAL '1 year', if_not_exists => true);

-- migrate: next

-- Pierwsze zmaterializowanie istniejących danych. Bieżące wiaderko dopełnia tryb czasu rzeczywistego.
CALL refresh_continuous_aggregate('energy_1m', NULL, date_trunc('minute', now()));

-- migrate: next

CALL refresh_continuous_aggregate('energy_1h', NULL, date_trunc('hour', now()));
