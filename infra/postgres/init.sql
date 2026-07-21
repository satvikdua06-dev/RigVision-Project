-- ──────────────────────────────────────────────────────────
-- RigVision-3D — PostgreSQL + TimescaleDB Initialization
-- ──────────────────────────────────────────────────────────
-- This runs automatically on first 'docker compose up'.
-- It creates the TimescaleDB extension and all tables.
-- ──────────────────────────────────────────────────────────

-- Enable TimescaleDB extension
-- This turns regular Postgres tables into "hypertables" that
-- automatically partition data by time for fast time-range queries.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Sensor Readings ──
-- Raw time-series data from all sensors.
-- Each row = one sensor reading at one point in time.
-- TimescaleDB will partition this by 'recorded_at' automatically.
CREATE TABLE IF NOT EXISTS sensor_readings (
    id              BIGSERIAL,
    zone_id         VARCHAR(50)    NOT NULL,
    sensor_type     VARCHAR(50)    NOT NULL,   -- temperature, vibration, noise, gas_h2s, pressure
    value           DOUBLE PRECISION NOT NULL,
    unit            VARCHAR(20)    NOT NULL,   -- °C, g_rms, dB, ppm, bar
    recorded_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, recorded_at)
);

-- Convert to hypertable (TimescaleDB magic)
-- Chunks data into 1-hour intervals for efficient queries
SELECT create_hypertable('sensor_readings', 'recorded_at',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- Index for "get all readings for a zone in a time range"
CREATE INDEX IF NOT EXISTS idx_sensor_zone_time
    ON sensor_readings (zone_id, recorded_at DESC);

-- Index for "get all readings of a sensor type across zones"
CREATE INDEX IF NOT EXISTS idx_sensor_type_time
    ON sensor_readings (sensor_type, recorded_at DESC);

-- ── Violations ──
-- Compliance rule violations with evidence.
-- Each row = one violation event (e.g., "person missing hard hat").
CREATE TABLE IF NOT EXISTS violations (
    id              VARCHAR(50)    PRIMARY KEY,
    rule_id         VARCHAR(50)    NOT NULL,   -- e.g., PPE-001, ENV-001, OCC-001
    zone_id         VARCHAR(50)    NOT NULL,
    severity        VARCHAR(20)    NOT NULL,   -- LOW, MEDIUM, HIGH, CRITICAL
    message         TEXT           NOT NULL,
    person_ids      INTEGER[]      DEFAULT '{}',  -- which persons were involved
    evidence_frame  BYTEA,                      -- JPEG snapshot as evidence
    detected_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,                -- NULL = still active
    resolved_by     VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_violations_zone
    ON violations (zone_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_violations_severity
    ON violations (severity, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_violations_active
    ON violations (resolved_at) WHERE resolved_at IS NULL;

-- ── Anomalies ──
-- Detected sensor anomalies (Z-score, threshold, rate-of-change).
-- Each row = one anomaly event with its root-cause analysis.
CREATE TABLE IF NOT EXISTS anomalies (
    id              BIGSERIAL      PRIMARY KEY,
    zone_id         VARCHAR(50)    NOT NULL,
    sensor_type     VARCHAR(50)    NOT NULL,
    anomaly_type    VARCHAR(50)    NOT NULL,   -- threshold, zscore, rate_of_change, correlation
    value           DOUBLE PRECISION NOT NULL,
    threshold       DOUBLE PRECISION,
    z_score         DOUBLE PRECISION,
    severity        VARCHAR(20)    NOT NULL,
    message         TEXT           NOT NULL,
    root_cause      TEXT,                       -- LLM-generated root cause (Phase 7)
    detected_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_zone_time
    ON anomalies (zone_id, detected_at DESC);

-- ── Person Tracking History ──
-- Historical positions of tracked persons (for replay/analysis).
CREATE TABLE IF NOT EXISTS person_tracking (
    id              BIGSERIAL,
    person_id       INTEGER        NOT NULL,
    x               DOUBLE PRECISION NOT NULL,
    y               DOUBLE PRECISION NOT NULL,
    z               DOUBLE PRECISION NOT NULL,
    zone_id         VARCHAR(50),
    posture         VARCHAR(20),
    ppe_hardhat     BOOLEAN        DEFAULT FALSE,
    ppe_vest        BOOLEAN        DEFAULT FALSE,
    ppe_goggles     BOOLEAN        DEFAULT FALSE,
    confidence      DOUBLE PRECISION,
    cameras_visible INTEGER        DEFAULT 1,
    recorded_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, recorded_at)
);

SELECT create_hypertable('person_tracking', 'recorded_at',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_person_tracking_person_time
    ON person_tracking (person_id, recorded_at DESC);

-- ── Permits (Permit-to-Work) ──
CREATE TABLE IF NOT EXISTS permits (
    permit_id       TEXT            PRIMARY KEY,
    type            TEXT            NOT NULL,   -- hot_work, confined_space, electrical, excavation
    zone            TEXT            NOT NULL,
    description     TEXT            NOT NULL,
    workers         TEXT[]          DEFAULT '{}',
    issued_by       TEXT            NOT NULL,
    start_time      TIMESTAMPTZ     NOT NULL,
    end_time        TIMESTAMPTZ     NOT NULL,
    status          TEXT            NOT NULL DEFAULT 'active',  -- active, closed, expired, revoked
    requires_gas_clear  BOOLEAN     DEFAULT FALSE,
    gas_clear_ppm   DOUBLE PRECISION DEFAULT 10.0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_permits_zone_status
    ON permits (zone, status);

CREATE INDEX IF NOT EXISTS idx_permits_status_time
    ON permits (status, start_time DESC);

-- ── Incidents ──
CREATE TABLE IF NOT EXISTS incidents (
    incident_id         TEXT            PRIMARY KEY,
    severity            TEXT            NOT NULL,   -- HIGH, CRITICAL
    title               TEXT            NOT NULL,
    rules_fired         JSONB           DEFAULT '[]',
    sensor_snapshot     JSONB           DEFAULT '{}',
    persons_snapshot    JSONB           DEFAULT '[]',
    permits_snapshot    JSONB           DEFAULT '[]',
    report_text         TEXT,
    status              TEXT            NOT NULL DEFAULT 'open',  -- open, acknowledged, closed
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    acknowledged_at     TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_incidents_severity_time
    ON incidents (severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_status
    ON incidents (status, created_at DESC);

-- ──────────────────────────────────────────────────────────
-- Done! Tables created:
--   sensor_readings  (hypertable) — raw sensor time-series
--   violations       — compliance violations with evidence
--   anomalies        — detected sensor anomalies
--   person_tracking  (hypertable) — historical person positions
--   permits          — permit-to-work records
--   incidents        — compound risk incident log
-- ──────────────────────────────────────────────────────────
