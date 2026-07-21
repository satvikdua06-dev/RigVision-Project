"""Seed mock permit-to-work, shift, and maintenance context into Redis.

Called at compound_risk.py startup if keys are absent, so the demo works
immediately without any separate data-loading step.
"""

from __future__ import annotations

import json
import os
import time

import redis as redis_lib

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "") or None

PERMITS_KEY    = "rigvision:permits:active"
SHIFT_KEY      = "rigvision:shift:current"
MAINTENANCE_KEY = "rigvision:maintenance:active"


def _get_redis() -> redis_lib.Redis:
    return redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT,
                           password=REDIS_PASSWORD, decode_responses=True)


def seed_if_absent(r: redis_lib.Redis | None = None) -> None:
    if r is None:
        r = _get_redis()
    now = int(time.time())

    if not r.exists(PERMITS_KEY):
        permits = [
            {
                "permit_id": "PTW-2026-001",
                "type": "hot_work",
                "zone": "zone_a",
                "description": "Welding repair on mud pump discharge line — Section 4.2 of OISD-105",
                "workers": ["Vatsal", "Arnim"],
                "issued_by": "security.manager@rigvision.dev",
                "start_time": now - 3600,
                "end_time": now + 7200,
                "status": "active",
                "requires_gas_clear": True,
                "gas_clear_ppm": 5.0,
            },
            {
                "permit_id": "PTW-2026-002",
                "type": "confined_space",
                "zone": "zone_b",
                "description": "Inspection of mud tank internal baffles — DGMS Circular 2/2020",
                "workers": ["Ayan"],
                "issued_by": "security.manager@rigvision.dev",
                "start_time": now - 1800,
                "end_time": now + 5400,
                "status": "active",
                "requires_gas_clear": True,
                "gas_clear_ppm": 10.0,
            },
        ]
        r.set(PERMITS_KEY, json.dumps(permits))
        print("[mock_context] Seeded 2 permits into Redis")

    # Shift + maintenance seed COMPLIANT state. These keys are static -- nothing
    # updates them -- so seeding a reduced crew or unconfirmed LOTO created
    # violations (C011, C012) that could never clear and pinned the compliance
    # score at 15/100 permanently.
    if not r.exists(SHIFT_KEY):
        shift = {
            "shift": "day",
            "shift_number": 1,
            "start_time": now - 7200,
            "end_time": now + 21600,
            "crew_size": 6,
            "supervisor": "Vatsal",
            "is_reduced_crew": False,
            "fatigue_hours": 2,
        }
        r.set(SHIFT_KEY, json.dumps(shift))
        print("[mock_context] Seeded shift context into Redis")

    if not r.exists(MAINTENANCE_KEY):
        maintenance = [
            {
                "maintenance_id": "MNT-2026-001",
                "zone": "zone_a",
                "equipment": "mud_pump_a1",
                "type": "corrective",
                "description": "Bearing replacement on mud pump A1 — equipment must be isolated",
                "status": "in_progress",
                "start_time": now - 1800,
                "isolation_confirmed": True,
                "technician": "Arnim",
            },
        ]
        r.set(MAINTENANCE_KEY, json.dumps(maintenance))
        print("[mock_context] Seeded maintenance records into Redis")


if __name__ == "__main__":
    seed_if_absent()
    print("[mock_context] Done.")
