-- 004_data_windows: okna testów i przerw w danych (adnotacje Grafany, wykluczenia w analityce), etap 2, k7.
-- Tabela tylko do odczytu dla aplikacji: wpisy dodaje wyłącznie `migrate` (nowa migracja na każde nowe okno).
-- exclude_from_analytics: FALSE tylko dla okna referencyjnego (calm_window), które nie jest przerwą ani zakłóceniem.
-- Granice okien: dla zdarzeń z k5 wg docs/handoff/e2-k5-report.md; zanik zasilania i przerwa diagnostyczna z luk w danych
-- (ostatni wiersz przed luką i pierwszy po niej); wdrożenie k6 wg logu migrate/collector. Nie edytuj po zastosowaniu.

CREATE TABLE data_windows (
    id          BIGSERIAL PRIMARY KEY,
    start_time  TIMESTAMPTZ NOT NULL,
    end_time    TIMESTAMPTZ NOT NULL CHECK (end_time >= start_time),
    kind        TEXT        NOT NULL CHECK (kind ~ '^[a-z0-9_]+$'),
    description TEXT        NOT NULL,
    exclude_from_analytics BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX data_windows_start_idx ON data_windows (start_time);

INSERT INTO data_windows (start_time, end_time, kind, description, exclude_from_analytics) VALUES
    ('2026-11-23 22:38:25+00', '2026-11-23 22:38:26+00', 'collector_start',
     'Start collectora (rozgrzewka jednego cyklu)', TRUE),
    ('2026-11-23 22:41:00+00', '2026-11-23 22:51:00+00', 'calm_window',
     'Okno referencyjne 10 min, bez testów (epizody błędu licznika co 64 s w środku)', FALSE),
    ('2026-11-23 22:52:14+00', '2026-11-23 22:52:26+00', 'mqtt_broker_restart',
     'Restart brokera MQTT (0 s luki, 0 duplikatów)', TRUE),
    ('2026-11-23 22:53:44+00', '2026-11-23 22:55:37+00', 'collector_stopped',
     'Diagnostyka: collector zatrzymany, brak danych z tego okna', TRUE),
    ('2026-11-23 22:56:35+00', '2026-11-23 22:57:27+00', 'rs485_break',
     'Test przerwy RS485 (odłączony przewód): meter_status = 1 przez 52 s', TRUE),
    ('2026-11-23 22:58:59+00', '2026-11-23 23:00:33+00', 'plc_lan1_unplugged',
     'Test PLC offline (kabel LAN1 odłączony): link_status = 1 przez 94 s', TRUE),
    ('2026-11-23 23:03:39+00', '2026-11-23 23:05:25+00', 'plc_program_stop',
     'Test Stop programu w CODESYS: link_status = 1, serwer Modbus nie odpowiadał', TRUE),
    ('2026-11-23 23:16:57.132+00', '2026-11-24 06:52:43.248+00', 'power_outage',
     'Zanik zasilania PLC, licznika i komputera (do pierwszego wiersza po starcie collectora)', TRUE),
    ('2026-11-24 11:03:53.043+00', '2026-11-24 11:18:57.442+00', 'collector_stopped',
     'Diagnostyka E2-PLC1: collector zatrzymany na 15 min', TRUE),
    ('2026-11-24 14:33:59+00', '2026-11-24 14:34:30+00', 'deploy',
     'Wdrożenie k6: restart collectora i ingestu, migracje 002 i 003', TRUE);

GRANT SELECT ON data_windows TO app_reader;
