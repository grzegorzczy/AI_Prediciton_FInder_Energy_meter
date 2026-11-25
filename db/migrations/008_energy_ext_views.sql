-- 008_energy_ext_views: widok energii biernej (E2-PLC2, krok 2). Transakcyjna.
-- reactive_1h_calc: przyrost liczników energii biernej n2 (Q > 0, `pos`) i n4 (Q < 0, `neg`) oraz całka mocy biernej z podziałem
-- na znak (ta sama konstrukcja co energy_1h_calc, D7): obie miary obok siebie. Rozdzielczość licznika (100 varh) i okres próbkowania
-- z devices.meta (reactive_resolution_varh, poll_interval_s); brak wartości daje NULL, a nie domysł.
-- Przyrost liczony względem poprzedniego wiaderka Z odczytem licznika (LAG po wierszach z licznikiem), reset licznika
-- (wartość mniejsza od poprzedniej: przyrost = wartość) i flagi pos_gap_before i neg_gap_before (osobno dla każdego licznika) jak gap_before w energy_1h_calc. Całka neg jest podana jako wartość
-- dodatnia (moduł), żeby porównywać ją wprost ze stanem licznika n4.
-- Przy obecnym obciążeniu (Q ok. -9 var) licznik zmienia stan co 100 varh, czyli raz na ok. 11 godzin: przyrost godzinowy
-- jest prawie zawsze 0; całka mocy daje bieżący obraz.
-- Nie edytuj po zastosowaniu: zmianę wprowadza nowa migracja.

CREATE VIEW reactive_1h_calc AS
WITH base AS (
    SELECT e.*,
           (d.meta ->> 'poll_interval_s')::float8            AS poll_interval_s,
           (d.meta ->> 'reactive_resolution_varh')::float8   AS resolution_varh
    FROM energy_ext_1h e
    JOIN devices d USING (device_id)
), pos AS (
    SELECT device_id, bucket,
           lag(counter_pos_last) OVER w AS prev_last,
           lag(bucket)           OVER w AS prev_bucket
    FROM energy_ext_1h
    WHERE counter_pos_last IS NOT NULL
    WINDOW w AS (PARTITION BY device_id ORDER BY bucket)
), neg AS (
    SELECT device_id, bucket,
           lag(counter_neg_last) OVER w AS prev_last,
           lag(bucket)           OVER w AS prev_bucket
    FROM energy_ext_1h
    WHERE counter_neg_last IS NOT NULL
    WINDOW w AS (PARTITION BY device_id ORDER BY bucket)
)
SELECT
    b.bucket,
    b.device_id,
    b.counter_pos_first, b.counter_pos_last, b.counter_neg_first, b.counter_neg_last,
    b.poll_interval_s,
    b.resolution_varh,
    -- przyrost stanu licznika w godzinie
    CASE
        WHEN b.counter_pos_last IS NULL THEN NULL
        WHEN p.prev_last IS NULL THEN b.counter_pos_last - b.counter_pos_first
        WHEN b.counter_pos_last < p.prev_last THEN b.counter_pos_last
        ELSE b.counter_pos_last - p.prev_last
    END                                                      AS reactive_pos_delta_varh,
    CASE
        WHEN b.counter_neg_last IS NULL THEN NULL
        WHEN n.prev_last IS NULL THEN b.counter_neg_last - b.counter_neg_first
        WHEN b.counter_neg_last < n.prev_last THEN b.counter_neg_last
        ELSE b.counter_neg_last - n.prev_last
    END                                                      AS reactive_neg_delta_varh,
    COALESCE(b.counter_pos_last < p.prev_last, FALSE)        AS pos_reset,
    COALESCE(b.counter_neg_last < n.prev_last, FALSE)        AS neg_reset,
    COALESCE(b.bucket - p.prev_bucket > INTERVAL '1 hour', FALSE) AS pos_gap_before,
    COALESCE(b.bucket - n.prev_bucket > INTERVAL '1 hour', FALSE) AS neg_gap_before,
    -- całka mocy biernej (Q > 0 i |Q| przy Q < 0) z obecnych próbek i pokrycie godziny pomiarem Q
    b.reactive_pos_sum * b.poll_interval_s / 3600.0          AS reactive_pos_integral_varh,
    -b.reactive_neg_sum * b.poll_interval_s / 3600.0         AS reactive_neg_integral_varh,
    CASE WHEN b.poll_interval_s IS NOT NULL
         THEN LEAST(1.0, b.reactive_power_n * b.poll_interval_s / 3600.0) END AS coverage,
    (b.bucket + INTERVAL '1 hour' <= now())                  AS bucket_complete
FROM base b
LEFT JOIN pos p ON p.device_id = b.device_id AND p.bucket = b.bucket
LEFT JOIN neg n ON n.device_id = b.device_id AND n.bucket = b.bucket;

GRANT SELECT ON energy_ext_1m, energy_ext_1h, reactive_1h_calc TO app_reader;
