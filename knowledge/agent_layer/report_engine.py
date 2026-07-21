"""Daily Shift Report engine.

Three jobs:

1. build_draft()   - sweep the last N hours of anomalies, incidents, compliance
                     violations and closed permits, and turn them into a list of
                     line items the supervisor must account for.
2. save_report()   - persist the filled-in report (what was actually done about
                     each item).
3. review_report() - after submission, analyse the report against report history.
                     Recurrence detection is DETERMINISTIC (signature matching
                     across past reports); the LM Studio call then explains the
                     findings and suggests process improvements. The LM is never
                     the thing deciding whether something is a repeat -- it only
                     narrates evidence already computed here.

Storage: rigvision:daily_reports  (JSON list, newest first, capped at 90)
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

log = logging.getLogger("report_engine")

REDIS_URL       = os.getenv("REDIS_URL", "redis://localhost:6379/0")
LM_STUDIO_URL   = os.getenv("LM_STUDIO_URL",   "http://localhost:1234/v1/chat/completions")
LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL", "qwen2.5-7b-instruct-1m")

REPORTS_KEY          = "rigvision:daily_reports"
DIAGNOSTICS_KEY      = "rigvision:diagnostics"
INCIDENTS_KEY        = "rigvision:incidents:latest"
COMPLIANCE_AUDIT_KEY = "rigvision:compliance_audit:latest"
PERMITS_KEY          = "rigvision:permits:active"

MAX_REPORTS = 90          # ~3 months of daily reports
RECURRENCE_LOOKBACK = 30  # reports scanned when counting repeats


# --------------------------------------------------------------------------
# Draft building
# --------------------------------------------------------------------------

def _load_json(r: redis.Redis, key: str, default):
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else default
    except Exception:
        return default


def _signature(item: dict) -> str:
    """Stable identity for 'the same thing going wrong again'.

    Deliberately excludes timestamps and measured values -- H2S breaching in
    zone_a today and again next Tuesday must produce the SAME signature, or
    recurrence detection is worthless.
    """
    src = item.get("source", "?")
    if src == "anomaly":
        sensors = "+".join(sorted(item.get("sensors") or []))
        return f"anomaly:{item.get('zone','?')}:{sensors}"
    if src == "incident":
        rules = "+".join(sorted(item.get("rules") or []))
        return f"incident:{rules}"
    if src == "compliance":
        return f"compliance:{item.get('code','?')}"
    if src == "permit":
        return f"permit:{item.get('permit_type','?')}:{item.get('zone','?')}"
    return f"{src}:{item.get('title','?')}"


def build_draft(r: redis.Redis, hours: float = 24.0) -> dict:
    """Collect everything from the last `hours` that needs an explanation."""
    now       = int(time.time())
    cutoff    = now - int(hours * 3600)
    cutoff_ms = cutoff * 1000
    items: List[dict] = []

    # -- Anomalies (threshold breaches diagnosed by the LLM agent) ----------
    for d in _load_json(r, DIAGNOSTICS_KEY, []):
        ts_ms = int(d.get("timestamp") or 0)
        if ts_ms < cutoff_ms:
            continue
        sensors = d.get("triggered_sensors") or []
        zone    = d.get("rig_zone_id") or d.get("zone_id") or "?"
        items.append({
            "ref_id":      d.get("event_id") or f"anom-{ts_ms}",
            "source":      "anomaly",
            "severity":    d.get("severity", "HIGH"),
            "zone":        zone,
            "sensors":     sensors,
            "occurred_at": ts_ms // 1000,
            "title":       f"{', '.join(s.upper() for s in sensors) or 'Sensor'} breach in {zone.replace('_', ' ').upper()}",
            "detail":      (d.get("diagnosis") or d.get("summary") or "")[:400],
            "telemetry":   d.get("telemetry_snapshot") or {},
        })

    # -- Incidents (compound risk engine firings) --------------------------
    for inc in _load_json(r, INCIDENTS_KEY, []):
        ts = int(inc.get("created_at") or inc.get("timestamp") or 0)
        if ts > 10_000_000_000:      # stored in ms
            ts //= 1000
        if ts < cutoff:
            continue
        rules = [rf.get("rule_id", "?") for rf in (inc.get("rules_fired") or [])]
        items.append({
            "ref_id":      inc.get("incident_id", f"inc-{ts}"),
            "source":      "incident",
            "severity":    inc.get("severity", "CRITICAL"),
            "zone":        inc.get("zone", "-"),
            "rules":       rules,
            "occurred_at": ts,
            "title":       inc.get("title") or f"Compound risk incident ({', '.join(rules)})",
            "detail":      (inc.get("report_text") or "")[:400],
        })

    # -- Standing compliance violations ------------------------------------
    audit = _load_json(r, COMPLIANCE_AUDIT_KEY, {}) or {}
    for v in (audit.get("violations") or []):
        items.append({
            "ref_id":      f"{v.get('code','C?')}-{audit.get('generated_at', now)}",
            "source":      "compliance",
            "severity":    v.get("severity", "MEDIUM"),
            "code":        v.get("code"),
            "zone":        "-",
            "occurred_at": int(audit.get("generated_at") or now),
            "title":       f"[{v.get('code')}] {v.get('standard')} {v.get('clause')} deviation",
            "detail":      v.get("description", "")[:400],
            "regulatory":  f"{v.get('standard','')} {v.get('clause','')}".strip(),
        })

    # -- Permits that closed in the window ---------------------------------
    for p in _load_json(r, PERMITS_KEY, []):
        closed = int(p.get("closed_at") or 0)
        if p.get("status") != "closed" or closed < cutoff:
            continue
        items.append({
            "ref_id":      p.get("permit_id", f"ptw-{closed}"),
            "source":      "permit",
            "severity":    "INFO",
            "zone":        p.get("zone", "-"),
            "permit_type": p.get("type", "?"),
            "occurred_at": closed,
            "title":       f"{str(p.get('type','')).replace('_',' ').upper()} permit closed - {p.get('zone','?').replace('_',' ').upper()}",
            "detail":      p.get("description", "")[:400],
        })

    # Collapse duplicates WITHIN the window. A standing breach can fire dozens of
    # times in 24h; that is one thing to explain, not fifty. Keep the newest
    # occurrence as the representative and carry an occurrence count.
    grouped: Dict[str, dict] = {}
    for it in items:
        sig = _signature(it)
        it["signature"] = sig
        existing = grouped.get(sig)
        if existing is None:
            it["occurrences"] = 1
            it["first_occurred_at"] = it["occurred_at"]
            grouped[sig] = it
        else:
            existing["occurrences"] += 1
            if it["occurred_at"] > existing["occurred_at"]:
                existing["occurred_at"] = it["occurred_at"]
                existing["detail"] = it["detail"] or existing["detail"]
            existing["first_occurred_at"] = min(existing["first_occurred_at"], it["occurred_at"])

    deduped = list(grouped.values())

    # Attach recurrence context so the form itself shows "this is the 4th day running"
    history = _load_json(r, REPORTS_KEY, [])
    for it in deduped:
        prior = _prior_occurrences(history, it["signature"])
        it["prior_count"] = len(prior)
        it["last_seen"]   = prior[0]["report_date"] if prior else None
        it["last_action"] = prior[0]["action_taken"] if prior else None

    sev_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}
    deduped.sort(key=lambda i: (sev_rank.get(i["severity"], 9), -i["occurrences"], -i["occurred_at"]))

    return {
        "generated_at":  now,
        "window_hours":  hours,
        "window_start":  cutoff,
        "item_count":    len(deduped),
        "raw_event_count": len(items),
        "items":         deduped,
    }


def _prior_occurrences(history: List[dict], signature: str) -> List[dict]:
    """Every past report entry matching this signature, newest first."""
    out = []
    for rep in history[:RECURRENCE_LOOKBACK]:
        for it in (rep.get("items") or []):
            if it.get("signature") == signature:
                out.append({
                    "report_id":    rep.get("report_id"),
                    "report_date":  rep.get("report_date"),
                    "action_taken": it.get("action_taken", ""),
                    "root_cause":   it.get("root_cause", ""),
                    "resolution":   it.get("resolution", ""),
                })
    return out


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------

def save_report(r: redis.Redis, payload: dict) -> dict:
    """Persist a submitted report. Returns the stored record."""
    now = int(time.time())
    report = {
        "report_id":    f"DSR-{time.strftime('%Y%m%d', time.localtime(now))}-{uuid.uuid4().hex[:5].upper()}",
        "report_date":  payload.get("report_date") or time.strftime("%Y-%m-%d", time.localtime(now)),
        "shift":        payload.get("shift", "day"),
        "supervisor":   payload.get("supervisor", "").strip() or "unnamed",
        "submitted_at": now,
        "window_hours": payload.get("window_hours", 24),
        "notes":        payload.get("notes", ""),
        "items":        payload.get("items", []),
        "review":       {"status": "pending"},
    }

    history = _load_json(r, REPORTS_KEY, [])
    history.insert(0, report)
    r.set(REPORTS_KEY, json.dumps(history[:MAX_REPORTS]))
    log.info("Daily report %s saved (%d items)", report["report_id"], len(report["items"]))
    return report


def get_reports(r: redis.Redis) -> List[dict]:
    return _load_json(r, REPORTS_KEY, [])


def get_report(r: redis.Redis, report_id: str) -> Optional[dict]:
    for rep in _load_json(r, REPORTS_KEY, []):
        if rep.get("report_id") == report_id:
            return rep
    return None


def _update_report(r: redis.Redis, report_id: str, patch: dict) -> Optional[dict]:
    history = _load_json(r, REPORTS_KEY, [])
    for rep in history:
        if rep.get("report_id") == report_id:
            rep.update(patch)
            r.set(REPORTS_KEY, json.dumps(history[:MAX_REPORTS]))
            return rep
    return None


# --------------------------------------------------------------------------
# AI review
# --------------------------------------------------------------------------

def _call_lm(prompt: str, max_tokens: int = 700) -> str:
    try:
        resp = requests.post(
            LM_STUDIO_URL,
            json={
                "model": LM_STUDIO_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LM Studio call failed: %s", e)
        return f"AI narrative unavailable: {e}"


def _strip_fabricated_repeats(narrative: str) -> str:
    """Force the REPEAT FAILURES section to 'None.' when history shows no repeats.

    Small local models keep writing a plausible-sounding repeat analysis even when
    the prompt states there are none. Recurrence is computed from stored report
    history here, so that computation is authoritative and simply overrides the
    model rather than trusting it to comply.
    """
    lines, out = narrative.split("\n"), []
    in_section = False
    for line in lines:
        heading = line.strip().lstrip("#").strip().upper()
        if line.strip().startswith("#"):
            if heading.startswith("REPEAT FAILURES"):
                in_section = True
                out.append(line)
                out.append("None.")
                out.append("")
                continue
            in_section = False
        if not in_section:
            out.append(line)
    return "\n".join(out)


def _analyse_recurrence(report: dict, history: List[dict]) -> List[dict]:
    """Deterministic repeat detection across report history.

    An item is a repeat if its signature appeared in any earlier report. This is
    computed from stored data, not inferred by the model, so it cannot hallucinate
    a recurrence that never happened.
    """
    # Exclude the report being reviewed from its own history.
    past = [h for h in history if h.get("report_id") != report.get("report_id")]
    findings = []

    for it in (report.get("items") or []):
        # Routine events (a permit closing on schedule) recur by design -- they
        # are not failures, and flagging them buries the ones that are.
        if it.get("severity") == "INFO" or it.get("source") == "permit":
            continue
        sig   = it.get("signature") or _signature(it)
        prior = _prior_occurrences(past, sig)
        if not prior:
            continue
        findings.append({
            "signature":    sig,
            "title":        it.get("title", "?"),
            "severity":     it.get("severity", "HIGH"),
            "zone":         it.get("zone", "-"),
            "times_seen":   len(prior) + 1,
            "first_seen":   prior[-1]["report_date"],
            "last_seen":    prior[0]["report_date"],
            "this_action":  it.get("action_taken", ""),
            "past_actions": [p["action_taken"] for p in prior if p["action_taken"]][:5],
            "unresolved":   it.get("resolution") != "resolved",
        })

    findings.sort(key=lambda f: -f["times_seen"])
    return findings


def _quality_flags(report: dict) -> List[str]:
    """Cheap deterministic checks on report completeness."""
    flags = []
    items = report.get("items") or []

    blank = [i["title"] for i in items if not (i.get("action_taken") or "").strip()]
    if blank:
        flags.append(f"{len(blank)} item(s) submitted with no action recorded: {'; '.join(blank[:3])}")

    thin = [i["title"] for i in items
            if 0 < len((i.get("action_taken") or "").strip()) < 15]
    if thin:
        flags.append(f"{len(thin)} item(s) have an action description too short to audit: {'; '.join(thin[:3])}")

    no_cause = [i["title"] for i in items
                if i.get("severity") in ("CRITICAL", "HIGH") and not (i.get("root_cause") or "").strip()]
    if no_cause:
        flags.append(f"{len(no_cause)} high-severity item(s) closed without a root cause: {'; '.join(no_cause[:3])}")

    unresolved = [i for i in items if i.get("resolution") == "unresolved"]
    if unresolved:
        flags.append(f"{len(unresolved)} item(s) carried forward unresolved into the next shift")

    return flags


def review_report(r: redis.Redis, report_id: str) -> dict:
    """Run the AI review pass over a submitted report. Writes result onto the report."""
    history = _load_json(r, REPORTS_KEY, [])
    report  = next((h for h in history if h.get("report_id") == report_id), None)
    if not report:
        raise ValueError(f"Report {report_id} not found")

    recurring = _analyse_recurrence(report, history)
    flags     = _quality_flags(report)

    # Build evidence block for the model -- it explains, it does not detect.
    items_text = "\n".join(
        f"  [{i.get('severity')}] {i.get('title')}\n"
        f"    What was done: {i.get('action_taken') or '(nothing recorded)'}\n"
        f"    Root cause:    {i.get('root_cause') or '(not identified)'}\n"
        f"    Resolution:    {i.get('resolution') or 'unknown'}"
        for i in (report.get("items") or [])
    ) or "  (no items)"

    if recurring:
        rec_text = "\n".join(
            f"  - '{f['title']}' has now occurred {f['times_seen']} times "
            f"(first {f['first_seen']}, last {f['last_seen']}).\n"
            f"    Previous fixes attempted: {'; '.join(f['past_actions']) or '(none recorded)'}\n"
            f"    Fix applied this time: {f['this_action'] or '(nothing recorded)'}"
            for f in recurring
        )
        repeat_instruction = (
            "One bullet per repeat issue listed above, and ONLY those issues. Name the\n"
            "issue, say why the earlier fix did not hold, and give the control that would\n"
            "actually stop it. If the same fix was applied before and the problem returned,\n"
            "say outright that the fix does not work."
        )
    else:
        rec_text = (
            "  NONE. Every item in this report is its first recorded occurrence.\n"
            "  No issue in this report has appeared in any previous report."
        )
        # Without this the model invents repeat failures that the history disproves.
        repeat_instruction = (
            "The recurrence check found NO repeat issues. Write exactly the single word\n"
            "\"None.\" under this heading and nothing else. Do NOT describe any issue as\n"
            "repeated, recurring, or happening again -- the report history proves otherwise."
        )

    flags_text = "\n".join(f"  - {f}" for f in flags) or "  (none)"

    prompt = f"""You are the RigVision Safety Review Engine auditing a submitted daily shift report from an remote drilling facility.

REPORT: {report['report_id']} | Date: {report['report_date']} | Shift: {report['shift']} | Supervisor: {report['supervisor']}

ITEMS AND REMEDIAL ACTIONS TAKEN:
{items_text}

SUPERVISOR NOTES: {report.get('notes') or '(none)'}

REPEAT ISSUES (detected from report history -- these are facts, not guesses):
{rec_text}

REPORT QUALITY ISSUES (automatically detected):
{flags_text}

Write a review of at most 400 words using exactly the four markdown headings below.
Write ONLY the heading and your analysis under it. Never restate these instructions
in your output.

## VERDICT
One or two sentences stating plainly whether this shift's response was adequate.

## REPEAT FAILURES
{repeat_instruction}

## GAPS IN THIS REPORT
Name the specific items a DGMS inspector could not audit, and say what is missing
from each.

## RECOMMENDED ACTIONS
A numbered list, highest impact first. Each action names who acts and by when.
Prefer permanent engineering or procedural controls over increased monitoring.

Be direct and concrete. Do not praise. Do not invent events that are not listed above."""

    narrative = _call_lm(prompt)
    if not recurring and not narrative.startswith("AI narrative unavailable"):
        narrative = _strip_fabricated_repeats(narrative)

    review = {
        "status":            "ready",
        "reviewed_at":       int(time.time()),
        "recurring_issues":  recurring,
        "quality_flags":     flags,
        "repeat_count":      len(recurring),
        "narrative":         narrative,
    }
    _update_report(r, report_id, {"review": review})
    log.info("Report %s reviewed: %d repeats, %d quality flags",
             report_id, len(recurring), len(flags))
    return review
