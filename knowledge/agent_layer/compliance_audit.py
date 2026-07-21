"""Quality & Compliance Audit Agent.

Every AUDIT_POLL_INTERVAL seconds:
  1. Reads live rig state from Redis (sensors, permits, shift, maintenance, PPE)
  2. Deterministically checks each OISD/DGMS/Factory Act rule
  3. Computes a 0-100 compliance score (deductions per violation severity)
  4. Calls Gemini to generate corrective action workflow narrative
  5. Writes full audit report to rigvision:compliance_audit:latest

Flags deviations BEFORE they escalate - complementary to the compound risk engine
which triggers only on active multi-sensor combinations.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import redis
import requests

log = logging.getLogger("compliance_audit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

REDIS_URL          = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",   "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct-1m")
AUDIT_POLL_INTERVAL = float(os.getenv("AUDIT_POLL_INTERVAL", "300"))

COMPLIANCE_AUDIT_KEY = "rigvision:compliance_audit:latest"

SENSORS_KEY     = "rigvision:sensors:latest"   # Redis Hash (hgetall)
PERSONS_KEY     = "rigvision:persons"
PPE_KEY         = "rigvision:ppe:latest"
PERMITS_KEY     = "rigvision:permits:active"
SHIFT_KEY       = "rigvision:shift:current"
MAINTENANCE_KEY = "rigvision:maintenance:active"

SCORE_DEDUCTIONS = {"CRITICAL": 25, "HIGH": 10, "MEDIUM": 5}

# Sensor limits come from cad/zone_definitions.json -- the same file the sensor
# console, heatmap and anomaly evaluator read. This module previously carried its
# own hardcoded numbers, which meant a reading could show NORMAL on the console
# while raising a HIGH compliance violation here.
ZONE_DEFS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cad", "zone_definitions.json",
)

# Fallback used only if zone_definitions.json cannot be read.
_FALLBACK_LIMITS = {
    "gas_h2s":     {"warning": 10, "critical": 15},
    "temperature": {"warning": 50, "critical": 65},
    "vibration":   {"warning": 5,  "critical": 8},
    "noise":       {"warning": 95, "critical": 105},
    "pressure":    {"warning": 20, "critical": 25, "warning_low": 4, "critical_low": 2},
}

_limits_cache: Optional[dict] = None


def _limits() -> dict:
    """Per-sensor-type limits keyed by type, merged across zones (widest wins)."""
    global _limits_cache
    if _limits_cache is not None:
        return _limits_cache
    merged: dict = {}
    try:
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
        if not merged:
            raise ValueError("no sensors in zone_definitions.json")
    except Exception as e:
        log.warning("Could not read zone_definitions.json (%s); using fallback limits", e)
        merged = dict(_FALLBACK_LIMITS)
    _limits_cache = merged
    return merged


def _lim(sensor_type: str, bound: str, default=None):
    return _limits().get(sensor_type, {}).get(bound, default)


@dataclass
class Violation:
    code: str
    standard: str
    clause: str
    severity: str             # CRITICAL | HIGH | MEDIUM
    description: str
    current_value: Optional[str] = None
    threshold: Optional[str] = None
    corrective_action: str = ""


def _get_state(r: redis.Redis) -> dict:
    def _load(key):
        raw = r.get(key)
        return json.loads(raw) if raw else None

    # sensors:latest is a Redis Hash (hset per sensor-id); parse each field value as JSON
    sensors_hash = r.hgetall(SENSORS_KEY)
    sensors = {k: json.loads(v) for k, v in sensors_hash.items()} if sensors_hash else {}

    permits_raw = _load(PERMITS_KEY)
    permits = permits_raw if isinstance(permits_raw, list) else []

    shift_raw = _load(SHIFT_KEY)
    shift = shift_raw if isinstance(shift_raw, dict) else {}

    maint_raw = _load(MAINTENANCE_KEY)
    maintenance = maint_raw if isinstance(maint_raw, list) else []

    ppe_raw = _load(PPE_KEY)
    ppe = ppe_raw if isinstance(ppe_raw, dict) else {}

    persons_raw = _load(PERSONS_KEY)
    persons = persons_raw if isinstance(persons_raw, list) else []

    return {
        "sensors":     sensors,
        "permits":     permits,
        "shift":       shift,
        "maintenance": maintenance,
        "ppe":         ppe,
        "persons":     persons,
    }


def _sv(sensors: dict, key: str) -> Optional[float]:
    v = sensors.get(key)
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _check_compliance(state: dict) -> List[Violation]:
    violations: List[Violation] = []
    sensors     = state["sensors"]
    permits     = [p for p in state["permits"]     if p.get("status") == "active"]
    shift       = state["shift"]
    maintenance = [m for m in state["maintenance"] if m.get("status") == "in_progress"]
    ppe         = state["ppe"]

    # Sensor fields use SCADA IDs (e.g. gas_a/gas_b); take worst-case across zones
    def _svmax(*keys):
        vals = [_sv(sensors, k) for k in keys]
        valid = [v for v in vals if v is not None]
        return max(valid) if valid else None

    gas   = _svmax("gas_a",  "gas_b")
    temp  = _svmax("temp_a", "temp_b")
    pres  = _sv(sensors, "pressure_a")
    vib   = _sv(sensors, "vib_a")
    noise = _sv(sensors, "noise_a")

    hot_work_permits = [p for p in permits if p.get("type") == "hot_work"]
    confined_permits = [p for p in permits if p.get("type") == "confined_space"]
    is_night         = shift.get("shift") == "night"
    is_reduced       = shift.get("is_reduced_crew", False)
    crew_size        = int(shift.get("crew_size", 99))

    # â”€â”€ C001: OISD-105 Cl.4.2 - hot work gas limit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if hot_work_permits and gas is not None:
        for p in hot_work_permits:
            limit = float(p.get("gas_clear_ppm", 5.0))
            if gas >= limit:
                violations.append(Violation(
                    code="C001", standard="OISD-105", clause="Cl.4.2",
                    severity="CRITICAL",
                    description=f"H2S ({gas:.1f} ppm) at or above hot-work gas-clear threshold ({limit} ppm) while permit {p['permit_id']} is active.",
                    current_value=f"{gas:.1f} ppm H2S",
                    threshold=f"< {limit} ppm",
                    corrective_action="Suspend hot work immediately. Re-test atmosphere every 30 min. Resume only when gas < threshold for two consecutive readings.",
                ))

    # â”€â”€ C002/C003: OISD-GDN-192 Cl.4 - H2S action levels â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    gas_crit, gas_warn = _lim("gas_h2s", "critical"), _lim("gas_h2s", "warning")
    if gas is not None:
        if gas_crit is not None and gas >= gas_crit:
            violations.append(Violation(
                code="C002", standard="OISD-GDN-192", clause="Cl.4 AL3",
                severity="CRITICAL",
                description=f"H2S at Action Level 3 ({gas:.1f} ppm >= {gas_crit} ppm). Full area evacuation mandatory. SCBA required for all entrants.",
                current_value=f"{gas:.1f} ppm", threshold=f"< {gas_crit} ppm",
                corrective_action="Sound site siren. All personnel move upwind to muster point within 10 min. Account for all workers. Notify DGMS. Do not re-enter without SCBA.",
            ))
        elif gas_warn is not None and gas >= gas_warn:
            violations.append(Violation(
                code="C003", standard="OISD-GDN-192", clause="Cl.4 AL2",
                severity="HIGH",
                description=f"H2S at Action Level 2 ({gas:.1f} ppm >= {gas_warn} ppm). Non-essential personnel must evacuate upwind.",
                current_value=f"{gas:.1f} ppm", threshold=f"< {gas_warn} ppm",
                corrective_action="Evacuate non-essential personnel upwind. Essential workers don SCBA. Identify and isolate H2S source. Log readings every 15 min.",
            ))

    # â”€â”€ C004/C005: OISD-116 Cl.5.3 - pump vibration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    vib_crit, vib_warn = _lim("vibration", "critical"), _lim("vibration", "warning")
    if vib is not None:
        if vib_crit is not None and vib >= vib_crit:
            violations.append(Violation(
                code="C004", standard="OISD-116", clause="Cl.5.3",
                severity="CRITICAL",
                description=f"Mud pump vibration ({vib:.2f} g_rms) exceeds shutdown threshold ({vib_crit} g_rms). Catastrophic bearing failure risk.",
                current_value=f"{vib:.2f} g_rms", threshold=f"< {vib_crit} g_rms",
                corrective_action="Shut down mud pump immediately. Do not restart until mechanical inspection confirms bearing integrity.",
            ))
        elif vib_warn is not None and vib >= vib_warn:
            violations.append(Violation(
                code="C005", standard="OISD-116", clause="Cl.5.3",
                severity="HIGH",
                description=f"Mud pump vibration ({vib:.2f} g_rms) above alert threshold ({vib_warn} g_rms).",
                current_value=f"{vib:.2f} g_rms", threshold=f"< {vib_warn} g_rms",
                corrective_action="Alert maintenance. Monitor every 5 min. Prepare for shutdown if trend continues upward.",
            ))

    # â”€â”€ C006/C007/C008: OISD-118 Cl.6.1 - temperature limits â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # zone_definitions.json defines two bounds per sensor, so the old three-tier
    # temperature ladder (95/85/80) collapses to critical/warning. C006 is retired.
    temp_crit, temp_warn = _lim("temperature", "critical"), _lim("temperature", "warning")
    if temp is not None:
        if temp_crit is not None and temp >= temp_crit:
            violations.append(Violation(
                code="C007", standard="OISD-118", clause="Cl.6.1",
                severity="CRITICAL",
                description=f"Temperature ({temp:.1f} C) at or above the critical limit ({temp_crit} C). Cooling system failure, excessive friction or hydrocarbon ignition risk.",
                current_value=f"{temp:.1f} C", threshold=f"< {temp_crit} C",
                corrective_action="Shutdown equipment. Activate emergency cooling. Inspect for vapour ignition risk. Root-cause confirmation before restart.",
            ))
        elif temp_warn is not None and temp >= temp_warn:
            violations.append(Violation(
                code="C008", standard="OISD-118", clause="Cl.6.1",
                severity="HIGH",
                description=f"Temperature ({temp:.1f} C) above normal operating limit ({temp_warn} C). Increased monitoring required.",
                current_value=f"{temp:.1f} C", threshold=f"< {temp_warn} C",
                corrective_action="Increase monitoring frequency. Inspect cooling system. Notify operations supervisor.",
            ))

    # â”€â”€ C009: OISD-118 Cl.5.2 - high temp + low pressure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    pres_low = _lim("pressure", "warning_low")
    if (temp is not None and pres is not None and temp_crit is not None
            and pres_low is not None and temp >= temp_crit and pres <= pres_low):
        violations.append(Violation(
            code="C009", standard="OISD-118", clause="Cl.5.2",
            severity="CRITICAL",
            description=f"Simultaneous high temperature ({temp:.1f} C) and low pressure ({pres:.1f} bar) - potential seal/gasket failure. Treat as hydrocarbon release emergency.",
            current_value=f"Temp={temp:.1f} C, Pres={pres:.1f} bar",
            threshold=f"Temp < {temp_crit} C OR Pres > {pres_low} bar",
            corrective_action="Evacuate zone. Isolate process. Treat as hydrocarbon release until investigation confirms otherwise. Notify DGMS within 2 hours.",
        ))

    # â”€â”€ C010: OISD-105 Cl.5.1 - confined space gas limit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if confined_permits and gas is not None and gas >= 1.0:
        violations.append(Violation(
            code="C010", standard="OISD-105", clause="Cl.5.1",
            severity="CRITICAL",
            description=f"H2S ({gas:.1f} ppm) exceeds confined space TWA limit (1 ppm) with active confined space entry permit.",
            current_value=f"{gas:.1f} ppm", threshold="< 1 ppm TWA",
            corrective_action="Withdraw ALL workers from confined space immediately. Re-test atmosphere. Provide SCBA if re-entry required. Standby rescue team must be positioned at entry point.",
        ))

    # â”€â”€ C011: OISD-116 Cl.3.1 - night shift minimum crew â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if is_night and (is_reduced or crew_size < 5):
        violations.append(Violation(
            code="C011", standard="OISD-116", clause="Cl.3.1",
            severity="HIGH",
            description=f"Night shift crew below minimum (crew={crew_size}, reduced={is_reduced}). Minimum: Driller + 3 roughnecks + 1 derrickman + senior supervisor on-site.",
            current_value=f"Crew: {crew_size}", threshold=">= 5 + senior supervisor",
            corrective_action="Halt non-essential operations. Call in additional crew. Document reduced-crew approval from Installation Manager before continuing critical operations.",
        ))

    # â”€â”€ C012: OISD-105 Cl.7.3 - LOTO isolation unconfirmed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for m in maintenance:
        if not m.get("isolation_confirmed", True):
            violations.append(Violation(
                code="C012", standard="OISD-105", clause="Cl.7.3",
                severity="CRITICAL",
                description=f"Maintenance job {m.get('maintenance_id','?')} ({m.get('description','?')}) in-progress with unconfirmed LOTO isolation.",
                current_value="isolation_confirmed=False",
                threshold="isolation_confirmed=True",
                corrective_action="Stop all work on this equipment immediately. Verify ALL energy isolation points. Apply physical locks and tags. Attempt start to confirm de-energisation before resuming.",
            ))

    # â”€â”€ C013: Factory Act Â§36 - PPE compliance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if ppe.get("person_present"):
        missing = [item for item in ["hat", "glasses"] if ppe.get(item) == "missing"]
        if missing:
            violations.append(Violation(
                code="C013", standard="Factory Act", clause="Â§36",
                severity="HIGH",
                description=f"PPE violation detected in operational area: {', '.join(missing)} missing.",
                current_value=f"Missing: {', '.join(missing)}",
                threshold="Full PPE at all times",
                corrective_action="Direct worker to don required PPE immediately. Worker must leave operational area until PPE is worn correctly. Supervisor to be notified within 5 minutes.",
            ))

    # â”€â”€ C014: DGMS 3/2016 Cl.5 - SIMOPS (hot work + confined space) â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if hot_work_permits and confined_permits:
        violations.append(Violation(
            code="C014", standard="DGMS 3/2016", clause="Cl.5",
            severity="CRITICAL",
            description="Hot work and confined space entry permits are simultaneously active. SIMOPS risk assessment has not been documented.",
            current_value="Both permit types active concurrently",
            threshold="Explicit SIMOPS RA required",
            corrective_action="Suspend one operation. Site Safety Officer must complete SIMOPS risk assessment. Minimum 15m separation required or physical barriers before both can proceed.",
        ))

    # â”€â”€ C015: OISD-116 Cl.4 - multi-hazard no formal assessment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Counts sensors at or past their configured warning bound -- the same point
    # the console turns a reading amber.
    anomalous_count = sum([
        1 if (gas  is not None and gas_warn  is not None and gas  >= gas_warn)  else 0,
        1 if (temp is not None and temp_warn is not None and temp >= temp_warn) else 0,
        1 if (vib  is not None and vib_warn  is not None and vib  >= vib_warn)  else 0,
        1 if (pres is not None and pres_low  is not None and pres <= pres_low)  else 0,
    ])
    if anomalous_count >= 2:
        violations.append(Violation(
            code="C015", standard="OISD-116", clause="Cl.4",
            severity="HIGH",
            description=f"{anomalous_count} simultaneous abnormal sensor conditions detected. OISD-116 requires a formal multi-hazard risk assessment when two or more independent hazardous conditions are present.",
            current_value=f"{anomalous_count} abnormal parameters",
            threshold="< 2 simultaneous hazardous conditions OR formal MHRA documented",
            corrective_action="Conduct formal multi-hazard risk assessment immediately. Increase monitoring frequency. Obtain Installation Manager approval to continue operations.",
        ))

    return violations


def get_code_registry() -> List[dict]:
    """Reference metadata for the COMPLIANCE CODE LEGEND UI.

    Trigger text is built from the SAME _lim() lookup the checks above use, so
    the legend can't drift out of sync with zone_definitions.json the way a
    hand-written description would.
    """
    gc, gw = _lim("gas_h2s", "critical"), _lim("gas_h2s", "warning")
    vc, vw = _lim("vibration", "critical"), _lim("vibration", "warning")
    tc, tw = _lim("temperature", "critical"), _lim("temperature", "warning")
    pl = _lim("pressure", "warning_low")

    return [
        {"code": "C001", "severity": "CRITICAL", "standard": "OISD-105 Cl.4.2",
         "title": "Hot Work Gas-Clear Breach",
         "trigger": "Hot-work permit active and H2S at/above that permit's gas-clear threshold."},
        {"code": "C002", "severity": "CRITICAL", "standard": "OISD-GDN-192 Cl.4",
         "title": "H2S Action Level 3",
         "trigger": f"H2S >= {gc} ppm -- full area evacuation, SCBA required."},
        {"code": "C003", "severity": "HIGH", "standard": "OISD-GDN-192 Cl.4",
         "title": "H2S Action Level 2",
         "trigger": f"H2S >= {gw} ppm -- non-essential personnel evacuate upwind."},
        {"code": "C004", "severity": "CRITICAL", "standard": "OISD-116 Cl.5.3",
         "title": "Mud Pump Vibration Shutdown",
         "trigger": f"Vibration >= {vc} g_rms -- bearing failure risk, shut down."},
        {"code": "C005", "severity": "HIGH", "standard": "OISD-116 Cl.5.3",
         "title": "Mud Pump Vibration Alert",
         "trigger": f"Vibration >= {vw} g_rms -- alert threshold."},
        {"code": "C007", "severity": "CRITICAL", "standard": "OISD-118 Cl.6.1",
         "title": "Critical Temperature",
         "trigger": f"Temperature >= {tc} C."},
        {"code": "C008", "severity": "HIGH", "standard": "OISD-118 Cl.6.1",
         "title": "Above Normal Temperature",
         "trigger": f"Temperature >= {tw} C -- above normal operating limit."},
        {"code": "C009", "severity": "CRITICAL", "standard": "OISD-118 Cl.5.2",
         "title": "High Temperature + Pressure Loss",
         "trigger": f"Temperature >= {tc} C and pressure <= {pl} bar at the same time -- possible seal/gasket failure."},
        {"code": "C010", "severity": "CRITICAL", "standard": "OISD-105 Cl.5.1",
         "title": "Confined Space Gas Limit",
         "trigger": "Confined-space permit active and H2S >= 1 ppm (TWA limit)."},
        {"code": "C011", "severity": "HIGH", "standard": "OISD-116 Cl.3.1",
         "title": "Night Shift Below Minimum Crew",
         "trigger": "Night shift with a reduced crew or fewer than 5 personnel on site."},
        {"code": "C012", "severity": "CRITICAL", "standard": "OISD-105 Cl.7.3",
         "title": "Unconfirmed LOTO Isolation",
         "trigger": "Maintenance job in progress with isolation not confirmed."},
        {"code": "C013", "severity": "HIGH", "standard": "Factory Act Sec.36",
         "title": "PPE Non-Compliance",
         "trigger": "Person present without required hard hat or safety glasses."},
        {"code": "C014", "severity": "CRITICAL", "standard": "DGMS 3/2016 Cl.5",
         "title": "SIMOPS Without Risk Assessment",
         "trigger": "Hot-work and confined-space permits active at the same time, no SIMOPS assessment recorded."},
        {"code": "C015", "severity": "HIGH", "standard": "OISD-116 Cl.4",
         "title": "Multi-Hazard Without Assessment",
         "trigger": "Two or more sensors simultaneously at/above their warning bound."},
    ]


def _compliance_score(violations: List[Violation]) -> int:
    score = 100
    for v in violations:
        score -= SCORE_DEDUCTIONS.get(v.severity, 5)
    return max(0, score)


def _call_gemini(prompt: str) -> str:
    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 500,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LM Studio call failed: %s", e)
        return f"Workflow narrative unavailable: {e}"


def _generate_workflow(violations: List[Violation], score: int) -> str:
    if not violations:
        return "All monitored parameters are within compliance thresholds. No corrective actions required."

    v_text = "\n".join(
        f"  [{v.code}] {v.severity} - {v.standard} {v.clause}: {v.description}\n"
        f"    Current: {v.current_value} | Threshold: {v.threshold}"
        for v in violations
    )
    prompt = f"""You are the RigVision Compliance Audit System generating a CORRECTIVE ACTION WORKFLOW for an remote drilling facility.

COMPLIANCE SCORE: {score}/100

ACTIVE VIOLATIONS:
{v_text}

Generate a prioritised corrective action workflow (max 350 words) that:
1. Sequences actions by time-to-harm (CRITICAL violations first)
2. Groups related actions to minimise operational disruption
3. Assigns responsibility: WHO must act (e.g., "Shift Supervisor", "Safety Officer", "Maintenance Team Lead", "Operations")
4. States realistic completion times: "Immediate (0-5 min)", "Short-term (5-30 min)", "Within shift"
5. Lists what must be documented for DGMS/Inspector of Factories regulatory compliance

Be directive and specific. The reader may be under time pressure."""

    return _call_gemini(prompt)


INITIAL_DELAY = 360  # seconds - wait 6 min at startup to stagger LM Studio load


def generate(r: redis.Redis, *, blocking: bool = False) -> dict:
    """Run one compliance audit pass and write it to Redis.

    Deterministic violations land in Redis immediately; the LM Studio narrative
    is filled in afterwards. With blocking=False the narrative is generated on a
    background thread (poll loop). With blocking=True the call waits for it --
    used by the manual GENERATE button so the caller gets a finished report.

    Returns the report dict as written.
    """
    import threading

    state      = _get_state(r)
    violations = _check_compliance(state)
    score      = _compliance_score(violations)

    result_base = {
        "generated_at":      int(time.time()),
        "compliance_score":  score,
        "violation_count":   len(violations),
        "critical_count":    sum(1 for v in violations if v.severity == "CRITICAL"),
        "high_count":        sum(1 for v in violations if v.severity == "HIGH"),
        "medium_count":      sum(1 for v in violations if v.severity == "MEDIUM"),
        "violations": [
            {
                "code":              v.code,
                "standard":          v.standard,
                "clause":            v.clause,
                "severity":          v.severity,
                "description":       v.description,
                "current_value":     v.current_value,
                "threshold":         v.threshold,
                "corrective_action": v.corrective_action,
            }
            for v in violations
        ],
        "corrective_workflow": "Generating...",
        "status": "generating",
    }
    r.set(COMPLIANCE_AUDIT_KEY, json.dumps(result_base))
    r.expire(COMPLIANCE_AUDIT_KEY, 86400)

    def _write_narrative(viols=violations, sc=score, base=dict(result_base)):
        base["corrective_workflow"] = _generate_workflow(viols, sc)
        base["status"] = "ready"
        r.set(COMPLIANCE_AUDIT_KEY, json.dumps(base))
        r.expire(COMPLIANCE_AUDIT_KEY, 86400)
        log.info("Compliance workflow narrative written.")
        return base

    if blocking:
        result = _write_narrative()
    else:
        threading.Thread(target=_write_narrative, daemon=True).start()
        result = result_base

    log.info(
        "Compliance audit done - Score=%d Violations=%d (CRIT=%d HIGH=%d MED=%d)",
        score, len(violations), result_base["critical_count"],
        result_base["high_count"], result_base["medium_count"],
    )
    return result


def run():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    log.info("Compliance Audit Agent started. Poll interval: %ds", int(AUDIT_POLL_INTERVAL))
    log.info("Waiting %ds before first LM Studio call to avoid GPU contention at startup", INITIAL_DELAY)
    time.sleep(INITIAL_DELAY)

    while True:
        try:
            generate(r)
        except Exception as e:
            log.error("Compliance audit error: %s", e)
        time.sleep(AUDIT_POLL_INTERVAL)


if __name__ == "__main__":
    run()
