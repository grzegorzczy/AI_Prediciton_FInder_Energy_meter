-- 001_core: tabele devices i measurements (etap 2, k2).
-- Role app_writer i app_reader istnieją przed migracjami (tworzy je migrate.py).
-- Nie edytuj tego pliku po zastosowaniu: zmianę wprowadza nowa migracja (suma kontrolna).

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Odbicie config/devices.yaml; wpisy dodaje ingest (reguła 3: dane urządzeń tylko w configu).
CREATE TABLE devices (
    device_id TEXT PRIMARY KEY CHECK (device_id ~ '^[A-Za-z0-9_-]+$'),
    name      TEXT NOT NULL,
    site      TEXT NOT NULL,
    line      TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN ('plc', 'energy_meter', 'pump')),
    source    TEXT NOT NULL CHECK (source IN ('real', 'sim')),
    enabled   BOOLEAN NOT NULL DEFAULT TRUE,
    meta      JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Jedna wąska tabela pomiarów: wiersz = jedna wartość jednej metryki w chwili.
CREATE TABLE measurements (
    time      TIMESTAMPTZ      NOT NULL,
    device_id TEXT             NOT NULL REFERENCES devices (device_id),
    metric    TEXT             NOT NULL CHECK (metric ~ '^[a-z0-9_]+$'),
    value     DOUBLE PRECISION NOT NULL
              CHECK (value NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)),
    unit      TEXT             NOT NULL,
    source    TEXT             NOT NULL CHECK (source IN ('real', 'sim')),
    UNIQUE (device_id, metric, time)
);

SELECT create_hypertable('measurements', 'time', chunk_time_interval => INTERVAL '1 day');

ALTER TABLE measurements SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id, metric',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('measurements', INTERVAL '1 day');
SELECT add_retention_policy('measurements', INTERVAL '90 days');

-- Najmniejsze uprawnienia: ingest zapisuje pomiary i synchronizuje devices; bez DELETE i DDL.
GRANT SELECT, INSERT ON measurements TO app_writer;
GRANT SELECT, INSERT, UPDATE ON devices TO app_writer;
