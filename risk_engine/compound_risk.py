"""Compound Risk Detection Engine - standalone polling service.

Reads sensors + persons + PPE + permits + shift + maintenance from Redis
every POLL_INTERVAL seconds, applies correlation rules, and calls Gemini
to generate a risk narrative when the state changes.

Output: rigvision:compound_risk:latest (JSON, read by backend WS bridge).

Run as:  python -m risk_engine.compound_risk
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis
import requests

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from risk_engine.mock_context import seed_if_absent
from risk_engine.rules import RuleFiring, aggregate_severity, evaluate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] risk_engine: %(message)s",
)
log = logging.getLogger("risk_engine")

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
REDIS_HOST     = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None
POLL_INTERVAL  = float(os.getenv("RISK_POLL_INTERVAL", "5"))
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",   "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct-1m")
CRITICAL_CONSECUTIVE_FOR_INCIDENT = int(os.getenv("RISK_INCIDENT_THRESHOLD", "2"))

COMPOUND_RISK_KEY = "rigvision:compound_risk:latest"

# â”€â”€ OISD/DGMS inline regulatory context (for Gemini prompt) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_REGULATORY_CONTEXT = """
KEY OISD/DGMS/FACTORY ACT REGULATORY THRESHOLDS (India):

OISD-105 (Permit-to-Work):
- Hot work permits require H2S/flammable gas <5 ppm in work area before issue.
- Confined space permits require <10 ppm H2S and O2 between 19.5%-23.5%.
- LOTO (Lock-Out/Tag-Out) mandatory before any maintenance on energised equipment.
- Gas testing every 30 minutes during hot work.

OISD-155 (PPE for Drilling):
- H2S TLV-TWA: 1 ppm; STEL: 5 ppm; IDLH: 50 ppm.
- SCBA mandatory above 10 ppm H2S. H2S detector mandatory at waist height.
- Hard hats, safety glasses mandatory at all times on drill floor.

OISD-116 (Minimum Safety Standards - Drilling):
- Minimum crew of 5 for any well-control operation on night shift.
- BOP to be tested every 14 days; pressure integrity every 250 hours.
- Temperature >85°C in pump room requires immediate shutdown.
- Vibration >5 g_rms on mud pump indicates imminent bearing failure (shutdown).

OISD-118 (Pressure Vessels & Piping):
- Operating below 30% of design pressure triggers low-pressure alarm.
- Pressure drop >20% in 10 minutes = suspected leak; isolate immediately.

DGMS Circular 3/2016 - Hot Work in Hazardous Areas:
- Hot work during night shift requires a dedicated fire watch.
- Firewatch to carry portable gas detector; abort if alarm triggers.

Factory Act 1948 Â§36:
- Employer must provide and maintain PPE free of charge.
- Failure to provide = criminal liability for safety officer.
"""


def _call_gemini(prompt: str) -> str:
    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.15,
                "max_tokens": 400,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LM Studio call failed: %s", e)
        return f"Narrative generation failed: {e}"


# Threshold table mirroring cad/zone_definitions.json (the single source of truth
# used by the sensor console, heatmap and anomaly evaluator). Used only to label
# each reading BREACH/NORMAL for the narrative prompt.
_NARRATIVE_LIMITS = {
    "gas":      {"warning": 10, "critical": 15},
    "temp":     {"warning": 50, "critical": 65},
    "vib":      {"warning": 5,  "critical": 8},
    "noise":    {"warning": 95, "critical": 105},
    "pressure": {"warning": 20, "critical": 25, "warning_low": 4, "critical_low": 2},
}


def _reading_status(sensor_id: str, value: float) -> str:
    """Label a reading against its configured limits."""
    key = next((k for k in _NARRATIVE_LIMITS if sensor_id.startswith(k)), None)
    lim = _NARRATIVE_LIMITS.get(key or "", {})
    if not lim:
        return "NORMAL"
    if lim.get("critical") is not None and value >= lim["critical"]:
        return f"BREACH (critical limit {lim['critical']})"
    if lim.get("warning") is not None and value >= lim["warning"]:
        return f"BREACH (warning limit {lim['warning']})"
    if lim.get("critical_low") is not None and value <= lim["critical_low"]:
        return f"BREACH (critical low limit {lim['critical_low']})"
    if lim.get("warning_low") is not None and value <= lim["warning_low"]:
        return f"BREACH (low limit {lim['warning_low']})"
    hi = lim.get("warning")
    return f"NORMAL (within limit {hi})" if hi is not None else "NORMAL"


def _build_narrative(firings: List[RuleFiring], sensors: dict, shift: dict) -> str:
    rules_text = "\n".join(
        f"- [{f.rule_id}] {f.severity}: {f.title}\n  {f.description}\n"
        f"  Factors: {', '.join(f.contributing_factors)}\n"
        f"  Regulatory refs: {', '.join(f.regulatory_refs)}"
        for f in firings
    )

    # Label every reading BREACH/NORMAL. Handing over bare numbers lets the model
    # describe an in-limit sensor as breaching (e.g. calling vib 3.7 "above 5").
    reading_lines = []
    for sid, v in sorted(sensors.items()):
        if not v:
            continue
        val = round(float(v.get("value") or 0), 2)
        reading_lines.append(f"  {sid} = {val}  -> {_reading_status(sid, val)}")
    readings_text = "\n".join(reading_lines) or "  (no readings)"

    # Only the clauses the fired rules actually cite. Passing the whole OISD/DGMS
    # catalogue invites the model to bring in unrelated clauses (confined-space
    # limits with no confined-space permit active, etc.).
    cited = sorted({ref for f in firings for ref in f.regulatory_refs})
    reg_text = "\n".join(f"  - {c}" for c in cited) or "  (none cited)"

    prompt = f"""You are the RigVision Compound Risk Intelligence Engine at an remote offshore drilling facility.
You have detected correlated risk conditions that NO single sensor threshold would catch alone.

CURRENT SENSOR READINGS (status is authoritative -- do not contradict it):
{readings_text}

SHIFT CONTEXT: {shift.get('shift','?')} shift, {shift.get('crew_size','?')} crew members, reduced={shift.get('is_reduced_crew',False)}

TRIGGERED CORRELATION RULES (these are the ONLY rules currently firing):
{rules_text}

REGULATIONS CITED BY THESE RULES:
{reg_text}

Write a concise 4-6 sentence compound risk assessment for the operations supervisor:
1. What combination of conditions makes this dangerous RIGHT NOW
2. Which regulatory limits are breached, citing only the regulations listed above
3. The single most important immediate action
4. Expected consequence if not acted upon in the next 15 minutes

STRICT RULES -- a fabricated hazard destroys the credibility of this alert:
- Discuss ONLY sensors marked BREACH above. Never describe a NORMAL sensor as high,
  rising, exceeding, or approaching a limit.
- Never mention a permit, confined space entry, or maintenance activity unless it
  appears in the triggered rules above.
- Never cite a regulation that is not in the list above.
- Every number you state must appear verbatim in the readings or rules above.

Be direct, technical, and specific. No markdown headers. No bullet points. Plain prose."""

    return _call_gemini(prompt)


def _build_immediate_actions(firings: List[RuleFiring]) -> List[str]:
    """Deterministic immediate actions from fired rules - no LLM needed."""
    actions = []
    seen_rules = {f.rule_id for f in firings}
    if "R001" in seen_rules:
        actions.append("STOP all hot work immediately - cease welding/cutting and remove ignition sources.")
        actions.append("Initiate gas testing every 5 minutes until below 1 ppm before any restart.")
    if "R002" in seen_rules:
        actions.append("Evacuate non-essential personnel to muster point; issue SCBA to all in-zone workers.")
    if "R003" in seen_rules:
        actions.append("Emergency LOTO verification: confirm all isolation points on maintenance equipment.")
    if "R005" in seen_rules:
        actions.append("Initiate pressure integrity check; prepare for emergency isolation of process lines.")
    if "R006" in seen_rules:
        actions.append("RESCUE PROTOCOL: assume confined space workers are incapacitated; deploy rescue team with SCBA.")
    if "R_PTW" in seen_rules:
        actions.append("STOP work under the affected permit; re-validate permit conditions before resuming.")
    return actions


def _fetch_state(r: redis.Redis) -> Dict[str, Any]:
    pipe = r.pipeline()
    pipe.hgetall("rigvision:sensors:latest")
    pipe.get("rigvision:persons")
    pipe.get("rigvision:ppe:latest")
    pipe.get("rigvision:permits:active")
    pipe.get("rigvision:shift:current")
    pipe.get("rigvision:maintenance:active")
    results = pipe.execute()

    sensors_raw, persons_raw, ppe_raw, permits_raw, shift_raw, maint_raw = results

    sensors  = {k: json.loads(v) for k, v in (sensors_raw or {}).items()}
    persons  = json.loads(persons_raw)  if persons_raw  else []
    ppe      = json.loads(ppe_raw)      if ppe_raw      else {}
    permits  = json.loads(permits_raw)  if permits_raw  else []
    shift    = json.loads(shift_raw)    if shift_raw    else {}
    maint    = json.loads(maint_raw)    if maint_raw    else []

    return dict(sensors=sensors, persons=persons, ppe=ppe,
                permits=permits, shift=shift, maintenance=maint)


def run() -> None:
    log.info("Compound Risk Engine starting (poll=%.1fs)", POLL_INTERVAL)

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT,
                    password=REDIS_PASSWORD, decode_responses=True)
    try:
        r.ping()
        log.info("Redis connected.")
    except Exception as e:
        log.error("Redis unavailable: %s", e)
        sys.exit(1)

    seed_if_absent(r)

    # Lazy import to avoid circular on startup
    from risk_engine.emergency_orchestrator import maybe_trigger

    prev_signature: Optional[str] = None
    consecutive_critical = 0
    _last_narrative_at: float = 0.0
    NARRATIVE_COOLDOWN = 300.0  # seconds - don't call LM Studio more than once per 5 min

    while True:
        try:
            state = _fetch_state(r)
            firings = evaluate(
                state["sensors"], state["persons"], state["ppe"],
                state["permits"], state["shift"], state["maintenance"],
            )
            severity = aggregate_severity(firings)

            # Track consecutive CRITICAL cycles for incident gating
            if severity == "CRITICAL":
                consecutive_critical += 1
            else:
                consecutive_critical = 0

            # Build a compact signature to detect state changes
            signature = json.dumps(
                {"sev": severity, "rules": sorted(f.rule_id for f in firings)},
                sort_keys=True,
            )

            now = int(time.time())
            payload: Dict[str, Any] = {
                "severity": severity,
                "rule_count": len(firings),
                "rules_fired": [
                    {
                        "rule_id": f.rule_id,
                        "severity": f.severity,
                        "title": f.title,
                        "description": f.description,
                        "contributing_factors": f.contributing_factors,
                        "zone": f.zone,
                        "regulatory_refs": f.regulatory_refs,
                    }
                    for f in firings
                ],
                "immediate_actions": _build_immediate_actions(firings),
                "narrative": "",
                "updated_at": now,
            }

            if signature != prev_signature:
                log.info("Risk state changed â†’ %s (%d rules)", severity, len(firings))
                prev_signature = signature
                elapsed = time.time() - _last_narrative_at
                if firings and elapsed >= NARRATIVE_COOLDOWN:
                    import threading
                    def _gen_and_store(f=firings, s=state, p=payload):
                        p["narrative"] = _build_narrative(f, s["sensors"], s["shift"])
                        r.set(COMPOUND_RISK_KEY, json.dumps(p))
                        r.expire(COMPOUND_RISK_KEY, 300)
                    threading.Thread(target=_gen_and_store, daemon=True).start()
                    _last_narrative_at = time.time()
                elif not firings:
                    payload["narrative"] = "All systems within safe operating limits. No compound risks detected."

            else:
                # State unchanged - keep existing narrative from Redis
                existing_raw = r.get(COMPOUND_RISK_KEY)
                if existing_raw:
                    try:
                        existing = json.loads(existing_raw)
                        payload["narrative"] = existing.get("narrative", "")
                    except Exception:
                        pass

            r.set(COMPOUND_RISK_KEY, json.dumps(payload))
            r.expire(COMPOUND_RISK_KEY, 300)

            # Trigger emergency orchestrator after N consecutive CRITICAL cycles
            if (severity == "CRITICAL" and
                    consecutive_critical >= CRITICAL_CONSECUTIVE_FOR_INCIDENT):
                try:
                    maybe_trigger(r, firings, state, payload)
                    consecutive_critical = 0  # reset after incident filed
                except Exception as e:
                    log.warning("Emergency orchestrator error: %s", e)

        except Exception as e:
            log.error("Poll error: %s", e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run()
