"""Incident Pattern Intelligence Agent.

Mines incident history + near-miss reports against OISD/DGMS regulatory context
using Gemini to surface recurring patterns manual investigations would miss.

Runs every PATTERN_POLL_INTERVAL seconds (default 600 = 10 min).
Writes findings to rigvision:pattern_intel:latest in Redis.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

import redis
import requests

log = logging.getLogger("pattern_intelligence")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

REDIS_URL            = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",   "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct-1m")
PATTERN_POLL_INTERVAL = float(os.getenv("PATTERN_POLL_INTERVAL", "600"))

INCIDENTS_KEY     = "rigvision:incidents:latest"
NEAR_MISSES_KEY   = "rigvision:near_misses:latest"
PATTERN_INTEL_KEY = "rigvision:pattern_intel:latest"

MOCK_NEAR_MISSES = [
    {
        "id": "NM-2026-001", "date": "2026-07-01",
        "zone": "zone_a", "type": "gas_leak",
        "description": "H2S spiked to 8 ppm during active hot work permit. Detector alarmed after 15 min. Gas clear threshold was 5 ppm. Hot work stopped manually by worker â€” no supervisor on floor.",
        "contributing_factors": ["hot_work_permit_active", "elevated_h2s", "delayed_detection", "supervisor_absent"],
        "regulatory_refs": ["OISD-105 Cl.4.2", "OISD-GDN-192 Cl.4"],
        "outcome": "No injury. Hot work suspended 2 hours. Gas re-tested at 30-min intervals.",
    },
    {
        "id": "NM-2026-002", "date": "2026-07-05",
        "zone": "zone_b", "type": "ppe_violation",
        "description": "Night shift crew member found without H2S personal monitor inside confined space. Confined space entry permit was active. Supervisor was off-site reviewing permits.",
        "contributing_factors": ["ppe_missing", "night_shift", "confined_space_entry", "supervisor_off_site"],
        "regulatory_refs": ["Factory Act Â§36", "OISD-105 Cl.5.1", "DGMS 2/2020 Cl.3"],
        "outcome": "Worker evacuated. Mandatory PPE compliance re-briefing issued to night shift.",
    },
    {
        "id": "NM-2026-003", "date": "2026-07-08",
        "zone": "zone_a", "type": "loto_failure",
        "description": "Mud pump vibration reached 4.2 g_rms while adjacent LOTO procedure was in progress. Isolation was not confirmed before work began on the adjacent valve.",
        "contributing_factors": ["vibration_elevated", "loto_incomplete", "concurrent_maintenance"],
        "regulatory_refs": ["OISD-116 Cl.5.3", "OISD-105 Cl.7.3"],
        "outcome": "Pump shutdown. LOTO verification checklist updated. Isolation confirmation made mandatory.",
    },
    {
        "id": "NM-2026-004", "date": "2026-07-12",
        "zone": "zone_a", "type": "process_anomaly",
        "description": "Simultaneous temperature rise to 68Â°C and pressure drop to 2.8 bar on night shift with only 2 crew members. No maintenance permit active â€” cause unknown at time of detection.",
        "contributing_factors": ["high_temperature", "low_pressure", "night_shift", "reduced_crew_2"],
        "regulatory_refs": ["OISD-118 Cl.5.2", "OISD-118 Cl.6.1", "OISD-116 Cl.3.1"],
        "outcome": "Auto cooling activated. Crew evacuated zone. Gasket inspection revealed partial seal failure.",
    },
    {
        "id": "NM-2026-005", "date": "2026-07-15",
        "zone": "zone_b", "type": "simops_violation",
        "description": "Hot work and confined space entry permits both active simultaneously in adjacent zones. No SIMOPS risk assessment was performed. Discovered during unplanned safety walkthrough.",
        "contributing_factors": ["simops_no_assessment", "confined_space_active", "hot_work_adjacent"],
        "regulatory_refs": ["DGMS 3/2016 Cl.5", "OISD-105 Cl.5.1"],
        "outcome": "Both permits suspended. SIMOPS mandatory briefing added to permit issuance checklist.",
    },
    {
        "id": "NM-2026-006", "date": "2026-07-18",
        "zone": "zone_a", "type": "gas_leak",
        "description": "H2S rose to 6 ppm during night shift. Hot work permit was active in same zone. Night supervisor did not evacuate non-essential personnel â€” unclear on Action Level 2 protocol.",
        "contributing_factors": ["hot_work_permit_active", "elevated_h2s", "night_shift", "protocol_knowledge_gap"],
        "regulatory_refs": ["OISD-GDN-192 Cl.4", "OISD-105 Cl.4.2", "DGMS 3/2016 Cl.4"],
        "outcome": "Shift safety officer intervened. H2S source isolated. Protocol refresher for night supervisors.",
    },
]


# The six MOCK_NEAR_MISSES above are fabricated demo fixtures, not detections.
# Seeding them made the near-miss log and every pattern report look like real
# findings. Off by default: set RIGVISION_SEED_NEAR_MISSES=1 to load them for a demo.
SEED_NEAR_MISSES = os.getenv("RIGVISION_SEED_NEAR_MISSES", "0") == "1"


def _seed_near_misses(r: redis.Redis) -> None:
    if not SEED_NEAR_MISSES:
        return
    if not r.exists(NEAR_MISSES_KEY):
        r.set(NEAR_MISSES_KEY, json.dumps(MOCK_NEAR_MISSES))
        r.expire(NEAR_MISSES_KEY, 86400 * 30)
        log.warning("Seeded %d MOCK near-miss records (RIGVISION_SEED_NEAR_MISSES=1) "
                    "- these are demo fixtures, not real detections", len(MOCK_NEAR_MISSES))


def _call_gemini(prompt: str) -> str:
    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 600,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LM Studio call failed: %s", e)
        return f"Analysis unavailable: {e}"


def _analyze(incidents: List[dict], near_misses: List[dict]) -> dict:
    incident_lines = "\n".join(
        f"  [{i.get('incident_id','?')}] {i.get('title','?')} | Rules: {[r.get('rule_id','?') for r in i.get('rules_fired', [])]}"
        for i in incidents[:12]
    ) or "  (No confirmed incidents yet)"

    nm_lines = "\n".join(
        f"  [{nm['id']}] {nm['date']} Zone:{nm['zone']} Type:{nm['type']}\n"
        f"    Factors: {', '.join(nm['contributing_factors'])}\n"
        f"    Regs: {', '.join(nm['regulatory_refs'])}\n"
        f"    Outcome: {nm['outcome']}"
        for nm in near_misses
    )

    prompt = f"""You are a Safety Intelligence Analyst for an remote drilling facility (RigVision-3D).

CONFIRMED INCIDENTS (auto-triggered by compound risk engine):
{incident_lines}

NEAR-MISS REPORTS (last 30 days):
{nm_lines}

REGULATORY FRAMEWORK:
- OISD-105 Cl.4.2: Hot work forbidden if H2S â‰¥ gas-clear threshold (typically 5 ppm)
- OISD-105 Cl.5.1: Confined space entry requires valid permit + continuous gas monitoring
- OISD-105 Cl.7.3: No maintenance work without confirmed LOTO isolation
- OISD-116 Cl.3.1: Night shift on critical ops needs senior supervisor physically on-site
- OISD-116 Cl.4: Two or more simultaneous hazards require formal multi-hazard risk assessment
- OISD-116 Cl.5.3: Vibration â‰¥ 3 g_rms alert; â‰¥ 5 g_rms immediate shutdown
- OISD-118 Cl.5.2: High temp + low pressure simultaneously = potential hydrocarbon release
- OISD-GDN-192 Cl.4: H2S â‰¥ 5 ppm â†’ AL2 (evacuate non-essential); â‰¥ 10 ppm â†’ AL3 (full evacuation)
- DGMS 3/2016 Cl.4: Night shift hot work requires dedicated firewatch + 15-min gas log
- DGMS 3/2016 Cl.5: SIMOPS (hot work + confined space) requires explicit risk assessment

Produce a structured SAFETY INTELLIGENCE REPORT:

## 1. RECURRING PATTERNS
Identify 3â€“5 patterns that appear across multiple events. Cite specific NM/Incident IDs. Focus on what combinations keep reappearing.

## 2. HIGHEST-RISK COMPOUND SCENARIOS
2â€“3 scenarios where the COMBINATION of factors created a danger greater than any individual factor. Explain the compounding mechanism in plain language a shift supervisor would understand.

## 3. REGULATORY COMPLIANCE GAPS
Which specific OISD/DGMS clauses are being systematically violated or inconsistently applied? Cite evidence.

## 4. ACTIONABLE PREVENTION PRIORITIES
Numbered, highest-impact first. Concrete control measures, not generic advice. Specify WHO must act and WHEN.

## 5. RISK FORECAST
Based on these patterns, what compound risk scenario is most likely to escalate to a CRITICAL incident in the next 7 days if current trends continue?

Be specific and evidence-based. A safety officer will present this at the daily briefing."""

    analysis = _call_gemini(prompt)

    # Extract top-level prevention priorities as structured list for UI
    priorities = []
    in_section = False
    for line in analysis.split("\n"):
        stripped = line.strip()
        if "ACTIONABLE PREVENTION" in stripped.upper():
            in_section = True
            continue
        if in_section and stripped.startswith("#"):
            break
        if in_section and stripped and (stripped[0].isdigit() or stripped.startswith("-")):
            text = stripped.lstrip("0123456789.-) ").strip()
            if text:
                priorities.append(text)

    return {
        "generated_at":        int(time.time()),
        "incidents_analyzed":  len(incidents),
        "near_misses_analyzed": len(near_misses),
        "analysis":            analysis,
        "top_priorities":      priorities[:5],
        "status":              "ready",
    }


INITIAL_DELAY = 180  # seconds before first LM Studio call at startup


def generate(r: redis.Redis) -> dict:
    """Run one pattern-intelligence pass and write it to Redis. Returns the report."""
    _seed_near_misses(r)

    incidents_raw = r.get(INCIDENTS_KEY)
    incidents     = json.loads(incidents_raw) if incidents_raw else []
    nm_raw        = r.get(NEAR_MISSES_KEY)
    near_misses   = json.loads(nm_raw) if nm_raw else []

    # Nothing to mine yet - don't burn an LM call inventing patterns from no data.
    if not incidents and not near_misses:
        result = {
            "generated_at":         int(time.time()),
            "incidents_analyzed":   0,
            "near_misses_analyzed": 0,
            "analysis":             "No incidents or near-misses on record yet. Pattern analysis will begin once events accumulate.",
            "top_priorities":       [],
            "status":               "ready",
        }
    else:
        log.info("Analyzing %d incidents + %d near-misses", len(incidents), len(near_misses))
        result = _analyze(incidents, near_misses)

    r.set(PATTERN_INTEL_KEY, json.dumps(result))
    r.expire(PATTERN_INTEL_KEY, 86400)
    log.info("Pattern intelligence report written (priorities=%d)", len(result["top_priorities"]))
    return result


def run():
    r = redis.from_url(REDIS_URL, decode_responses=True)
    log.info("Pattern Intelligence Agent started. Poll interval: %ds", int(PATTERN_POLL_INTERVAL))
    _seed_near_misses(r)

    log.info("Waiting %ds before first LM Studio call to avoid GPU contention at startup", INITIAL_DELAY)
    time.sleep(INITIAL_DELAY)

    while True:
        try:
            generate(r)
        except Exception as e:
            log.error("Pattern analysis error: %s", e)
        time.sleep(PATTERN_POLL_INTERVAL)


if __name__ == "__main__":
    run()
