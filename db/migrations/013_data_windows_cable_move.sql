-- 013_data_windows_cable_move: przełożenie kabla sieciowego IPC z enp1s0 do enp2s0 (E3-k7a, K7-U4).
-- 27.11.2026 ok. 20:49 czasu lokalnego Grzegorz przełożył kabel do drugiego portu (nowa dzierżawa DHCP 192.168.0.215). Jądro:
-- enp1s0 Link Down 19:49:22, enp2s0 Link Up 19:49:28 UTC; collector `plc: OK -> PLC_OFFLINE` 19:49:25 UTC. Granice z bazy:
-- ostatni wiersz real przed luką 19:49:22.160 UTC, koniec luki (pierwszy wiersz po drugiej, 2-sekundowej przerwie) 19:49:35.155 UTC.
-- Wcześniejsza „przerwa sieci” 17:46–20:49 dotyczyła tylko drogi dostępu laptopa: dane real szły wtedy 20 wierszy/s (raport e3-k7a).

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-27 19:49:22.160+00', '2026-11-27 19:49:35.155+00', 'network_outage',
     'Przelozenie kabla sieciowego IPC do portu enp2s0 (nowy adres 192.168.0.215), luka w danych real 13 s', TRUE);
