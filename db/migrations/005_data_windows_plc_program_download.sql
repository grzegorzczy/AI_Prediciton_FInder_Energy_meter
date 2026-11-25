-- 005_data_windows_plc_program_download: okno pobrania programu do PLC (adnotacja Grafany, wykluczenie z analityki), k7c.
-- Grzegorz potwierdził 25.11.2026: 24.11 ok. 15:25 czasu lokalnego wgrał program do PLC (download z CODESYS po poprawce
-- FB_EnergyMeter). Granice z bazy: pierwszy i ostatni wiersz link_status = 1 w tym epizodzie (18 wierszy, 17,002 s); pierwszy
-- wiersz link_status = 0 po nim: 14:25:22.514. Skutek: wyzerowanie meter_error_count (reset liczników FB).
-- Stare migracje bez zmian (sumy kontrolne); ograniczenie rodzaju w data_windows to tylko wzorzec ^[a-z0-9_]+$, więc nie wymaga zmiany.

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-24 14:25:03.390+00', '2026-11-24 14:25:20.392+00', 'plc_program_download',
     'Download programu PLC (Grzegorz), reset liczników FB', TRUE);
