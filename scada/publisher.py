"""
SCADA Publisher — drains the normalised-reading queue and writes to:

  1. Redis  rigvision:sensors:latest   (frontend real-time display)
  2. TimescaleDB scada_readings hypertable  (historical queries)

Only "good" quality readings are written.
Batches up to SCADA_BATCH_SIZE readings or waits SCADA_BATCH_MAX_WAIT_MS ms,
whichever comes first, before flushing — reduces per-reading overhead.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

import redis as redis_lib

from .normalizer import NormalizedReading

log = logging.getLogger(__name__)

BATCH_SIZE     = int(os.getenv("SCADA_BATCH_SIZE",        "20"))
BATCH_MAX_WAIT = float(os.getenv("SCADA_BATCH_MAX_WAIT_MS", "500")) / 1000.0

REDIS_SENSORS_KEY = "rigvision:sensors:latest"


class Publisher(threading.Thread):

    def __init__(self, q: queue.Queue):
        super().__init__(name="Publisher", daemon=True)
        self.queue  = q
        self._stop  = threading.Event()
        self._redis: Optional[redis_lib.Redis] = None
        self._pg                               = None

    def stop(self) -> None:
        self._stop.set()

    # ── Connection helpers ─────────────────────────────────────────────────────

    def _connect_redis(self) -> None:
        self._redis = redis_lib.Redis(
            host     = os.getenv("REDIS_HOST",     "localhost"),
            port     = int(os.getenv("REDIS_PORT", "6379")),
            password = os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        self._redis.ping()

    def _connect_pg(self) -> None:
        import psycopg2
        self._pg = psycopg2.connect(
            host     = os.getenv("POSTGRES_HOST",     "localhost"),
            port     = int(os.getenv("POSTGRES_PORT", "5432")),
            dbname   = os.getenv("POSTGRES_DB",       "rigvision"),
            user     = os.getenv("POSTGRES_USER",     "rigvision"),
            password = os.getenv("POSTGRES_PASSWORD", "rigvision_dev_password"),
        )
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._pg.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scada_readings (
                    time       TIMESTAMPTZ       NOT NULL,
                    sensor_id  TEXT              NOT NULL,
                    value      DOUBLE PRECISION  NOT NULL,
                    unit       TEXT,
                    quality    TEXT,
                    protocol   TEXT,
                    device     TEXT
                );
            """)
            # Attempt TimescaleDB hypertable; silently skip if extension absent
            try:
                cur.execute("""
                    SELECT create_hypertable(
                        'scada_readings', 'time',
                        if_not_exists => TRUE,
                        migrate_data  => TRUE
                    );
                """)
            except Exception:
                self._pg.rollback()
                log.info("[publisher] TimescaleDB extension not found — using plain PostgreSQL table")
            self._pg.commit()

    # ── Writers ────────────────────────────────────────────────────────────────

    _SENSOR_FIELD = {
        "temp": "temperature", "vib": "vibration",
        "gas": "gas_h2s", "noise": "noise", "pressure": "pressure",
    }

    def _sensor_to_zone(self, sensor_id: str) -> str:
        clean_id = sensor_id
        if clean_id.endswith("_f1"):
            clean_id = clean_id[:-3]
        parts = clean_id.split("_")
        if len(parts) > 1:
            suffix = parts[-1]
            return f"zone_{suffix}"
        return "unknown"

    def _write_redis(self, batch: list[NormalizedReading]) -> None:
        for r in batch:
            # 1. Update rigvision:sensors:latest hash
            sensor_data = {
                "value": r.value,
                "updated_at": r.timestamp,
                "source": r.protocol
            }
            self._redis.hset(REDIS_SENSORS_KEY, r.sensor_id, json.dumps(sensor_data))

            # 2. Update rigvision:zones hash
            zone_id = self._sensor_to_zone(r.sensor_id)
            if zone_id == "unknown":
                continue

            # Determine field name
            prefix = r.sensor_id.split("_")[0]
            field = self._SENSOR_FIELD.get(prefix)
            if not field:
                continue

            raw = self._redis.hget("rigvision:zones", zone_id)
            z = json.loads(raw) if raw else {
                "status": "normal", "temperature": 25.0, "vibration": 0.0,
                "noise": 40.0, "gas_h2s": 0.0, "pressure": 1.0,
                "person_count": 0, "ppe_violations": [], "updated_at": int(time.time()),
            }
            z[field] = round(r.value, 3)
            z.setdefault("sensor_sources", {})[field] = r.protocol
            z["updated_at"] = int(time.time())
            self._redis.hset("rigvision:zones", zone_id, json.dumps(z))

    def _write_pg(self, batch: list[NormalizedReading]) -> None:
        from psycopg2.extras import execute_values
        rows = [
            (
                datetime.fromtimestamp(r.timestamp, tz=timezone.utc),
                r.sensor_id, r.value, r.unit, r.quality, r.protocol, r.device,
            )
            for r in batch
        ]
        with self._pg.cursor() as cur:
            execute_values(cur, """
                INSERT INTO scada_readings
                    (time, sensor_id, value, unit, quality, protocol, device)
                VALUES %s
            """, rows)
        self._pg.commit()

    # ── Thread main ────────────────────────────────────────────────────────────

    def run(self) -> None:
        # Connect Redis (retry up to 5×)
        for attempt in range(5):
            try:
                self._connect_redis()
                log.info("[publisher] Redis connected")
                break
            except Exception as e:
                log.warning(f"[publisher] Redis connect failed ({e}), retry in {2**attempt}s")
                time.sleep(2 ** attempt)

        # Connect Postgres (retry up to 5×)
        for attempt in range(5):
            try:
                self._connect_pg()
                log.info("[publisher] Postgres connected")
                break
            except Exception as e:
                log.warning(f"[publisher] Postgres connect failed ({e}), retry in {2**attempt}s")
                time.sleep(2 ** attempt)

        while not self._stop.is_set():
            # ── Drain up to BATCH_SIZE readings within BATCH_MAX_WAIT seconds ─
            batch: list[NormalizedReading] = []
            deadline = time.monotonic() + BATCH_MAX_WAIT

            while len(batch) < BATCH_SIZE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    reading = self.queue.get(timeout=min(remaining, 0.05))
                    if reading.quality == "good":
                        batch.append(reading)
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        break

            if not batch:
                continue

            # ── Redis write ───────────────────────────────────────────────────
            if self._redis is not None:
                try:
                    self._write_redis(batch)
                except Exception as e:
                    log.error(f"[publisher] Redis write failed: {e}")
                    try:
                        self._connect_redis()
                    except Exception:
                        pass

            # ── Postgres write ────────────────────────────────────────────────
            if self._pg is not None:
                try:
                    self._write_pg(batch)
                except Exception as e:
                    log.error(f"[publisher] Postgres write failed: {e}")
                    try:
                        self._pg.rollback()
                        self._connect_pg()
                    except Exception:
                        pass

            log.debug(f"[publisher] flushed {len(batch)} reading(s)")
