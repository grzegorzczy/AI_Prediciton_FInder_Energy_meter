-- 011_data_windows_ipc_reboot: okno restartu komputera przemysłowego w teście k8 (E2-k8a).
-- 25.11.2026 o 13:03:4x czasu lokalnego Grzegorz wykonał `sudo reboot` na komputerze (czyste zamknięcie: usługi zatrzymane przez systemd,
-- kolejno collector 12:03:48.000, baza 12:03:48.028, ingest 12:03:49 UTC). Granice z bazy: ostatni wiersz link_status przed przerwą
-- 12:03:47.557 UTC, pierwszy po starcie stosu 12:04:24.705 UTC (collector: start 12:04:23.674, `plc: (start) -> OK` 12:04:24.708).
-- Luka 37,148 s; poza nią żadnej sekundy z liczbą wierszy innej niż 20. Wzorzec `kind` ^[a-z0-9_]+$, więc ograniczenie bez zmian.
-- Stare migracje bez zmian (sumy kontrolne).

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-25 12:03:47.557+00', '2026-11-25 12:04:24.705+00', 'ipc_reboot',
     'Restart komputera przemyslowego (test k8: sudo reboot), luka w danych do pierwszego wiersza po starcie stosu', TRUE);
