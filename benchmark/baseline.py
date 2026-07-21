"""Single-sensor threshold baseline -- the control arm of the benchmark.

This models a conventional SCADA/DCS alarm: each sensor is compared against its
own configured bound, in isolation, with no knowledge of permits, maintenance
state, PPE or shift context.

The baseline is deliberately given every advantage so the comparison is
conservative rather than flattering:

  * It alarms at the WARNING bound, not the critical bound. Alarming earlier
    can only improve its lead time and its recall.
  * It reads the SAME thresholds from cad/zone_definitions.json that the rest of
    the platform uses, so it is not being handicapped with stale numbers.
  * It fires on ANY sensor breaching, so it has maximum opportunity to detect.

Anything the compound engine wins after that is a real win.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

ZONE_DEFS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cad", "zone_definitions.json",
)

_limits_cache: Optional[dict] = None


def limits() -> dict:
    """Sensor-type -> bounds, merged across zones. Same source as the console."""
    global _limits_cache
    if _limits_cache is not None:
        return _limits_cache
    merged: dict = {}
    with open(ZONE_DEFS_PATH, "r", encoding="utf-8") as fh:
        defs = json.load(fh)
    for zone in (defs.get("zones") or {}).values():
        for s in zone.get("sensors", []):
            t = s.get("type")
            if not t:
                continue
            merged.setdefault(t, {})
            for k in ("warning", "critical", "warning_low", "critical_low"):
                if s.get(k) is not None:
                    merged[t][k] = s[k]
    _limits_cache = merged
    return merged


# Map SCADA sensor id prefix -> sensor type in zone_definitions.json
_ID_TO_TYPE = {
    "gas": "gas_h2s",
    "temp": "temperature",
    "vib": "vibration",
    "noise": "noise",
    "pressure": "pressure",
}


def _sensor_type(sensor_id: str) -> Optional[str]:
    for prefix, stype in _ID_TO_TYPE.items():
        if sensor_id.startswith(prefix):
            return stype
    return None


def evaluate(sensors: Dict[str, dict]) -> List[str]:
    """Return a list of breach descriptions. Empty list == no alarm.

    Deliberately ignores permits / maintenance / PPE / shift -- that blindness
    is the property being measured.
    """
    breaches: List[str] = []
    lim = limits()

    for sid, reading in sorted(sensors.items()):
        if not reading:
            continue
        try:
            val = float(reading.get("value"))
        except (TypeError, ValueError):
            continue

        stype = _sensor_type(sid)
        if not stype:
            continue
        bounds = lim.get(stype, {})
        if not bounds:
            continue

        warn = bounds.get("warning")
        warn_low = bounds.get("warning_low")

        if warn is not None and val >= warn:
            breaches.append(f"{sid}={val} >= warning {warn}")
        elif warn_low is not None and val <= warn_low:
            breaches.append(f"{sid}={val} <= low warning {warn_low}")

    return breaches
