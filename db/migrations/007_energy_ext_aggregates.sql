-- migrate: no-transaction
-- 007_energy_ext_aggregates: agregaty ciągłe energy_ext_1m i energy_ext_1h (E2-PLC2, krok 2): jakość energii (THD, kąt),
-- temperatura i czas pracy licznika, energia bierna (stany liczników n2/n4 oraz całka mocy biernej z podziałem na znak).
-- Osobne agregaty obok energy_1m i energy_1h (te zostają bez zmian: agregatu ciągłego nie da się rozszerzyć o kolumny bez
-- usunięcia i odtworzenia, a to groziłoby utratą wiaderek starszych niż 90 dni surowych danych).
-- Kolumny wyłącznie addytywne lub odtwarzalne (liczności, sumy, min, max, first, last), jak w 002: pochodne liczą widoki (008).
-- Wiaderka powstają dla każdej minuty z dowolną z tych metryk; kolumny metryk v2 są NULL (a liczności 0) tam, gdzie ich nie ma,
-- więc dane sprzed mapy v2 to „brak danych”, a nie zero. Całka mocy biernej obejmuje cały zapis `reactive_power` (od v1).
-- Odporność na przerwanie w połowie (jak K6-U3): każda instrukcja idempotentna, suma kontrolna zapisywana po całości.
-- Nie edytuj po zastosowaniu: zmianę wprowadza nowa migracja.

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_ext_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', time) AS bucket,
    device_id,
    count(value) FILTER (WHERE metric = 'thd_voltage')       AS thd_voltage_n,
    sum(value)   FILTER (WHERE metric = 'thd_voltage')       AS thd_voltage_sum,
    min(value)   FILTER (WHERE metric = 'thd_voltage')       AS thd_voltage_min,
    max(value)   FILTER (WHERE metric = 'thd_voltage')       AS thd_voltage_max,
    count(value) FILTER (WHERE metric = 'thd_current')       AS thd_current_n,
    sum(value)   FILTER (WHERE metric = 'thd_current')       AS thd_current_sum,
    min(value)   FILTER (WHERE metric = 'thd_current')       AS thd_current_min,
    max(value)   FILTER (WHERE metric = 'thd_current')       AS thd_current_max,
    count(value) FILTER (WHERE metric = 'phase_angle')       AS phase_angle_n,
    sum(value)   FILTER (WHERE metric = 'phase_angle')       AS phase_angle_sum,
    min(value)   FILTER (WHERE metric = 'phase_angle')       AS phase_angle_min,
    max(value)   FILTER (WHERE metric = 'phase_angle')       AS phase_angle_max,
    sum(cos(radians(value))) FILTER (WHERE metric = 'phase_angle') AS phase_cos_sum,
    count(value) FILTER (WHERE metric = 'meter_temperature') AS temperature_n,
    sum(value)   FILTER (WHERE metric = 'meter_temperature') AS temperature_sum,
    min(value)   FILTER (WHERE metric = 'meter_temperature') AS temperature_min,
    max(value)   FILTER (WHERE metric = 'meter_temperature') AS temperature_max,
    first(value, time) FILTER (WHERE metric = 'run_time')    AS run_time_first,
    last(value, time)  FILTER (WHERE metric = 'run_time')    AS run_time_last,
    min(value)         FILTER (WHERE metric = 'run_time')    AS run_time_min,
    max(value)         FILTER (WHERE metric = 'run_time')    AS run_time_max,
    first(value, time) FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_first,
    last(value, time)  FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_last,
    min(value)         FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_min,
    max(value)         FILTER (WHERE metric = 'reactive_pos_varh') AS counter_pos_max,
    first(value, time) FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_first,
    last(value, time)  FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_last,
    min(value)         FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_min,
    max(value)         FILTER (WHERE metric = 'reactive_neg_varh') AS counter_neg_max,
    count(value) FILTER (WHERE metric = 'reactive_power')    AS reactive_power_n,
    sum(GREATEST(value, 0)) FILTER (WHERE metric = 'reactive_power') AS reactive_pos_sum,
    sum(LEAST(value, 0))    FILTER (WHERE metric = 'reactive_power') AS reactive_neg_sum
FROM measurements
WHERE metric IN ('thd_voltage', 'thd_current', 'phase_angle', 'meter_temperature', 'run_time',
                 'reactive_pos_varh', 'reactive_neg_varh', 'reactive_power')
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

CREATE MATERIALIZED VIEW IF NOT EXISTS energy_ext_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', bucket) AS bucket,
    device_id,
    sum(thd_voltage_n)::bigint     AS thd_voltage_n,
    sum(thd_voltage_sum)           AS thd_voltage_sum,
    min(thd_voltage_min)           AS thd_voltage_min,
    max(thd_voltage_max)           AS thd_voltage_max,
    sum(thd_current_n)::bigint     AS thd_current_n,
    sum(thd_current_sum)           AS thd_current_sum,
    min(thd_current_min)           AS thd_current_min,
    max(thd_current_max)           AS thd_current_max,
    sum(phase_angle_n)::bigint     AS phase_angle_n,
    sum(phase_angle_sum)           AS phase_angle_sum,
    min(phase_angle_min)           AS phase_angle_min,
    max(phase_angle_max)           AS phase_angle_max,
    sum(phase_cos_sum)             AS phase_cos_sum,
    sum(temperature_n)::bigint     AS temperature_n,
    sum(temperature_sum)           AS temperature_sum,
    min(temperature_min)           AS temperature_min,
    max(temperature_max)           AS temperature_max,
    -- first/last z FILTER po kolumnie nie-NULL: first() bierze wartość najwcześniejszego wiersza także wtedy, gdy jest NULL,
    -- a minuty bez danej metryki (np. sprzed mapy v2) mają NULL; bez FILTER godzina graniczna dostawałaby NULL.
    first(run_time_first, bucket) FILTER (WHERE run_time_first IS NOT NULL) AS run_time_first,
    last(run_time_last, bucket)   FILTER (WHERE run_time_last IS NOT NULL)  AS run_time_last,
    min(run_time_min)              AS run_time_min,
    max(run_time_max)              AS run_time_max,
    first(counter_pos_first, bucket) FILTER (WHERE counter_pos_first IS NOT NULL) AS counter_pos_first,
    last(counter_pos_last, bucket)   FILTER (WHERE counter_pos_last IS NOT NULL)  AS counter_pos_last,
    min(counter_pos_min)           AS counter_pos_min,
    max(counter_pos_max)           AS counter_pos_max,
    first(counter_neg_first, bucket) FILTER (WHERE counter_neg_first IS NOT NULL) AS counter_neg_first,
    last(counter_neg_last, bucket)   FILTER (WHERE counter_neg_last IS NOT NULL)  AS counter_neg_last,
    min(counter_neg_min)           AS counter_neg_min,
    max(counter_neg_max)           AS counter_neg_max,
    sum(reactive_power_n)::bigint  AS reactive_power_n,
    sum(reactive_pos_sum)          AS reactive_pos_sum,
    sum(reactive_neg_sum)          AS reactive_neg_sum
FROM energy_ext_1m
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

ALTER MATERIALIZED VIEW energy_ext_1m SET (timescaledb.materialized_only = false);

-- migrate: next

ALTER MATERIALIZED VIEW energy_ext_1h SET (timescaledb.materialized_only = false);

-- migrate: next

SELECT add_continuous_aggregate_policy('energy_ext_1m',
    start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => true);

-- migrate: next

SELECT add_continuous_aggregate_policy('energy_ext_1h',
    start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => true);

-- migrate: next

ALTER MATERIALIZED VIEW energy_ext_1m SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

ALTER MATERIALIZED VIEW energy_ext_1h SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

SELECT add_compression_policy('energy_ext_1m', INTERVAL '14 days', if_not_exists => true);

-- migrate: next

SELECT add_compression_policy('energy_ext_1h', INTERVAL '60 days', if_not_exists => true);

-- migrate: next

SELECT add_retention_policy('energy_ext_1m', INTERVAL '1 year', if_not_exists => true);

-- migrate: next

-- Pierwsze zmaterializowanie istniejących danych (m.in. całka mocy biernej od początku zapisu).
CALL refresh_continuous_aggregate('energy_ext_1m', NULL, date_trunc('minute', now()));

-- migrate: next

CALL refresh_continuous_aggregate('energy_ext_1h', NULL, date_trunc('hour', now()));
