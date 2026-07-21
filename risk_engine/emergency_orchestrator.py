"""Emergency Response Orchestrator.

Triggered by compound_risk.py when CRITICAL risk persists for N consecutive
cycles. Responsibilities:
  1. Snapshot the full rig state (sensors, persons, PPE, permits)
  2. Write an incident record to Postgres + Redis
  3. Generate a structured incident report via Gemini
  4. Publish to rigvision:incidents:latest for the WS bridge to broadcast
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import redis
import requests

from risk_engine.rules import RuleFiring

log = logging.getLogger("risk_engine.emergency")

LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",   "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct-1m")

INCIDENTS_KEY = "rigvision:incidents:latest"
INCIDENT_COOLDOWN = int(os.getenv("INCIDENT_COOLDOWN_SECONDS", "120"))
# A standing breach that never clears still gets logged again periodically (a
# "still open" record), just not every couple of minutes.
STANDING_BREACH_REMINDER = int(os.getenv("INCIDENT_REMINDER_SECONDS", "3600"))

_last_incident_time: float = 0.0
_last_incident_signature: Optional[str] = None


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
        return f"Report generation failed: {e}"


def _generate_incident_report(
    firings: List[RuleFiring],
    state: Dict[str, Any],
    incident_id: str,
) -> str:
    sensor_summary = {
        k: round(float((v or {}).get("value") or 0), 2)
        for k, v in state.get("sensors", {}).items()
    }
    persons = state.get("persons", [])
    permits = [p for p in state.get("permits", []) if p.get("status") == "active"]
    shift   = state.get("shift", {})
    maintenance = [m for m in state.get("maintenance", []) if m.get("status") == "in_progress"]

    rules_text = "\n".join(
        f"  [{f.rule_id}] {f.severity} â€” {f.title}: {f.description}"
        for f in firings
    )
    reg_refs = sorted({ref for f in firings for ref in f.regulatory_refs})

    prompt = f"""You are the RigVision automated safety system generating an OFFICIAL INCIDENT REPORT for an remote drilling facility.

INCIDENT ID: {incident_id}
TIMESTAMP: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

TRIGGERED COMPOUND RISK RULES:
{rules_text}

SENSOR READINGS AT TIME OF INCIDENT:
{json.dumps(sensor_summary, indent=2)}

SHIFT CONTEXT:
- Shift: {shift.get('shift', '?')} (reduced_crew={shift.get('is_reduced_crew', False)}, crew_size={shift.get('crew_size', '?')})
- Supervisor: {shift.get('supervisor', '?')}

ACTIVE PERMITS-TO-WORK:
{json.dumps([{'id': p['permit_id'], 'type': p['type'], 'zone': p['zone'], 'workers': p.get('workers',[])} for p in permits], indent=2)}

ACTIVE MAINTENANCE:
{json.dumps([{'id': m['maintenance_id'], 'zone': m['zone'], 'desc': m['description']} for m in maintenance], indent=2)}

PERSONNEL ON SITE: {len(persons)} persons tracked

APPLICABLE REGULATIONS: {', '.join(reg_refs)}

Generate a formal incident report with these sections:
1. INCIDENT SUMMARY (2 sentences â€” what happened, why it is significant)
2. COMPOUND RISK ASSESSMENT (explain why the COMBINATION of conditions is dangerous, not just individual sensors)
3. REGULATORY BREACHES IDENTIFIED (cite specific OISD/DGMS clauses)
4. IMMEDIATE RESPONSE ACTIONS (numbered, priority order, first 15 minutes)
5. EVIDENCE PRESERVATION CHECKLIST (what must be documented/retained)
6. REPORTING OBLIGATIONS (who must be notified: DGMS, factory inspector, OIM)

Be formal, precise, and cite specific regulation clauses. This report will be filed with DGMS."""

    return _call_gemini(prompt)


def _write_to_postgres(incident: dict) -> None:
    try:
        import psycopg2, psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", "5433")),
            dbname=os.getenv("POSTGRES_DB", "rigvision"),
            user=os.getenv("POSTGRES_USER", "rigvision"),
            password=os.getenv("POSTGRES_PASSWORD", "rigvision_dev_password"),
        )
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO incidents
                    (incident_id, severity, title, rules_fired, sensor_snapshot,
                     persons_snapshot, permits_snapshot, report_text, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open')
                ON CONFLICT (incident_id) DO NOTHING
            """, (
                incident["incident_id"],
                incident["severity"],
                incident["title"],
                json.dumps(incident["rules_fired"]),
                json.dumps(incident["sensor_snapshot"]),
                json.dumps(incident["persons_snapshot"]),
                json.dumps(incident["permits_snapshot"]),
                incident["report_text"],
            ))
        conn.commit()
        conn.close()
        log.info("Incident %s written to Postgres", incident["incident_id"])
    except Exception as e:
        log.warning("Postgres incident write failed: %s", e)


def maybe_trigger(
    r: redis.Redis,
    firings: List[RuleFiring],
    state: Dict[str, Any],
    risk_payload: Dict[str, Any],
) -> Optional[dict]:
    """Create an incident, but not one per poll cycle for a single standing breach.

    Files a new incident when either:
      - the breach signature changed (different rules and/or permits/zones firing
        -- a genuinely new event), even if still inside the cooldown window, or
      - the SAME breach has now persisted past STANDING_BREACH_REMINDER, so an
        hours-long unresolved condition still produces periodic records.
    A same-signature breach inside the cooldown window is not re-filed -- that
    was the bug: compound_risk.py polls every few seconds and previously reset
    its consecutive-CRITICAL counter after every trigger, so one unresolved
    permit breach generated a fresh "incident" every ~2 minutes indefinitely.
    """
    global _last_incident_time, _last_incident_signature
    now = time.time()

    signature = json.dumps(
        {"rules": sorted(f.rule_id for f in firings),
         "zones": sorted({f.zone for f in firings if f.zone})},
        sort_keys=True,
    )
    same_breach = signature == _last_incident_signature
    elapsed = now - _last_incident_time

    if same_breach and elapsed < STANDING_BREACH_REMINDER:
        return None
    if not same_breach and elapsed < INCIDENT_COOLDOWN:
        return None

    _last_incident_time = now
    _last_incident_signature = signature

    incident_id = f"INC-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    top_rule = max(firings, key=lambda f: (f.severity == "CRITICAL", f.rule_id))
    title = f"COMPOUND RISK: {top_rule.title}"

    log.warning("INCIDENT TRIGGERED: %s", incident_id)

    # Build snapshot
    permits = [p for p in state.get("permits", []) if p.get("status") == "active"]
    sensor_snapshot = {
        k: round(float((v or {}).get("value") or 0), 2)
        for k, v in state.get("sensors", {}).items()
    }

    # Generate report (Gemini call â€” may take a few seconds)
    report_text = _generate_incident_report(firings, state, incident_id)

    incident = {
        "incident_id":       incident_id,
        "severity":          "CRITICAL",
        "title":             title,
        "rules_fired":       risk_payload.get("rules_fired", []),
        "sensor_snapshot":   sensor_snapshot,
        "persons_snapshot":  state.get("persons", []),
        "permits_snapshot":  permits,
        "report_text":       report_text,
        "status":            "open",
        "created_at":        int(now),
        "narrative":         risk_payload.get("narrative", ""),
        "immediate_actions": risk_payload.get("immediate_actions", []),
    }

    # Write to Redis list (keep last 20 incidents)
    incidents_raw = r.get(INCIDENTS_KEY)
    incidents = json.loads(incidents_raw) if incidents_raw else []
    incidents.insert(0, incident)
    r.set(INCIDENTS_KEY, json.dumps(incidents[:20]))
    r.expire(INCIDENTS_KEY, 86400)

    # Write to Postgres (best-effort)
    _write_to_postgres(incident)

    log.warning("Incident %s filed. Severity=CRITICAL", incident_id)
    return incident
