"""RigVision-3D — Zone assignment + sensor fusion (shared).

Used by:
  - pipeline.py (demo mode) to build zone states directly.
  - location_service.py to assign zones to triangulated persons and fuse sensors.

Sensor values come from the seam `rigvision:sensors:latest` (written by the Sensor
Console now, MQTT bridge later). Manual readings never expire; live readings expire
after SENSOR_STALE_SECONDS.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional, Tuple

import redis

CANONICAL_SENSOR_TYPES = ("temperature", "vibration", "noise", "gas_h2s", "pressure")
SENSOR_STALE_SECONDS = float(os.getenv("SENSOR_STALE_SECONDS", "10"))
SENSORS_KEY = "rigvision:sensors:latest"
# Resolved per-sensor thresholds, published by the backend (ThresholdResolver:
# device manual → zone environmental → zone_definitions fallback). Using them here
# keeps zone coloring consistent with what the anomaly detector enforces.
RESOLVED_THRESHOLDS_KEY = "rigvision:thresholds:resolved"
DEFAULT_PPE = {"hardhat": None, "vest": None, "goggles": None}
_SEVERITY = {"normal": 0, "warning": 1, "critical": 2}


def load_zone_definitions(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def assign_zone(position_3d: Optional[Tuple[float, float, float]], zone_defs: dict) -> str:
    """Return the zone id whose bounding box contains the 3D point, else 'unknown'."""
    if position_3d is None:
        return "unknown"
    x, y, z = position_3d
    for zid, zdef in zone_defs["zones"].items():
        b = zdef.get("bounds")
        if not b:
            continue
        mn, mx = b["min"], b["max"]
        if mn["x"] <= x <= mx["x"] and mn["y"] <= y <= mx["y"] and mn["z"] <= z <= mx["z"]:
            return zid
    return "unknown"


def read_sensor_readings(redis_client: redis.Redis) -> dict:
    """Read the sensor seam (rigvision:sensors:latest)."""
    try:
        raw = redis_client.get(SENSORS_KEY)
        return json.loads(raw) if raw else {}
    except Exception as e:
        print(f"[sensors] read error: {e}")
        return {}


def read_resolved_thresholds(redis_client: redis.Redis) -> dict:
    """Read the backend-published resolved threshold table ({sensor_id: limits}).
    Empty dict if the backend hasn't published yet → zone_definitions values apply."""
    try:
        raw = redis_client.get(RESOLVED_THRESHOLDS_KEY)
        return json.loads(raw) if raw else {}
    except Exception as e:
        print(f"[thresholds] read error: {e}")
        return {}


def _sensor_limits(s: dict, resolved_thresholds: dict) -> tuple:
    """(warning, critical, normal_range) for a sensor — resolved table first,
    zone_definitions fallback otherwise."""
    t = resolved_thresholds.get(s["id"])
    if t:
        nr = t.get("normal_range")
        if not nr or nr[0] is None:
            nr = s.get("normal_range")
        return t.get("warning"), t.get("critical"), nr
    return s.get("warning"), s.get("critical"), s.get("normal_range")


def build_zone_states(persons: list[dict], sensor_readings: dict, zone_defs: dict,
                      resolved_thresholds: dict | None = None) -> dict:
    """Fuse live sensor readings + person occupancy/PPE into per-zone state.

    Sensor values are validated for freshness (manual = never stale, others expire after
    SENSOR_STALE_SECONDS). Multiple sensors of one type aggregate worst-case (max). Zone
    status escalates from sensor thresholds, PPE violations, and occupancy.
    """
    now = time.time()
    resolved_thresholds = resolved_thresholds or {}
    states: dict = {}
    for zid, zdef in zone_defs["zones"].items():
        z_pers = [p for p in persons if p["zone"] == zid]
        ppe_viol = []
        for p in z_pers:
            ppe = p.get("ppe", {})
            if ppe.get("hardhat") is False:
                ppe_viol.append(f"Person #{p['id']} missing hard hat")
            if ppe.get("vest") is False:
                ppe_viol.append(f"Person #{p['id']} missing vest")

        by_type: dict[str, list[float]] = {t: [] for t in CANONICAL_SENSOR_TYPES}
        status, reason = "normal", None

        for s in zdef.get("sensors", []):
            reading = sensor_readings.get(s["id"])
            value = None
            if reading is not None:
                v = reading.get("value")
                if v is not None:
                    is_manual = reading.get("source") == "manual"
                    fresh = is_manual or (now - reading.get("updated_at", 0)) <= SENSOR_STALE_SECONDS
                    if fresh:
                        value = float(v)
            if value is None:
                continue

            stype = s["type"]
            if stype in by_type:
                by_type[stype].append(value)

            warn, crit, _ = _sensor_limits(s, resolved_thresholds)
            unit = s.get("unit", "")
            if crit is not None and value >= crit and _SEVERITY["critical"] > _SEVERITY[status]:
                status, reason = "critical", f"{stype} {value:.1f}{unit} >= critical ({crit}) [{s['id']}]"
            elif warn is not None and value >= warn and _SEVERITY["warning"] > _SEVERITY[status]:
                status, reason = "warning", f"{stype} {value:.1f}{unit} >= warning ({warn}) [{s['id']}]"

        if ppe_viol and _SEVERITY["warning"] > _SEVERITY[status]:
            status, reason = "warning", f"{len(ppe_viol)} PPE violation(s)"
        max_occ = zdef.get("max_occupancy", 99)
        if len(z_pers) > max_occ and _SEVERITY["critical"] > _SEVERITY[status]:
            status, reason = "critical", f"Overcrowded: {len(z_pers)}/{max_occ} persons"

        agg = {t: (round(max(by_type[t]), 2) if by_type[t] else None) for t in CANONICAL_SENSOR_TYPES}

        # Per-type display metadata so the frontend colors/scales bars identically to
        # the Sensor Console (same thresholds + bounds, single source of truth).
        sensor_meta: dict = {}
        for s in zdef.get("sensors", []):
            warn, crit, normal_range = _sensor_limits(s, resolved_thresholds)
            lo, hi = (normal_range or [0, 100])[:2]
            top = crit * 1.2 if crit is not None else hi * 1.5
            t = resolved_thresholds.get(s["id"])
            source_meta = None
            if t:
                source_meta = {
                    "level": t.get("source_level"),
                    "manual": t.get("source_manual"),
                    "device": t.get("device_name"),
                    "reason": t.get("selection_reason"),
                }
            sensor_meta[s["type"]] = {
                "warning": warn, "critical": crit,
                "min": lo, "max": max(top, hi), "unit": s.get("unit", ""),
                "threshold_source": source_meta,
            }

        states[zid] = {
            "status": status, "warning_reason": reason,
            "label": zdef.get("name", zid),
            "floor": zdef.get("floor", 0),
            "sensor_types": sorted({s["type"] for s in zdef.get("sensors", [])}),
            "sensor_meta": sensor_meta,
            "temperature": agg["temperature"], "vibration": agg["vibration"],
            "noise": agg["noise"], "gas_h2s": agg["gas_h2s"], "pressure": agg["pressure"],
            "person_count": len(z_pers), "ppe_violations": ppe_viol, "updated_at": int(time.time()),
        }
    return states
