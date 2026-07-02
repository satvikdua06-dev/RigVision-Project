"""Runtime threshold resolution for the anomaly detector.

Resolves, for every sensor in cad/zone_definitions.json, the warning/critical
limits that should govern it — preferring manual-derived ThresholdSpecs from
the Neo4j knowledge graph over the temporary hardcoded values in the JSON.

Selection priority per sensor:
  1. device_manual   — the sensor is attached to a device (HAS_SENSOR) and that
                       device has a manual-derived ThresholdSpec for the sensor type
  2. zone_environmental — a zone-scope (HSE standard) ThresholdSpec for the
                       sensor type applies to the sensor's zone
  3. zone_definitions_fallback — the legacy warning/critical numbers from
                       cad/zone_definitions.json

The resolved table is cached (the graph only changes when re-seeded); call
refresh() or POST /api/thresholds/refresh after re-running seed_graph.py.
Neo4j being unreachable is not fatal — everything falls back to level 3.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("rigvision.threshold_resolver")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "rigvision_neo4j")

DEVICE_THRESHOLD_QUERY = """
MATCH (d:Device)-[:HAS_SENSOR]->(s:Sensor)
MATCH (d)-[:HAS_THRESHOLD]->(t:ThresholdSpec {sensor_type: s.type})
OPTIONAL MATCH (m:Manual)-[:DEFINES_THRESHOLD]->(t)
RETURN s.id AS sensor_id, d.id AS device_id, d.name AS device_name,
       t.id AS threshold_id, t.metric AS metric, t.unit AS unit,
       t.normal_min AS normal_min, t.normal_max AS normal_max,
       t.warning_min AS warning_min, t.critical_min AS critical_min,
       t.operating_mode AS operating_mode, t.source_section AS source_section,
       t.confidence AS confidence, t.validated_by_human AS validated_by_human,
       m.title AS manual_title
"""

ZONE_THRESHOLD_QUERY = """
MATCH (z:Zone)-[:HAS_ENV_THRESHOLD]->(t:ThresholdSpec)
OPTIONAL MATCH (m:Manual)-[:DEFINES_THRESHOLD]->(t)
RETURN z.id AS kg_zone_id, t.sensor_type AS sensor_type,
       t.id AS threshold_id, t.metric AS metric, t.unit AS unit,
       t.normal_min AS normal_min, t.normal_max AS normal_max,
       t.warning_min AS warning_min, t.critical_min AS critical_min,
       t.operating_mode AS operating_mode, t.source_section AS source_section,
       t.confidence AS confidence, t.validated_by_human AS validated_by_human,
       m.title AS manual_title
"""


class ThresholdResolver:
    def __init__(self, zone_defs_path: str, zone_to_kg: Dict[str, str]):
        self._zone_defs_path = zone_defs_path
        self._zone_to_kg = zone_to_kg
        self._lock = threading.Lock()
        self._table: Optional[Dict[str, dict]] = None
        self._kg_available = False
        self._resolved_at: Optional[float] = None

    # ── public API ────────────────────────────────────────────────────────

    def get_table(self) -> Dict[str, dict]:
        """sensor_id -> resolved threshold record (cached, thread-safe)."""
        with self._lock:
            if self._table is None:
                self._table = self._build_table()
                self._resolved_at = time.time()
            return self._table

    def refresh(self) -> Dict[str, dict]:
        with self._lock:
            self._table = self._build_table()
            self._resolved_at = time.time()
            return self._table

    def status(self) -> dict:
        return {
            "kg_available": self._kg_available,
            "resolved_at": self._resolved_at,
            "sensor_count": len(self._table) if self._table else 0,
        }

    # ── internals ─────────────────────────────────────────────────────────

    def _load_zone_defs(self) -> dict:
        with open(self._zone_defs_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _query_kg(self):
        """Returns (device_specs: {sensor_id: row}, zone_specs: {(kg_zone, type): row})
        or (None, None) if Neo4j is unreachable."""
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            try:
                driver.verify_connectivity()
                with driver.session() as session:
                    device_specs = {r["sensor_id"]: dict(r) for r in session.run(DEVICE_THRESHOLD_QUERY)}
                    zone_specs = {
                        (r["kg_zone_id"], r["sensor_type"]): dict(r)
                        for r in session.run(ZONE_THRESHOLD_QUERY)
                    }
                return device_specs, zone_specs
            finally:
                driver.close()
        except Exception as e:
            logger.warning("Neo4j unavailable for threshold resolution (%s) — "
                           "falling back to zone_definitions.json for all sensors.", e)
            return None, None

    def _build_table(self) -> Dict[str, dict]:
        zone_defs = self._load_zone_defs()["zones"]
        device_specs, zone_specs = self._query_kg()
        self._kg_available = device_specs is not None

        table: Dict[str, dict] = {}
        counts = {"device_manual": 0, "zone_environmental": 0, "zone_definitions_fallback": 0}

        for rig_zone_id, zdef in zone_defs.items():
            kg_zone = self._zone_to_kg.get(rig_zone_id, rig_zone_id)
            for s in zdef.get("sensors", []):
                resolved = None
                if device_specs and s["id"] in device_specs:
                    resolved = self._from_kg_row(device_specs[s["id"]], s, rig_zone_id,
                                                 level="device_manual", priority=1)
                elif zone_specs and (kg_zone, s["type"]) in zone_specs:
                    resolved = self._from_kg_row(zone_specs[(kg_zone, s["type"])], s, rig_zone_id,
                                                 level="zone_environmental", priority=2)
                if resolved is None:
                    resolved = self._fallback(s, rig_zone_id)
                counts[resolved["source_level"]] += 1
                table[s["id"]] = resolved

        logger.info("Threshold table resolved: %d sensors (%s).", len(table),
                    ", ".join(f"{k}={v}" for k, v in counts.items()))
        return table

    @staticmethod
    def _from_kg_row(row: dict, sensor: dict, rig_zone_id: str, level: str, priority: int) -> dict:
        if level == "device_manual":
            reason = (f"Device-specific limit: sensor '{sensor['id']}' is mounted on "
                      f"{row.get('device_name')} ({row.get('metric')}), defined by "
                      f"'{row.get('manual_title')}'")
        else:
            reason = (f"Zone environmental limit for {sensor['type']} ({row.get('metric')}), "
                      f"defined by '{row.get('manual_title')}'")
        return {
            "sensor_id": sensor["id"],
            "sensor_type": sensor["type"],
            "rig_zone_id": rig_zone_id,
            "unit": row.get("unit") or sensor.get("unit", ""),
            "normal_range": [row.get("normal_min"), row.get("normal_max")],
            "warning": row.get("warning_min"),
            "critical": row.get("critical_min"),
            "threshold_id": row.get("threshold_id"),
            "metric": row.get("metric"),
            "operating_mode": row.get("operating_mode"),
            "device_id": row.get("device_id"),
            "device_name": row.get("device_name"),
            "source_manual": row.get("manual_title"),
            "source_section": row.get("source_section"),
            "confidence": row.get("confidence"),
            "validated_by_human": row.get("validated_by_human"),
            "source_level": level,
            "priority": priority,
            "selection_reason": reason,
        }

    @staticmethod
    def _fallback(sensor: dict, rig_zone_id: str) -> dict:
        return {
            "sensor_id": sensor["id"],
            "sensor_type": sensor["type"],
            "rig_zone_id": rig_zone_id,
            "unit": sensor.get("unit", ""),
            "normal_range": sensor.get("normal_range"),
            "warning": sensor.get("warning"),
            "critical": sensor.get("critical"),
            "threshold_id": None,
            "metric": None,
            "operating_mode": None,
            "device_id": None,
            "device_name": None,
            "source_manual": "cad/zone_definitions.json (temporary fallback)",
            "source_section": None,
            "confidence": None,
            "validated_by_human": False,
            "source_level": "zone_definitions_fallback",
            "priority": 3,
            "selection_reason": "No manual-derived threshold available; using the "
                                "temporary hardcoded limit from zone_definitions.json",
        }
