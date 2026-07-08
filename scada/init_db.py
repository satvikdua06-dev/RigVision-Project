"""
TimescaleDB / PostgreSQL initialisation for the SCADA layer.

Creates the sensor_readings table and attempts to turn it into a
TimescaleDB hypertable. Silently continues with a plain table if the
TimescaleDB extension is not installed.

Can be called as a module:
    python -m scada.init_db

Or imported and called programmatically:
    from scada.init_db import init_db
    init_db()
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scada_readings (
    time       TIMESTAMPTZ      NOT NULL,
    sensor_id  TEXT             NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    unit       TEXT,
    quality    TEXT,
    protocol   TEXT,
    device     TEXT
);
"""

_CREATE_HYPERTABLE = """
SELECT create_hypertable(
    'scada_readings', 'time',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS scada_readings_sensor_id_time_idx
    ON scada_readings (sensor_id, time DESC);
"""


def init_db(retries: int = 5, retry_delay: float = 3.0) -> bool:
    """
    Connect to Postgres, create the schema, attempt TimescaleDB hypertable.
    Returns True on success, False if Postgres is unreachable after all retries.
    """
    import psycopg2

    conn_kwargs = dict(
        host     = os.getenv("POSTGRES_HOST",     "localhost"),
        port     = int(os.getenv("POSTGRES_PORT", "5432")),
        dbname   = os.getenv("POSTGRES_DB",       "rigvision"),
        user     = os.getenv("POSTGRES_USER",     "rigvision"),
        password = os.getenv("POSTGRES_PASSWORD", "rigvision_dev_password"),
    )

    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(**conn_kwargs)
            break
        except psycopg2.OperationalError as e:
            msg = str(e).lower()
            # Auth failures won't resolve by retrying
            if "password authentication failed" in msg or "role" in msg:
                log.error(f"[init_db] Postgres auth failed: {e}")
                log.error("[init_db] Check POSTGRES_USER / POSTGRES_PASSWORD in .env match docker-compose.yml")
                return False
            log.warning(f"[init_db] Postgres not ready (attempt {attempt}/{retries}): {e}")
            if attempt == retries:
                log.error("[init_db] Could not connect to Postgres - schema not created")
                return False
            time.sleep(retry_delay)

    with conn:
        with conn.cursor() as cur:
            # Create plain table
            cur.execute(_CREATE_TABLE)
            conn.commit()
            log.info("[init_db] scada_readings table ready")

            # Try to promote to hypertable
            try:
                cur.execute(_CREATE_HYPERTABLE)
                conn.commit()
                log.info("[init_db] TimescaleDB hypertable ready")
            except psycopg2.Error:
                conn.rollback()
                log.info("[init_db] TimescaleDB extension not present - using plain PostgreSQL table")

            # Create covering index (safe to re-run)
            try:
                cur.execute(_CREATE_INDEX)
                conn.commit()
                log.info("[init_db] Indexes ready")
            except psycopg2.Error:
                conn.rollback()

    conn.close()
    log.info("[init_db] Database initialisation complete")
    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Load .env if present
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    success = init_db()
    sys.exit(0 if success else 1)
