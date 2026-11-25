-- SZKIC migracji 011_data_windows_ipc_reboot (E2-k8a). NIE jest w db/migrations/ celowo: trafi tam dopiero po teście restartu,
-- bo granice okna pochodzą z bazy (ostatni wiersz przed restartem, pierwszy po). Wzór jak 005/006/010; `kind` ma tylko wzorzec
-- ^[a-z0-9_]+$, więc nie wymaga zmiany ograniczenia. Stare migracje bez zmian (sumy kontrolne).
--
-- Wartości do wstawienia po teście (zapytania, do wykonania po powrocie komputera):
--   SELECT max(time) FROM measurements WHERE time < '<czas_rozruchu_UTC>';        -- last_before
--   SELECT min(time) FROM measurements WHERE time >= '<czas_rozruchu_UTC>';       -- first_after
-- Okno: start = last_before (włącznie, ostatni zapisany wiersz przed przerwą), end = first_after.
-- exclude_from_analytics = TRUE (luka w danych i niestabilny start; analityka etapu 4 ma to pomijać).

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('<last_before>+00', '<first_after>+00', 'ipc_reboot',
     'Restart komputera przemysłowego (test k8, sudo reboot): luka w danych do pierwszego wiersza po starcie stosu', TRUE);

-- Po dodaniu migracji: w tests/db/test_data_windows.py dopisać "ipc_reboot" na końcu listy rodzajów, zmienić liczbę 13 -> 14
-- (test_reader_reads...) oraz sprawdzić dokumentację okien (docs/data-model.md). Wdrożenie: R-1 z --build.
