-- 010_data_windows_plc2_download: okno pobrania programu do PLC w kroku PLC-2 (E2-PLC2, krok 4): przełączenie mapy Modbus na v2.
-- 25.11.2026 ok. 11:42-11:43 czasu lokalnego Grzegorz wgrał do PLC program z mapą v2 (nowy FB_EnergyMeter, rejestry 44-59).
-- Granice z bazy: pierwszy i ostatni wiersz link_status != 0 w tym epizodzie (10 wierszy, 8,003 s); pierwszy wiersz link_status = 0
-- po nim: 10:43:11.557 UTC (collector zalogował zmianę wersji mapy 1 -> 2 o 10:43:10.757 UTC). Skutek: wyzerowanie meter_error_count.
-- Stare migracje bez zmian (sumy kontrolne).

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-25 10:43:01.518+00', '2026-11-25 10:43:09.521+00', 'plc_program_download',
     'Download programu PLC (PLC-2: mapa Modbus v2, nowy FB_EnergyMeter), reset liczników FB', TRUE);
