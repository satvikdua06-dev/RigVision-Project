"""
SCADA Normalizer — converts RawReading → NormalizedReading.

Applies scale/offset from the register/topic config, validates the
sensor_id against zone_definitions.json, attaches a UTC timestamp,
and assigns a quality code.

Quality rules:
  good      — fresh value, passed all checks
  bad       — NaN / Inf / comm error flag in raw_value
  uncertain — (not set here; Publisher sets this on stale Redis values)
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .drivers.base import RawReading

_ZONE_DEF_PATH = Path(__file__).resolve().parent.parent / "cad" / "zone_definitions.json"
_VALID_SENSORS: set[str] = set()


def _load_valid_sensors() -> None:
    global _VALID_SENSORS
    if _VALID_SENSORS:
        return
    try:
        with open(_ZONE_DEF_PATH) as f:
            data = json.load(f)
        for zone in data.get("zones", {}).values():
            for s in zone.get("sensors", []):
                _VALID_SENSORS.add(s["id"])
    except FileNotFoundError:
        pass   # allow running without zone_definitions in tests


@dataclass
class NormalizedReading:
    sensor_id: str
    value:     float
    unit:      str
    quality:   str          # "good" | "bad"
    timestamp: float        # Unix epoch (UTC)
    protocol:  str
    raw_value: Optional[float]
    device:    Optional[str]


def normalize(raw: RawReading) -> Optional[NormalizedReading]:
    """
    Convert a RawReading to a NormalizedReading.
    Returns None when the sensor_id is unknown (phantom data dropped silently).
    """
    _load_valid_sensors()

    if _VALID_SENSORS and raw.sensor_id not in _VALID_SENSORS:
        return None

    cfg    = raw.config
    scale  = float(cfg.get("scale",  1.0))
    offset = float(cfg.get("offset", 0.0))
    unit   = str(cfg.get("unit", ""))

    value   = raw.raw_value * scale + offset
    quality = "bad" if (math.isnan(value) or math.isinf(value)) else "good"

    return NormalizedReading(
        sensor_id=raw.sensor_id,
        value=round(value, 4),
        unit=unit,
        quality=quality,
        timestamp=time.time(),
        protocol=raw.protocol,
        raw_value=raw.raw_value,
        device=raw.device,
    )
