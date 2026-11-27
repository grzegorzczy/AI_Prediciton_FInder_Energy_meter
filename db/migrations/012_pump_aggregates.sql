-- migrate: no-transaction
-- 012_pump_aggregates: agregat ciągły pump_1m (E3-k4, K0-D4) dla pomp: drgania RMS, temperatura łożyska, prąd silnika,
-- przepływ i obroty (liczność, suma, min, max) oraz znacznik pracy run_n = liczba próbek obrotów > 0 w minucie (K2-U4).
-- Minuta pracy (widok pump_1m_calc, K4-D2): speed_n > 0 AND run_n = speed_n – minuty postoju i częściowe (start i koniec
-- zmiany) nie są minutami pracy; trend drgań (etap 5) liczy tylko minuty pracy, nie tło z postoju.
-- Wiaderka powstają tylko dla minut z którąkolwiek z metryk pompy (urządzenia bez tych metryk nie tworzą wierszy).
-- Kolumny wyłącznie addytywne lub odtwarzalne, jak w 002 i 007 (pochodne liczy widok). Zestaw ustalony na stałe (K4-U5):
-- dodatki = osobny agregat (agregatu ciągłego nie da się rozszerzyć bez odtworzenia).
-- Polityki jak energy_1m, ale retencja 1 rok, żeby krzywa z 84 dni historii (k5) przetrwała skasowanie surowych danych.
-- Odporność na przerwanie w połowie (jak K6-U3): każda instrukcja idempotentna, suma kontrolna zapisywana po całości.
-- Nie edytuj po zastosowaniu: zmianę wprowadza nowa migracja.

CREATE MATERIALIZED VIEW IF NOT EXISTS pump_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', time) AS bucket,
    device_id,
    count(value) FILTER (WHERE metric = 'vibration_rms')       AS vibration_n,
    sum(value)   FILTER (WHERE metric = 'vibration_rms')       AS vibration_sum,
    min(value)   FILTER (WHERE metric = 'vibration_rms')       AS vibration_min,
    max(value)   FILTER (WHERE metric = 'vibration_rms')       AS vibration_max,
    count(value) FILTER (WHERE metric = 'bearing_temperature') AS bearing_temperature_n,
    sum(value)   FILTER (WHERE metric = 'bearing_temperature') AS bearing_temperature_sum,
    min(value)   FILTER (WHERE metric = 'bearing_temperature') AS bearing_temperature_min,
    max(value)   FILTER (WHERE metric = 'bearing_temperature') AS bearing_temperature_max,
    count(value) FILTER (WHERE metric = 'motor_current')       AS motor_current_n,
    sum(value)   FILTER (WHERE metric = 'motor_current')       AS motor_current_sum,
    min(value)   FILTER (WHERE metric = 'motor_current')       AS motor_current_min,
    max(value)   FILTER (WHERE metric = 'motor_current')       AS motor_current_max,
    count(value) FILTER (WHERE metric = 'flow')                AS flow_n,
    sum(value)   FILTER (WHERE metric = 'flow')                AS flow_sum,
    min(value)   FILTER (WHERE metric = 'flow')                AS flow_min,
    max(value)   FILTER (WHERE metric = 'flow')                AS flow_max,
    count(value) FILTER (WHERE metric = 'speed')               AS speed_n,
    sum(value)   FILTER (WHERE metric = 'speed')               AS speed_sum,
    min(value)   FILTER (WHERE metric = 'speed')               AS speed_min,
    max(value)   FILTER (WHERE metric = 'speed')               AS speed_max,
    count(value) FILTER (WHERE metric = 'speed' AND value > 0) AS run_n
FROM measurements
WHERE metric IN ('vibration_rms', 'bearing_temperature', 'motor_current', 'flow', 'speed')
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

ALTER MATERIALIZED VIEW pump_1m SET (timescaledb.materialized_only = false);

-- migrate: next

SELECT add_continuous_aggregate_policy('pump_1m',
    start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute', if_not_exists => true);

-- migrate: next

ALTER MATERIALIZED VIEW pump_1m SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

SELECT add_compression_policy('pump_1m', INTERVAL '14 days', if_not_exists => true);

-- migrate: next

SELECT add_retention_policy('pump_1m', INTERVAL '1 year', if_not_exists => true);

-- migrate: next

CREATE OR REPLACE VIEW pump_1m_calc AS
SELECT
    bucket,
    device_id,
    vibration_sum / nullif(vibration_n, 0)                         AS vibration_avg,
    vibration_min,
    vibration_max,
    bearing_temperature_sum / nullif(bearing_temperature_n, 0)     AS bearing_temperature_avg,
    bearing_temperature_min,
    bearing_temperature_max,
    motor_current_sum / nullif(motor_current_n, 0)                 AS motor_current_avg,
    flow_sum / nullif(flow_n, 0)                                   AS flow_avg,
    speed_sum / nullif(speed_n, 0)                                 AS speed_avg,
    speed_n,
    run_n,
    run_n::float8 / nullif(speed_n, 0)                             AS run_share,
    (speed_n > 0 AND run_n = speed_n)                              AS running
FROM pump_1m;

-- migrate: next

GRANT SELECT ON pump_1m, pump_1m_calc TO app_reader;
