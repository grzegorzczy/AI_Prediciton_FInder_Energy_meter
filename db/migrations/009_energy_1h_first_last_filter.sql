-- migrate: no-transaction
-- 009_energy_1h_first_last_filter: odtworzenie agregatu godzinnego energy_1h z poprawką first()/last() (E2-PLC2, krok 4).
-- Wada z migracji 002: `first(import_first, bucket)` i `last(...)` w agregacie hierarchicznym biorą wartość najwcześniejszego
-- (najpóźniejszego) wiersza także wtedy, gdy jest NULL, więc godzina, w której pierwsza lub ostatnia minuta nie ma energii
-- (np. cała minuta błędu licznika), dostawała import_first/last (export_first/last) = NULL i przyrost godziny był NULL.
-- Poprawka: first/last z `FILTER (WHERE kolumna IS NOT NULL)` (tak jak w energy_ext_1h, migracja 007).
-- Agregatu ciągłego nie da się zmienić w miejscu, więc: usunięcie zależnych widoków i agregatu, utworzenie od nowa z energy_1m
-- (retencja energy_1m = 1 rok, więc nic się nie traci), polityki jak w 002, pełne odświeżenie, odtworzenie widoków z 003
-- (definicje identyczne, wygenerowane z 003) i uprawnienia dla app_reader.
-- Odporność na przerwanie w połowie (jak K6-U3): każda instrukcja idempotentna (DROP IF EXISTS, IF NOT EXISTS, if_not_exists),
-- a runner zapisuje sumę kontrolną po całości; ponowne uruchomienie zaczyna od usunięcia.
-- Nie edytuj po zastosowaniu: zmianę wprowadza nowa migracja.

DROP VIEW IF EXISTS energy_daily_check;

-- migrate: next

DROP VIEW IF EXISTS energy_1h_calc;

-- migrate: next

DROP MATERIALIZED VIEW IF EXISTS energy_1h;

-- migrate: next

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
    first(import_first, bucket) FILTER (WHERE import_first IS NOT NULL) AS import_first,
    last(import_last, bucket) FILTER (WHERE import_last IS NOT NULL) AS import_last,
    min(import_min)               AS import_min,
    max(import_max)               AS import_max,
    first(export_first, bucket) FILTER (WHERE export_first IS NOT NULL) AS export_first,
    last(export_last, bucket) FILTER (WHERE export_last IS NOT NULL) AS export_last,
    min(export_min)               AS export_min,
    max(export_max)               AS export_max,
    sum(meter_error_seconds)::bigint AS meter_error_seconds,
    sum(meter_status_n)::bigint   AS meter_status_n
FROM energy_1m
GROUP BY 1, 2
WITH NO DATA;

-- migrate: next

ALTER MATERIALIZED VIEW energy_1h SET (timescaledb.materialized_only = false);

-- migrate: next

SELECT add_continuous_aggregate_policy('energy_1h',
    start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '15 minutes', if_not_exists => true);

-- migrate: next

ALTER MATERIALIZED VIEW energy_1h SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'device_id');

-- migrate: next

SELECT add_compression_policy('energy_1h', INTERVAL '60 days', if_not_exists => true);

-- migrate: next

CALL refresh_continuous_aggregate('energy_1h', NULL, date_trunc('hour', now()));

-- migrate: next

CREATE OR REPLACE VIEW energy_1h_calc AS
WITH base AS (
    SELECT e.*,
           (d.meta ->> 'poll_interval_s')::float8      AS poll_interval_s,
           (d.meta ->> 'energy_resolution_wh')::float8 AS resolution_wh
    FROM energy_1h e
    JOIN devices d USING (device_id)
), imp AS (
    SELECT device_id, bucket,
           lag(import_last) OVER w AS prev_import_last,
           lag(bucket)      OVER w AS prev_import_bucket
    FROM energy_1h
    WHERE import_last IS NOT NULL
    WINDOW w AS (PARTITION BY device_id ORDER BY bucket)
), expo AS (
    SELECT device_id, bucket,
           lag(export_last) OVER w AS prev_export_last
    FROM energy_1h
    WHERE export_last IS NOT NULL
    WINDOW w AS (PARTITION BY device_id ORDER BY bucket)
)
SELECT
    b.bucket,
    b.device_id,
    b.active_power_n, b.active_power_sum, b.active_power_min, b.active_power_max,
    b.active_power_sum / NULLIF(b.active_power_n, 0)       AS active_power_avg,
    b.voltage_n, b.voltage_min, b.voltage_max,
    b.voltage_sum / NULLIF(b.voltage_n, 0)                 AS voltage_avg,
    b.current_n, b.current_min, b.current_max,
    b.current_sum / NULLIF(b.current_n, 0)                 AS current_avg,
    b.reactive_power_sum / NULLIF(b.reactive_power_n, 0)   AS reactive_power_avg,
    b.apparent_power_sum / NULLIF(b.apparent_power_n, 0)   AS apparent_power_avg,
    b.power_factor_sum / NULLIF(b.power_factor_n, 0)       AS power_factor_avg,
    b.frequency_sum / NULLIF(b.frequency_n, 0)             AS frequency_avg,
    b.import_first, b.import_last, b.export_first, b.export_last,
    b.poll_interval_s,
    b.resolution_wh,
    -- całka mocy czynnej z obecnych próbek (Wh) i pokrycie okna próbkami
    b.active_power_sum * b.poll_interval_s / 3600.0         AS energy_integral_wh,
    -- LEAST ignoruje NULL, więc brak okresu próbkowania trzeba obsłużyć jawnie (NULL, nie domysł)
    CASE WHEN b.poll_interval_s IS NOT NULL
         THEN LEAST(1.0, b.active_power_n * b.poll_interval_s / 3600.0) END AS coverage,
    (b.bucket + INTERVAL '1 hour' <= now())               AS bucket_complete,
    -- przyrost licznika wzorcowego: różnica względem poprzedniego wiaderka z odczytem licznika
    CASE
        WHEN b.import_last IS NULL THEN NULL
        WHEN i.prev_import_last IS NULL THEN b.import_last - b.import_first
        WHEN b.import_last < i.prev_import_last THEN b.import_last
        ELSE b.import_last - i.prev_import_last
    END                                                     AS energy_import_delta_wh,
    CASE
        WHEN b.export_last IS NULL THEN NULL
        WHEN x.prev_export_last IS NULL THEN b.export_last - b.export_first
        WHEN b.export_last < x.prev_export_last THEN b.export_last
        ELSE b.export_last - x.prev_export_last
    END                                                     AS energy_export_delta_wh,
    COALESCE(b.import_last < i.prev_import_last, FALSE)     AS import_reset,
    COALESCE(b.export_last < x.prev_export_last, FALSE)     AS export_reset,
    COALESCE(b.bucket - i.prev_import_bucket > INTERVAL '1 hour', FALSE) AS gap_before,
    b.meter_error_seconds,
    b.meter_status_n,
    b.meter_error_seconds::float8 / NULLIF(b.meter_status_n, 0) AS meter_error_share
FROM base b
LEFT JOIN imp i ON i.device_id = b.device_id AND i.bucket = b.bucket
LEFT JOIN expo x ON x.device_id = b.device_id AND x.bucket = b.bucket;

-- migrate: next

-- Kontrola dobowa: całka mocy czynnej a przyrost licznika wzorcowego, doba lokalna Europe/Warsaw (stała do etapu 4).
-- Licznik zmienia stan co resolution_wh (100 Wh), więc przy małym obciążeniu przyrost dobowy to 1-2 kroki:
-- pierwszą miarą jest within_resolution, a deviation_pct tylko gdy przyrost >= 5 kroków licznika.
CREATE OR REPLACE VIEW energy_daily_check AS
WITH hours AS (
    SELECT c.*,
           (c.bucket AT TIME ZONE 'Europe/Warsaw')::date AS day
    FROM energy_1h_calc c
), days AS (
    SELECT
        device_id,
        day,
        sum(energy_integral_wh)                       AS integral_wh,
        sum(active_power_n * poll_interval_s)         AS covered_s,
        sum(energy_import_delta_wh)                   AS counter_delta_wh,
        max(resolution_wh)                            AS resolution_wh,
        count(*) FILTER (WHERE gap_before)            AS gap_before_count,
        count(*) FILTER (WHERE import_reset)          AS reset_count,
        bool_and(bucket_complete)                     AS buckets_complete
    FROM hours
    GROUP BY device_id, day
), sized AS (
    SELECT d.*,
           extract(epoch FROM ((d.day + 1)::timestamp AT TIME ZONE 'Europe/Warsaw')
                            - (d.day::timestamp AT TIME ZONE 'Europe/Warsaw'))::float8 AS day_length_s,
           ((d.day + 1)::timestamp AT TIME ZONE 'Europe/Warsaw') <= now() AS day_closed
    FROM days d
)
SELECT
    device_id,
    day,
    integral_wh,
    CASE WHEN covered_s IS NOT NULL THEN LEAST(1.0, covered_s / day_length_s) END      AS coverage,
    counter_delta_wh,
    CASE WHEN covered_s / day_length_s >= 0.5
         THEN integral_wh / (covered_s / day_length_s) END                            AS integral_extrapolated_wh,
    CASE WHEN covered_s / day_length_s >= 0.5
         THEN integral_wh / (covered_s / day_length_s) - counter_delta_wh END         AS diff_wh,
    resolution_wh,
    CASE WHEN covered_s / day_length_s >= 0.5 AND resolution_wh IS NOT NULL
         THEN abs(integral_wh / (covered_s / day_length_s) - counter_delta_wh) <= resolution_wh END AS within_resolution,
    CASE WHEN covered_s / day_length_s >= 0.5 AND resolution_wh IS NOT NULL AND counter_delta_wh >= 5 * resolution_wh
         THEN 100.0 * (integral_wh / (covered_s / day_length_s) - counter_delta_wh) / counter_delta_wh END AS deviation_pct,
    (day_closed AND buckets_complete)                                                 AS day_complete,
    gap_before_count,
    reset_count
FROM sized;

-- migrate: next

GRANT SELECT ON energy_1h, energy_1h_calc, energy_daily_check TO app_reader;
