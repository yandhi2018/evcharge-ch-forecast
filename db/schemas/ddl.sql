-- Слоистая схема хранения. Выполняется один раз при инициализации БД
-- (psql -U evcharge -d evcharge -f db/schemas/ddl.sql).

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS ops;

-- ops: журнал загрузок. Один запуск конвейера = одна строка.
CREATE TABLE IF NOT EXISTS ops.load_log (
    run_id              UUID PRIMARY KEY,
    source              TEXT NOT NULL,             -- 'evse_status' | 'evse_data' | 'weather'
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL,              -- success | skipped | partial | error
    params              JSONB,                      -- параметры запуска (slot, канton, диапазон дат и т.п.)
    response_code       INTEGER,
    attempts            INTEGER NOT NULL DEFAULT 1,
    changed_at          TIMESTAMPTZ,                -- дата изменения источника (для EVSEData)
    content_checksum    TEXT,                       -- контрольная сумма выгрузки
    raw_file_path       TEXT,
    rows_received       INTEGER,
    rows_written         INTEGER,
    duplicate_count     INTEGER,
    missing_id_count    INTEGER,
    error_text          TEXT
);

CREATE INDEX IF NOT EXISTS ix_load_log_source_started ON ops.load_log (source, started_at DESC);

-- raw.evse_status_snapshot: один снимок статуса на 15-минутный слот.
-- Идемпотентность: (slot, evse_id).
CREATE TABLE IF NOT EXISTS raw.evse_status_snapshot (
    slot        TIMESTAMPTZ NOT NULL,
    evse_id     TEXT NOT NULL,
    status      TEXT NOT NULL,
    run_id      UUID NOT NULL REFERENCES ops.load_log(run_id),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (slot, evse_id)
);

CREATE INDEX IF NOT EXISTS ix_evse_status_evse ON raw.evse_status_snapshot (evse_id, slot);

-- raw.evse_data_snapshot: справочник точек. Хранится только текущая версия записи
-- по каждой evse_id + история версий по хэшу содержимого.
-- Идемпотентность: (evse_id, content_hash).
CREATE TABLE IF NOT EXISTS raw.evse_data_snapshot (
    evse_id       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    record        JSONB NOT NULL,
    run_id        UUID NOT NULL REFERENCES ops.load_log(run_id),
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (evse_id, content_hash)
);

CREATE INDEX IF NOT EXISTS ix_evse_data_evse ON raw.evse_data_snapshot (evse_id, valid_from DESC);

-- raw.weather_hourly: почасовые погодные наблюдения по опорной точке кантона.
-- Идемпотентность: (canton_code, hour_ts) — вставка с обновлением.
CREATE TABLE IF NOT EXISTS raw.weather_hourly (
    canton_code     TEXT NOT NULL,
    hour_ts         TIMESTAMPTZ NOT NULL,
    temperature_2m  DOUBLE PRECISION,
    precipitation   DOUBLE PRECISION,
    snowfall        DOUBLE PRECISION,
    wind_speed_10m  DOUBLE PRECISION,
    run_id          UUID NOT NULL REFERENCES ops.load_log(run_id),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canton_code, hour_ts)
);
