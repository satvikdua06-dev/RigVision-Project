"""Labeled scenario corpus for compound-risk benchmarking.

WHAT THIS IS
------------
A set of hand-authored, time-stepped rig states with ground-truth labels, used
to measure the compound risk engine against a conventional single-sensor
threshold alarm.

HONESTY CONSTRAINTS -- read before quoting any number produced from this file:

1. These scenarios are SYNTHETIC. They are modeled on documented incident
   patterns (Visakhapatnam coke oven Jan-2025 gas accumulation, OISD/DGMS
   near-miss archetypes) but they are NOT a validated external dataset and were
   authored by the same project that implements the rules being measured.
   Numbers from this harness demonstrate mechanism, not field performance.

2. Every scenario carries a `rationale` explaining WHY it is labeled hazardous
   or safe. The labels are the foundation of every metric here, so they are
   written to be audited and argued with.

3. The corpus deliberately includes scenarios the current rules FAIL
   (`expected_gap: True`). A benchmark on which the system scores 100% is a
   benchmark that is measuring nothing.

LABEL DEFINITION
----------------
hazardous = True  -> a harm pathway exists and intervention is required before
                     `incident_at`. Not merely "a threshold was crossed".
hazardous = False -> no harm pathway. Thresholds may still trip; these cases
                     exist to measure nuisance alarms (false positives).

`incident_at` is the second at which the condition becomes injurious/
catastrophic. Detection lead time is measured backwards from it.

Sensor values follow the SCADA ids used everywhere else (gas_a, temp_a, ...).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Baseline context blocks reused across scenarios -------------------------------

_SHIFT_NORMAL = {"shift": "day", "shift_number": 1, "crew_size": 6,
                 "is_reduced_crew": False, "fatigue_hours": 2}

_PPE_OK = {"person_present": True, "hat": "present", "glasses": "present"}
_PPE_HAT_MISSING = {"person_present": True, "hat": "missing", "glasses": "present"}


def _permit(ptype: str, zone: str = "zone_a", *, gas_clear: float = 5.0,
            limits: Dict[str, float] | None = None) -> dict:
    return {
        "permit_id": f"PTW-BENCH-{ptype.upper()[:4]}",
        "type": ptype,
        "zone": zone,
        "status": "active",
        "description": f"benchmark {ptype}",
        "workers": ["W1"],
        "requires_gas_clear": True,
        "gas_clear_ppm": gas_clear,
        "sensor_limits": limits or {},
    }


def _maint(*, isolation: bool) -> dict:
    return {
        "maintenance_id": "MNT-BENCH-001",
        "zone": "zone_a",
        "equipment": "mud_pump_a1",
        "status": "in_progress",
        "isolation_confirmed": isolation,
        "description": "benchmark maintenance",
    }


def _ramp(start: float, end: float, steps: int) -> List[float]:
    """Linear ramp inclusive of both endpoints."""
    if steps <= 1:
        return [end]
    step = (end - start) / (steps - 1)
    return [round(start + step * i, 3) for i in range(steps)]


def _timeline(step_seconds: int, **series: List[float]) -> List[dict]:
    """Build [{t, sensors{...}}] from named sensor series of equal length."""
    length = len(next(iter(series.values())))
    out = []
    for i in range(length):
        out.append({
            "t": i * step_seconds,
            "sensors": {sid: {"value": vals[i]} for sid, vals in series.items()},
        })
    return out


# Static filler so every timeline carries a full sensor set.
def _flat(value: float, n: int) -> List[float]:
    return [value] * n


N = 21              # steps per scenario
STEP = 30           # seconds per step -> 10 minute window


SCENARIOS: List[Dict[str, Any]] = [

    # ── HAZARDOUS ────────────────────────────────────────────────────────────
    {
        "id": "SC-001",
        "name": "Gas accumulation during active hot work",
        "modeled_on": "Visakhapatnam Steel Plant coke oven battery, Jan 2025 - "
                      "entrapped gas accumulated while work proceeded; sensor data "
                      "existed but was not connected to permit state.",
        "hazardous": True,
        "incident_at": 600,
        "rationale": "Hot work (ignition source) proceeding while H2S climbs past the "
                     "permit's 5 ppm gas-clear limit. Harm pathway is ignition/"
                     "toxic exposure. OISD-105 Cl.4.2 forbids hot work at/above the "
                     "gas-clear threshold, so intervention is required well before "
                     "the zone-level 10 ppm warning is reached.",
        "context": {
            "permits": [_permit("hot_work", gas_clear=5.0)],
            "shift": _SHIFT_NORMAL, "maintenance": [], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_ramp(1.0, 14.0, N), temp_a=_flat(42.0, N),
            vib_a=_flat(2.1, N), pressure_a=_flat(9.0, N), noise_a=_flat(78.0, N),
        ),
    },
    {
        "id": "SC-002",
        "name": "Confined space entry with job-specific gas limit",
        "modeled_on": "OISD-105 Cl.5.1 confined space archetype; permit issuer sets a "
                      "stricter limit than the zone default for the specific job.",
        "hazardous": True,
        "incident_at": 570,
        "rationale": "Workers inside a confined space while gas rises past the 6 ppm "
                     "limit the permit issuer set for this job. Escape is restricted, "
                     "so harm onset is faster than an open-area exposure. Zone warning "
                     "(10 ppm) is not a safe trigger point for personnel already inside.",
        "context": {
            "permits": [_permit("confined_space", zone="zone_a", gas_clear=6.0,
                                limits={"gas": 6.0})],
            "shift": _SHIFT_NORMAL, "maintenance": [], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_ramp(0.5, 13.0, N), temp_a=_flat(40.0, N),
            vib_a=_flat(1.8, N), pressure_a=_flat(9.5, N), noise_a=_flat(75.0, N),
        ),
    },
    {
        "id": "SC-003",
        "name": "PPE breach in a sub-threshold gas environment",
        "modeled_on": "OISD-155 Cl.6.1 / Factory Act Sec.36. H2S TLV-TWA is 1 ppm; "
                      "unprotected exposure matters far below the 10 ppm zone alarm.",
        "hazardous": True,
        "incident_at": 600,
        "rationale": "A worker without a hard hat is in a zone where H2S sits at "
                     "3-4 ppm. No single sensor ever leaves its normal band, so a "
                     "conventional alarm stays silent for the entire window, yet an "
                     "unprotected person is accumulating exposure above TLV-TWA. This "
                     "is the archetypal compound-only hazard.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL, "maintenance": [],
            "ppe": _PPE_HAT_MISSING, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_ramp(2.0, 4.2, N), temp_a=_flat(44.0, N),
            vib_a=_flat(2.4, N), pressure_a=_flat(8.8, N), noise_a=_flat(80.0, N),
        ),
    },
    {
        "id": "SC-004",
        "name": "Equipment live during maintenance with unconfirmed isolation",
        "modeled_on": "OISD-105 Cl.7.3 LOTO archetype; NM-style event where vibration "
                      "indicated the machine was running while a technician worked on it.",
        "hazardous": True,
        "incident_at": 540,
        "rationale": "Maintenance is in progress with LOTO isolation NOT confirmed while "
                     "vibration indicates the equipment is turning. Harm pathway is "
                     "entanglement/crush on a machine believed to be dead.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL,
            "maintenance": [_maint(isolation=False)], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(1.2, N), temp_a=_flat(47.0, N),
            vib_a=_ramp(1.0, 7.4, N), pressure_a=_flat(9.1, N), noise_a=_flat(84.0, N),
        ),
    },
    {
        "id": "SC-005",
        "name": "Permit-scoped temperature limit breach (hot work near sensitive plant)",
        "modeled_on": "Permit-to-work practice: the issuer sets a limit tighter than the "
                      "zone default because of what is being worked on.",
        "hazardous": True,
        "incident_at": 600,
        "rationale": "The permit for this job caps temperature at 45 C because of adjacent "
                     "sensitive equipment - stricter than the 50 C zone warning. Exceeding "
                     "the permit condition invalidates the safe-work basis, so intervention "
                     "is required before the generic zone alarm would sound.",
        "context": {
            "permits": [_permit("hot_work", gas_clear=5.0, limits={"temperature": 45.0})],
            "shift": _SHIFT_NORMAL, "maintenance": [], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(1.0, N), temp_a=_ramp(30.0, 56.0, N),
            vib_a=_flat(2.0, N), pressure_a=_flat(9.0, N), noise_a=_flat(79.0, N),
        ),
    },
    {
        "id": "SC-006",
        "name": "Seal degradation: thermal rise with pressure loss during permit work",
        "modeled_on": "OISD-118 Cl.5.2 - simultaneous high temperature and pressure loss "
                      "treated as suspected hydrocarbon release.",
        "hazardous": True,
        "incident_at": 600,
        "rationale": "Temperature climbing while pressure falls, with permitted work in the "
                     "area, is the signature of seal/gasket failure and possible hydrocarbon "
                     "release. Note the single-sensor alarm DOES trip early here (temp passes "
                     "50 C well before the combination completes) - this scenario is included "
                     "specifically because the baseline is expected to win on raw lead time.",
        "context": {
            "permits": [_permit("hot_work", gas_clear=5.0)],
            "shift": _SHIFT_NORMAL, "maintenance": [], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(1.5, N), temp_a=_ramp(38.0, 72.0, N),
            vib_a=_flat(2.2, N), pressure_a=_ramp(9.0, 3.2, N), noise_a=_flat(81.0, N),
        ),
    },
    {
        "id": "SC-007",
        "name": "Confined space occupancy at TWA-level gas (known gap)",
        "modeled_on": "OISD-105 Cl.5.1 / OISD-155: H2S TLV-TWA is 1 ppm for continuous "
                      "occupancy, far below any zone alarm bound.",
        "hazardous": True,
        "incident_at": 600,
        "expected_gap": True,
        "rationale": "Personnel inside a confined space with gas at 2-3 ppm: above the 1 ppm "
                     "TWA for sustained occupancy, but below both the zone warning (10) and "
                     "this permit's gas-clear limit (10). NEITHER detector is expected to "
                     "fire. Included deliberately to expose a real false negative in the "
                     "compound engine - the compliance layer (C010) catches this, the "
                     "real-time rules do not.",
        "context": {
            "permits": [_permit("confined_space", gas_clear=10.0)],
            "shift": _SHIFT_NORMAL, "maintenance": [], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_ramp(1.8, 3.1, N), temp_a=_flat(41.0, N),
            vib_a=_flat(1.6, N), pressure_a=_flat(9.2, N), noise_a=_flat(74.0, N),
        ),
    },

    # ── SAFE (false-positive / nuisance-alarm tests) ─────────────────────────
    {
        "id": "SC-100",
        "name": "Routine operations, all parameters nominal",
        "modeled_on": "Steady-state baseline.",
        "hazardous": False,
        "incident_at": None,
        "rationale": "Everything inside normal bands, no permits, no maintenance, PPE "
                     "compliant. Any alarm from either detector is a false positive.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL, "maintenance": [],
            "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(1.1, N), temp_a=_flat(43.0, N),
            vib_a=_flat(2.0, N), pressure_a=_flat(9.0, N), noise_a=_flat(77.0, N),
        ),
    },
    {
        "id": "SC-101",
        "name": "Routine thermal load above warning bound, no harm pathway",
        "modeled_on": "Classic nuisance alarm: process runs warm during normal duty.",
        "hazardous": False,
        "incident_at": None,
        "rationale": "Temperature sits at 52-54 C, above the 50 C WARNING bound but far "
                     "below the 65 C critical bound, with no permit, no maintenance, no "
                     "personnel exposure and no pressure anomaly. A warning bound means "
                     "'monitor', not 'intervene'. A conventional alarm trips here and "
                     "contributes to alarm fatigue; there is no harm pathway to act on.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL, "maintenance": [],
            "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(0.9, N), temp_a=_ramp(50.5, 54.0, N),
            vib_a=_flat(2.3, N), pressure_a=_flat(8.7, N), noise_a=_flat(79.0, N),
        ),
    },
    {
        "id": "SC-102",
        "name": "Elevated vibration with LOTO isolation confirmed",
        "modeled_on": "Maintenance performed correctly - isolation verified before work.",
        "hazardous": False,
        "incident_at": None,
        "rationale": "Vibration crosses the 5 g_rms warning bound on adjacent running plant "
                     "while a maintenance job proceeds with isolation CONFIRMED. The "
                     "controls that make this safe are in place; the distinguishing fact "
                     "is the isolation flag, which a bare vibration threshold cannot see.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL,
            "maintenance": [_maint(isolation=True)], "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_flat(1.0, N), temp_a=_flat(45.0, N),
            vib_a=_ramp(4.6, 5.9, N), pressure_a=_flat(9.0, N), noise_a=_flat(86.0, N),
        ),
    },
    {
        "id": "SC-103",
        "name": "Gas below action level with full PPE and no permits",
        "modeled_on": "Background H2S in a sour-service area during normal duty.",
        "hazardous": False,
        "incident_at": None,
        "rationale": "Gas at 3-4 ppm with all PPE worn, no ignition source, no permit and "
                     "no confined space. Note this is the SAME gas band as SC-003; the "
                     "only difference is PPE compliance. The pair tests whether a detector "
                     "distinguishes exposure risk from mere concentration.",
        "context": {
            "permits": [], "shift": _SHIFT_NORMAL, "maintenance": [],
            "ppe": _PPE_OK, "persons": [],
        },
        "timeline": _timeline(
            STEP,
            gas_a=_ramp(3.0, 4.1, N), temp_a=_flat(44.0, N),
            vib_a=_flat(2.2, N), pressure_a=_flat(8.9, N), noise_a=_flat(78.0, N),
        ),
    },
]


def hazardous_scenarios() -> List[dict]:
    return [s for s in SCENARIOS if s["hazardous"]]


def safe_scenarios() -> List[dict]:
    return [s for s in SCENARIOS if not s["hazardous"]]
