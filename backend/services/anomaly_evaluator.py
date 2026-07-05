"""Deterministic anomaly evaluation against resolved thresholds.

Pure comparison logic — no AI, no I/O. Takes a live reading and the threshold
record produced by ThresholdResolver and returns a severity plus an explainable
threshold_context entry for the Kafka alert payload.

Breaches are bidirectional. Upper-bound breach (value too HIGH):
  value >= critical      -> CRITICAL (rank 2)
  value >= warning       -> HIGH     (rank 1)
Lower-bound breach (value too LOW — e.g. loss of pressure):
  value <= critical_low  -> CRITICAL (rank 2)
  value <= warning_low   -> HIGH     (rank 1)
otherwise                -> NORMAL   (rank 0)

`warning_low`/`critical_low` are optional; sensors with no low-side limits
(temperature, gas, noise, vibration today) behave exactly as before. The breach
direction ("high" | "low") is carried in the context so the KG query, LLM, and
UI can disambiguate which failure mode applies.
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
    direction: str = "high"  # "high" | "low" — which bound was breached


def evaluate(value: float, threshold: dict) -> EvaluationResult:
    warning = threshold.get("warning")
    critical = threshold.get("critical")
    warning_low = threshold.get("warning_low")
    critical_low = threshold.get("critical_low")

    # Criticals (either direction) take precedence over warnings.
    if critical is not None and value >= critical:
        severity, rank, direction = "CRITICAL", 2, "high"
    elif critical_low is not None and value <= critical_low:
        severity, rank, direction = "CRITICAL", 2, "low"
    elif warning is not None and value >= warning:
        severity, rank, direction = "HIGH", 1, "high"
    elif warning_low is not None and value <= warning_low:
        severity, rank, direction = "HIGH", 1, "low"
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
        "warning_low": warning_low,
        "critical_low": critical_low,
        "breach_level": severity,
        "breach_direction": direction,
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
    return EvaluationResult(severity, rank, True, context, direction)
