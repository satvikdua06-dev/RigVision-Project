"""Deterministic anomaly evaluation against resolved thresholds.

Pure comparison logic — no AI, no I/O. Takes a live reading and the threshold
record produced by ThresholdResolver and returns a severity plus an explainable
threshold_context entry for the Kafka alert payload.

Severity semantics match the existing pipeline (upper-bound breaches):
  value >= critical -> CRITICAL (rank 2)
  value >= warning  -> HIGH     (rank 1)
  otherwise         -> NORMAL   (rank 0)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class EvaluationResult:
    severity: str          # "NORMAL" | "HIGH" | "CRITICAL"
    rank: int              # 0 | 1 | 2
    is_breached: bool
    context: Optional[dict]  # threshold_context entry (only when breached)


def evaluate(value: float, threshold: dict) -> EvaluationResult:
    warning = threshold.get("warning")
    critical = threshold.get("critical")

    if critical is not None and value >= critical:
        severity, rank = "CRITICAL", 2
    elif warning is not None and value >= warning:
        severity, rank = "HIGH", 1
    else:
        return EvaluationResult("NORMAL", 0, False, None)

    normal = threshold.get("normal_range") or [None, None]
    context = {
        "value": value,
        "unit": threshold.get("unit"),
        "normal_min": normal[0],
        "normal_max": normal[1],
        "warning_min": warning,
        "critical_min": critical,
        "breach_level": severity,
        "sensor_id": threshold.get("sensor_id"),
        "metric": threshold.get("metric"),
        "selected_threshold_id": threshold.get("threshold_id"),
        "device_id": threshold.get("device_id"),
        "device_name": threshold.get("device_name"),
        "source_manual": threshold.get("source_manual"),
        "source_section": threshold.get("source_section"),
        "source_level": threshold.get("source_level"),
        "selection_reason": threshold.get("selection_reason"),
    }
    return EvaluationResult(severity, rank, True, context)
