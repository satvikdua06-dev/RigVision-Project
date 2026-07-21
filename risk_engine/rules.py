"""Compound risk correlation rules.

Each rule looks at a combination of sensor readings, permit-to-work status,
PPE compliance and maintenance activity to catch hazardous combinations that
no single sensor threshold would flag.

Every remaining rule is tied to a specific hazard: an open permit, an in-progress
maintenance job, or a PPE breach. The two rules that fired on generic sensor
combinations alone (R004 night-shift/reduced-crew, R007 3+ concurrent breaches)
were removed -- they fired on ambient conditions rather than an identifiable
hazard, so `shift` is no longer read by any rule.

Returns a list of RuleFiring objects — one per triggered rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RuleFiring:
    rule_id: str
    severity: str                         # "HIGH" | "CRITICAL"
    title: str
    description: str
    contributing_factors: List[str]
    zone: Optional[str] = None
    regulatory_refs: List[str] = field(default_factory=list)


def evaluate(
    sensors: dict,
    persons: list,
    ppe: dict,
    permits: list,
    shift: dict,          # unused since R004 was removed; kept for caller compatibility
    maintenance: list,
) -> List[RuleFiring]:
    """Apply all correlation rules. Returns only the rules that fire."""
    firings: List[RuleFiring] = []

    # ── Extract current readings ──────────────────────────────────────────────
    def sv(sid: str) -> float:
        return float((sensors.get(sid) or {}).get("value") or 0)

    gas_a      = sv("gas_a")
    gas_b      = sv("gas_b")
    temp_a     = sv("temp_a")
    temp_b     = sv("temp_b")
    vib_a      = sv("vib_a")
    vib_b      = sv("vib_b")
    pressure_a = sv("pressure_a")
    pressure_b = sv("pressure_b")
    max_gas    = max(gas_a, gas_b)
    max_temp   = max(temp_a, temp_b)

    active_permits  = [p for p in permits  if p.get("status") == "active"]
    active_maint    = [m for m in maintenance if m.get("status") == "in_progress"]
    hot_work        = [p for p in active_permits if p.get("type") == "hot_work"]
    confined_space  = [p for p in active_permits if p.get("type") == "confined_space"]

    ppe_violators = [
        pid for pid, st in ppe.items()
        if isinstance(st, dict)
        and (st.get("hat") == "missing" or st.get("glasses") == "missing")
    ]

    # ── R001: Gas + active hot-work permit (ignition risk) ───────────────────
    for permit in hot_work:
        zone = permit.get("zone", "")
        gas_val = gas_a if zone == "zone_a" else gas_b
        gas_limit = float(permit.get("gas_clear_ppm") or 5.0)
        if gas_val >= gas_limit:
            firings.append(RuleFiring(
                rule_id="R001",
                severity="CRITICAL",
                title="H2S/Flammable Gas + Active Hot Work Permit",
                description=(
                    f"Gas reading {gas_val:.1f} ppm in {zone} exceeds the {gas_limit:.0f} ppm "
                    f"gas-clear requirement for permit {permit['permit_id']}. "
                    f"Welding/cutting activities present an IMMEDIATE ignition risk."
                ),
                contributing_factors=[
                    f"gas={gas_val:.1f}ppm (limit {gas_limit:.0f}ppm)",
                    f"permit={permit['permit_id']} (hot_work, {zone})",
                    f"workers={permit.get('workers', [])}",
                ],
                zone=zone,
                regulatory_refs=["OISD-105 Cl.4.2", "DGMS Circular 3/2016 — Hot Work in Hazardous Areas"],
            ))

    # ── R002: PPE violation + elevated gas ────────────────────────────────────
    if ppe_violators and max_gas >= 3.0:
        sev = "CRITICAL" if max_gas >= 10 else "HIGH"
        firings.append(RuleFiring(
            rule_id="R002",
            severity=sev,
            title="PPE Non-Compliance in Elevated Gas Environment",
            description=(
                f"{len(ppe_violators)} personnel detected without required PPE "
                f"while H2S concentration is {max_gas:.1f} ppm. "
                f"IDLH threshold for H2S is 50 ppm; TLV-TWA is 1 ppm."
            ),
            contributing_factors=[
                f"ppe_violators={ppe_violators}",
                f"gas={max_gas:.1f}ppm",
            ],
            regulatory_refs=["OISD-155 Cl.6.1", "Factory Act 1948 §36 — PPE provision"],
        ))

    # ── R003: Vibration spike during active maintenance (LOTO failure risk) ──
    # Threshold matches zone_definitions.json vibration warning (5 g_rms)
    for maint in active_maint:
        zone = maint.get("zone", "")
        vib_val = vib_a if zone == "zone_a" else 0.0
        if vib_val >= 5.0 and not maint.get("isolation_confirmed"):
            firings.append(RuleFiring(
                rule_id="R003",
                severity="CRITICAL",
                title="Equipment Running During Active Maintenance (LOTO Breach Risk)",
                description=(
                    f"Vibration {vib_val:.2f} g_rms detected on equipment in {zone} "
                    f"while maintenance job {maint['maintenance_id']} is in progress "
                    f"and isolation has NOT been confirmed. Possible LOTO failure."
                ),
                contributing_factors=[
                    f"vib_a={vib_val:.2f}g_rms",
                    f"maintenance={maint['maintenance_id']}",
                    f"isolation_confirmed=False",
                ],
                zone=zone,
                regulatory_refs=["OISD-105 Cl.7.3 — LOTO procedures", "DGMS Circular 2/2020"],
            ))

    # ── R005: Temperature spike + pressure drop + active work ─────────────────
    # temp critical=65°C, pressure warning_low=4 bar from zone_definitions.json
    if max_temp >= 65 and pressure_a <= 4.0 and (hot_work or active_maint):
        firings.append(RuleFiring(
            rule_id="R005",
            severity="CRITICAL",
            title="High Temperature + Pressure Loss During Active Permit Work",
            description=(
                f"Temperature {max_temp:.1f}°C combined with pressure {pressure_a:.1f} bar "
                f"(normal ≥5 bar) during active work — possible seal/gasket failure "
                f"leading to hydrocarbon release under thermal stress."
            ),
            contributing_factors=[
                f"max_temp={max_temp:.1f}°C",
                f"pressure_a={pressure_a:.1f}bar",
                f"active_permits={[p['permit_id'] for p in hot_work]}",
                f"active_maintenance={[m['maintenance_id'] for m in active_maint]}",
            ],
            regulatory_refs=["OISD-118 Cl.5.2 — Pressure system integrity"],
        ))

    # ── R006: Gas exceeds confined-space entry limit with permit active ───────
    for permit in confined_space:
        zone = permit.get("zone", "")
        gas_val = gas_a if zone == "zone_a" else gas_b
        gas_limit = float(permit.get("gas_clear_ppm") or 10.0)
        if gas_val >= gas_limit:
            firings.append(RuleFiring(
                rule_id="R006",
                severity="CRITICAL",
                title="Gas Exceeds Confined Space Entry Limit — Personnel at Risk",
                description=(
                    f"Gas {gas_val:.1f} ppm in {zone} exceeds the "
                    f"{gas_limit:.0f} ppm confined-space entry limit for "
                    f"permit {permit['permit_id']}. "
                    f"Workers {permit.get('workers',[])} may be inside — immediate rescue protocol required."
                ),
                contributing_factors=[
                    f"gas_{zone[-1]}={gas_val:.1f}ppm",
                    f"entry_limit={gas_limit:.0f}ppm",
                    f"permit={permit['permit_id']}",
                    f"workers_at_risk={permit.get('workers',[])}",
                ],
                zone=zone,
                regulatory_refs=["OISD-105 Cl.6.4 — Confined space entry", "DGMS Circ.2/2020"],
            ))

    # ── R_PTW: Permit-scoped sensor condition breach ──────────────────────────
    # Fires when a reading exceeds the limits the permit issuer set at creation.
    # These limits are only active while the permit is open — they disappear on close/expiry.
    for permit in active_permits:
        p_zone  = permit.get("zone", "")
        limits  = permit.get("sensor_limits") or {}
        if not limits:
            continue
        gas_val  = gas_a      if p_zone == "zone_a" else gas_b
        temp_val = temp_a     if p_zone == "zone_a" else temp_b
        vib_val  = vib_a      if p_zone == "zone_a" else vib_b
        pres_val = pressure_a if p_zone == "zone_a" else pressure_b

        # Hot-work and confined-space permits already have a dedicated gas rule
        # (R001 / R006), and create_permit derives gas_clear_ppm FROM
        # sensor_limits.gas -- so checking gas here too would raise two CRITICAL
        # alerts for one breach of one number. R_PTW covers gas only for permit
        # types with no gas rule of their own (electrical, excavation).
        gas_covered_elsewhere = permit.get("type") in ("hot_work", "confined_space")

        breaches = []
        if "gas" in limits and not gas_covered_elsewhere and gas_val >= float(limits["gas"]):
            breaches.append(f"H₂S {gas_val:.1f} ppm (permit limit {float(limits['gas']):.1f} ppm)")
        if "temperature" in limits and temp_val >= float(limits["temperature"]):
            breaches.append(f"Temp {temp_val:.1f}°C (permit limit {float(limits['temperature']):.1f}°C)")
        if "vibration" in limits and vib_val >= float(limits["vibration"]):
            breaches.append(f"Vib {vib_val:.2f} g_rms (permit limit {float(limits['vibration']):.2f})")
        if "pressure_low" in limits and pres_val <= float(limits["pressure_low"]):
            breaches.append(f"Pressure {pres_val:.1f} bar (permit minimum {float(limits['pressure_low']):.1f} bar)")

        if breaches:
            firings.append(RuleFiring(
                rule_id="R_PTW",
                severity="CRITICAL",
                title=f"Permit Condition Breached — {permit['permit_id']}",
                description=(
                    f"Sensor readings in {p_zone} have exceeded the limits specified when "
                    f"permit {permit['permit_id']} ({permit.get('type','').replace('_',' ').upper()}) "
                    f"was issued: {'; '.join(breaches)}. "
                    f"Work must stop immediately and the permit must be reviewed."
                ),
                contributing_factors=breaches + [f"permit={permit['permit_id']}"],
                zone=p_zone,
                regulatory_refs=["OISD-105 Cl.4 — Permit-to-Work conditions", "DGMS Circular 3/2016"],
            ))

    return firings


def aggregate_severity(firings: List[RuleFiring]) -> str:
    if any(f.severity == "CRITICAL" for f in firings):
        return "CRITICAL"
    if firings:
        return "HIGH"
    return "NORMAL"


# Static reference metadata for the RULE LEGEND UI. Kept next to the rules
# themselves (rather than duplicated in the frontend) so a future edit to a
# rule's condition is visible right next to the text that describes it.
# NOTE: this is documentation, not logic -- update it by hand when a rule's
# trigger condition changes above.
RULE_REGISTRY = [
    {
        "code": "R001", "severity": "CRITICAL",
        "title": "H2S/Flammable Gas + Active Hot Work Permit",
        "trigger": "Active hot-work permit and gas reading at/above that permit's gas-clear limit.",
        "regulation": "OISD-105 Cl.4.2",
    },
    {
        "code": "R002", "severity": "HIGH / CRITICAL",
        "title": "PPE Non-Compliance in Elevated Gas Environment",
        "trigger": "A worker missing required PPE while H2S >= 3 ppm (CRITICAL if H2S >= 10 ppm).",
        "regulation": "OISD-155 Cl.6.1",
    },
    {
        "code": "R003", "severity": "CRITICAL",
        "title": "Equipment Running During Active Maintenance (LOTO Breach Risk)",
        "trigger": "Vibration >= 5 g_rms on equipment with an in-progress maintenance job whose LOTO isolation is unconfirmed.",
        "regulation": "OISD-105 Cl.7.3",
    },
    {
        "code": "R005", "severity": "CRITICAL",
        "title": "High Temperature + Pressure Loss During Active Permit Work",
        "trigger": "Temperature >= 65C and pressure <= 4 bar at the same time during active permitted work.",
        "regulation": "OISD-118 Cl.5.2",
    },
    {
        "code": "R006", "severity": "CRITICAL",
        "title": "Gas Exceeds Confined Space Entry Limit",
        "trigger": "Active confined-space permit and gas reading at/above that permit's entry limit.",
        "regulation": "OISD-105 Cl.6.4",
    },
    {
        "code": "R_PTW", "severity": "CRITICAL",
        "title": "Permit Condition Breached",
        "trigger": "Any sensor limit set on an active permit (temperature, vibration, low pressure -- and gas for permit types with no dedicated gas rule) is breached.",
        "regulation": "OISD-105 Cl.4",
    },
]
