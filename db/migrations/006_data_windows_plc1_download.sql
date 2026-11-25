-- 006_data_windows_plc1_download: okno pobrania programu do PLC w kroku PLC-1 (E2-PLC2), adnotacja Grafany, wykluczenie z analityki.
-- 25.11.2026 ok. 09:16 czasu lokalnego Grzegorz wgrał do PLC program z nowymi kanałami RTU (jakość, temperatura, czas pracy; mapa wciąż v1).
-- Granice z bazy: pierwszy i ostatni wiersz link_status != 0 w tym epizodzie (10 wierszy, 8,003 s); pierwszy wiersz link_status = 0
-- po nim: 08:16:20.611 UTC. Skutek: wyzerowanie meter_error_count (54 -> 0). Stare migracje bez zmian (sumy kontrolne).

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-25 08:16:10.574+00', '2026-11-25 08:16:18.577+00', 'plc_program_download',
     'Download programu PLC (PLC-1: nowe kanały RTU, mapa v1), reset liczników FB', TRUE);
