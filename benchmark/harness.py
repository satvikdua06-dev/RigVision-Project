"""Benchmark harness: compound risk engine vs single-sensor baseline.

Replays each labeled scenario step by step through BOTH detectors and reports
the metrics named in the evaluation criteria:

  * detection accuracy vs a single-sensor baseline  -> precision / recall
  * prediction lead time before incident threshold  -> seconds before incident_at
  * reduction in false negative rate                -> FN rate delta

Run standalone:
    python -m benchmark.harness
"""

from __future__ import annotations

import os
import sys
from statistics import mean
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmark import baseline
from benchmark.scenarios import SCENARIOS
from risk_engine.rules import evaluate as compound_evaluate


def _run_scenario(scenario: dict) -> dict:
    """Replay one scenario through both detectors. Returns per-scenario result."""
    ctx = scenario["context"]
    baseline_at: Optional[int] = None
    compound_at: Optional[int] = None
    baseline_evidence: List[str] = []
    compound_rules: List[str] = []

    for step in scenario["timeline"]:
        t, sensors = step["t"], step["sensors"]

        if baseline_at is None:
            hits = baseline.evaluate(sensors)
            if hits:
                baseline_at = t
                baseline_evidence = hits

        if compound_at is None:
            firings = compound_evaluate(
                sensors,
                ctx.get("persons", []),
                ctx.get("ppe", {}),
                ctx.get("permits", []),
                ctx.get("shift", {}),
                ctx.get("maintenance", []),
            )
            if firings:
                compound_at = t
                compound_rules = sorted({f.rule_id for f in firings})

        if baseline_at is not None and compound_at is not None:
            break

    incident_at = scenario.get("incident_at")
    hazardous = scenario["hazardous"]

    def lead(detected_at: Optional[int]) -> Optional[int]:
        if detected_at is None or incident_at is None:
            return None
        return max(0, incident_at - detected_at)

    return {
        "id": scenario["id"],
        "name": scenario["name"],
        "hazardous": hazardous,
        "expected_gap": scenario.get("expected_gap", False),
        "incident_at": incident_at,
        "rationale": scenario["rationale"],
        "modeled_on": scenario.get("modeled_on", ""),
        "baseline": {
            "detected": baseline_at is not None,
            "detected_at": baseline_at,
            "lead_time_s": lead(baseline_at),
            "evidence": baseline_evidence[:4],
        },
        "compound": {
            "detected": compound_at is not None,
            "detected_at": compound_at,
            "lead_time_s": lead(compound_at),
            "rules": compound_rules,
        },
    }


def _confusion(results: List[dict], key: str) -> dict:
    tp = sum(1 for r in results if r["hazardous"] and r[key]["detected"])
    fn = sum(1 for r in results if r["hazardous"] and not r[key]["detected"])
    fp = sum(1 for r in results if not r["hazardous"] and r[key]["detected"])
    tn = sum(1 for r in results if not r["hazardous"] and not r[key]["detected"])

    recall = tp / (tp + fn) if (tp + fn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    fn_rate = fn / (tp + fn) if (tp + fn) else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) else 0.0

    leads = [r[key]["lead_time_s"] for r in results
             if r["hazardous"] and r[key]["lead_time_s"] is not None]

    return {
        "true_positives": tp, "false_negatives": fn,
        "false_positives": fp, "true_negatives": tn,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "false_negative_rate": round(fn_rate, 4),
        "false_positive_rate": round(fp_rate, 4),
        "mean_lead_time_s": round(mean(leads), 1) if leads else None,
        "detections_with_lead": len(leads),
    }


def run() -> Dict[str, Any]:
    results = [_run_scenario(s) for s in SCENARIOS]

    base = _confusion(results, "baseline")
    comp = _confusion(results, "compound")

    hazardous = [r for r in results if r["hazardous"]]

    # The headline number: hazards the compound engine caught that a
    # conventional single-sensor alarm missed entirely.
    caught_only_by_compound = [
        r["id"] for r in hazardous
        if r["compound"]["detected"] and not r["baseline"]["detected"]
    ]
    caught_only_by_baseline = [
        r["id"] for r in hazardous
        if r["baseline"]["detected"] and not r["compound"]["detected"]
    ]
    missed_by_both = [
        r["id"] for r in hazardous
        if not r["compound"]["detected"] and not r["baseline"]["detected"]
    ]

    # Lead time compared only where BOTH detected, so the comparison is like-for-like.
    both = [r for r in hazardous
            if r["compound"]["lead_time_s"] is not None
            and r["baseline"]["lead_time_s"] is not None]
    earlier = [r["id"] for r in both
               if r["compound"]["lead_time_s"] > r["baseline"]["lead_time_s"]]
    later = [r["id"] for r in both
             if r["compound"]["lead_time_s"] < r["baseline"]["lead_time_s"]]
    lead_delta = (
        round(mean(r["compound"]["lead_time_s"] - r["baseline"]["lead_time_s"]
                   for r in both), 1)
        if both else None
    )

    fn_reduction = round(base["false_negative_rate"] - comp["false_negative_rate"], 4)
    fp_reduction = round(base["false_positive_rate"] - comp["false_positive_rate"], 4)

    return {
        "scenario_count": len(results),
        "hazardous_count": len(hazardous),
        "safe_count": len(results) - len(hazardous),
        "baseline": base,
        "compound": comp,
        "comparison": {
            "false_negative_rate_reduction": fn_reduction,
            "false_positive_rate_reduction": fp_reduction,
            "caught_only_by_compound": caught_only_by_compound,
            "caught_only_by_baseline": caught_only_by_baseline,
            "missed_by_both": missed_by_both,
            "compound_earlier_than_baseline": earlier,
            "compound_later_than_baseline": later,
            "mean_lead_time_delta_s": lead_delta,
            "lead_time_compared_on": len(both),
        },
        "results": results,
        "caveats": [
            "Scenarios are synthetic and were authored by this project; they model "
            "documented incident patterns but are not a validated external dataset.",
            "The baseline alarms at the WARNING bound (not critical), which maximises "
            "its recall and lead time -- the comparison is deliberately conservative.",
            "Neither detector applies temporal debouncing, so single-sample excursions "
            "are treated as detections for both.",
            "Corpus intentionally includes scenarios the compound engine fails "
            "(expected_gap) so the benchmark can expose false negatives.",
        ],
    }


def _fmt(v):
    return "-" if v is None else v


if __name__ == "__main__":
    import json as _json

    report = run()

    print("=" * 78)
    print("COMPOUND RISK BENCHMARK".center(78))
    print("=" * 78)
    print(f"{report['scenario_count']} scenarios "
          f"({report['hazardous_count']} hazardous / {report['safe_count']} safe)")
    print()

    hdr = f"{'':<28}{'BASELINE':>14}{'COMPOUND':>14}"
    print(hdr)
    print("-" * 78)
    for label, key in [
        ("recall (detection rate)", "recall"),
        ("precision", "precision"),
        ("F1", "f1"),
        ("FALSE NEGATIVE RATE", "false_negative_rate"),
        ("false positive rate", "false_positive_rate"),
        ("mean lead time (s)", "mean_lead_time_s"),
    ]:
        print(f"{label:<28}{_fmt(report['baseline'][key]):>14}"
              f"{_fmt(report['compound'][key]):>14}")

    c = report["comparison"]
    print()
    print("-" * 78)
    print(f"False negative rate reduction : {c['false_negative_rate_reduction']:+.2%}")
    print(f"False positive rate reduction : {c['false_positive_rate_reduction']:+.2%}")
    print(f"Caught ONLY by compound       : {c['caught_only_by_compound'] or 'none'}")
    print(f"Caught ONLY by baseline       : {c['caught_only_by_baseline'] or 'none'}")
    print(f"Missed by BOTH                : {c['missed_by_both'] or 'none'}")
    print(f"Compound detected earlier     : {c['compound_earlier_than_baseline'] or 'none'}")
    print(f"Compound detected later       : {c['compound_later_than_baseline'] or 'none'}")
    print(f"Mean lead-time delta (s)      : {_fmt(c['mean_lead_time_delta_s'])} "
          f"(compared on {c['lead_time_compared_on']} scenarios)")
    print()

    print("PER-SCENARIO".center(78, "-"))
    for r in report["results"]:
        tag = "HAZARD" if r["hazardous"] else "SAFE  "
        b, cp = r["baseline"], r["compound"]
        gap = "  [KNOWN GAP]" if r["expected_gap"] else ""
        print(f"{r['id']} {tag} {r['name'][:44]:<44}{gap}")
        print(f"    baseline: {'HIT @' + str(b['detected_at']) + 's' if b['detected'] else 'no alarm':<18}"
              f" lead={_fmt(b['lead_time_s'])}")
        print(f"    compound: {'HIT @' + str(cp['detected_at']) + 's' if cp['detected'] else 'no alarm':<18}"
              f" lead={_fmt(cp['lead_time_s'])}  rules={cp['rules'] or '-'}")
    print()
    print("CAVEATS".center(78, "-"))
    for cav in report["caveats"]:
        print(f"  * {cav}")
