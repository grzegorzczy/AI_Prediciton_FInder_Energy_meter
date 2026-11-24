-- 003_energy_views: widoki pochodne energii (etap 2, k6). Transakcyjna.
-- Wartości pochodne (średnie, całka, pokrycie, przyrost licznika) są w widokach, a nie w agregatach ciągłych,
-- bo tylko wartości addytywne można poprawnie złożyć w agregat godzinny.
-- Okres próbkowania i rozdzielczość licznika pochodzą z devices.meta (poll_interval_s, energy_resolution_wh; ingest
-- synchronizuje je z config/devices.yaml, reguła 3). Brak wartości w meta daje NULL, a nie domysł.
-- Luki są normalnym stanem danych: całka liczy tylko obecne próbki, bez interpolacji przez luki.
-- Przyrost licznika liczony jest względem poprzedniego wiaderka Z odczytem licznika (LAG po wierszach z licznikiem),
-- więc minuty bez odczytu energii (np. awaria licznika) nie zerują przyrostu następnego wiaderka.
-- Nie edytuj tego pliku po zastosowaniu: zmianę wprowadza nowa migracja (suma kontrolna).

CREATE VIEW energy_1m_calc AS
WITH base AS (
    SELECT e.*,
           (d.meta ->> 'poll_interval_s')::float8      AS poll_interval_s,
           (d.meta ->> 'energy_resolution_wh')::float8 AS resolution_wh
    FROM energy_1m e
    JOIN devices d USING (device_id)
), imp AS (
    SELECT device_id, bucket,
           lag(import_last) OVER w AS prev_import_last,
           lag(bucket)      OVER w AS prev_import_bucket
    FROM energy_1m
    WHERE import_last IS NOT NULL
    WINDOW w AS (PARTITION BY device_id ORDER BY bucket)
), expo AS (
    SELECT device_id, bucket,
           lag(export_last) OVER w AS prev_export_last
    FROM energy_1m
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
    LEAST(1.0, b.active_power_n * b.poll_interval_s / 60.0) AS coverage,
    (b.bucket + INTERVAL '1 minute' <= now())               AS bucket_complete,
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
    COALESCE(b.bucket - i.prev_import_bucket > INTERVAL '1 minute', FALSE) AS gap_before,
    b.meter_error_seconds,
    b.meter_status_n,
    b.meter_error_seconds::float8 / NULLIF(b.meter_status_n, 0) AS meter_error_share
FROM base b
LEFT JOIN imp i ON i.device_id = b.device_id AND i.bucket = b.bucket
LEFT JOIN expo x ON x.device_id = b.device_id AND x.bucket = b.bucket;

CREATE VIEW energy_1h_calc AS
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
    LEAST(1.0, b.active_power_n * b.poll_interval_s / 3600.0) AS coverage,
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

-- Kontrola dobowa: całka mocy czynnej a przyrost licznika wzorcowego, doba lokalna Europe/Warsaw (stała do etapu 4).
-- Licznik zmienia stan co resolution_wh (100 Wh), więc przy małym obciążeniu przyrost dobowy to 1-2 kroki:
-- pierwszą miarą jest within_resolution, a deviation_pct tylko gdy przyrost >= 5 kroków licznika.
CREATE VIEW energy_daily_check AS
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
    LEAST(1.0, covered_s / day_length_s)                                              AS coverage,
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

GRANT SELECT ON energy_1m, energy_1h, energy_1m_calc, energy_1h_calc, energy_daily_check TO app_reader;
