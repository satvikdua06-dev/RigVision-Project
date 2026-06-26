// ── Dummy WebSocket simulation ────────────────────────────────────────────────
// Mimics the exact rigvision: Redis key schemas from contracts doc.
// Replace with real WebSocket connection in Phase 2.

export const INITIAL_PERSONS = [
  {
    id: 1, x: -3, y: 0, z: -2, zone: 'zone_a',
    posture: 'standing',
    ppe: { hardhat: true, vest: true, goggles: false },
    confidence: 0.94, cameras_visible: 2
  },
  {
    id: 2, x: 1, y: 0, z: 0, zone: 'corridor',
    posture: 'walking',
    ppe: { hardhat: false, vest: true, goggles: false },
    confidence: 0.87, cameras_visible: 1
  },
  {
    id: 3, x: 3.5, y: 0, z: 2, zone: 'zone_b',
    posture: 'bending',
    ppe: { hardhat: true, vest: true, goggles: true },
    confidence: 0.91, cameras_visible: 2
  },
]

export const INITIAL_ZONES = {
  zone_a: {
    label: 'Zone A — Drill Floor',
    position: [-3.5, 0, -2],
    size: [4, 0.1, 3],
    status: 'warning',
    warning_reason: 'Missing goggles detected',
    temperature: 48.2, vibration: 1.8, noise: 78, gas_h2s: 2.1, pressure: 4.2,
    person_count: 1, ppe_violations: ['Goggles missing on Person #1'],
    updated_at: Date.now()
  },
  corridor: {
    label: 'Corridor',
    position: [0.5, 0, 0],
    size: [3, 0.1, 2],
    status: 'critical',
    warning_reason: 'Hard hat missing + H2S elevated',
    temperature: 42.0, vibration: 0.6, noise: 65, gas_h2s: 11.4, pressure: 3.8,
    person_count: 1, ppe_violations: ['Hard hat missing on Person #2'],
    updated_at: Date.now()
  },
  zone_b: {
    label: 'Zone B — Pump Room',
    position: [3.5, 0, 2],
    size: [4, 0.1, 3],
    status: 'normal',
    warning_reason: null,
    temperature: 38.5, vibration: 2.4, noise: 71, gas_h2s: 0.8, pressure: 5.1,
    person_count: 1, ppe_violations: [],
    updated_at: Date.now()
  }
}

export const INITIAL_VIOLATIONS = [
  {
    id: 'v-001', rule_id: 'PPE-001', zone: 'corridor',
    severity: 'HIGH', message: 'Hard hat missing — Person #2 in Corridor',
    person_ids: [2], timestamp: Date.now() - 12000
  },
  {
    id: 'v-002', rule_id: 'ENV-003', zone: 'corridor',
    severity: 'CRITICAL', message: 'H₂S at 11.4 ppm — threshold exceeded (10 ppm)',
    person_ids: [], timestamp: Date.now() - 5000
  },
  {
    id: 'v-003', rule_id: 'PPE-003', zone: 'zone_a',
    severity: 'MEDIUM', message: 'Safety goggles missing — Person #1 in Zone A',
    person_ids: [1], timestamp: Date.now() - 30000
  },
]

// Movement paths for animation — each person cycles through these positions
export const MOVEMENT_PATHS = {
  1: [
    { x: -3, z: -2 }, { x: -2.5, z: -1.5 }, { x: -2, z: -1 },
    { x: -2.5, z: -2 }, { x: -3, z: -2.5 }, { x: -3.5, z: -2 },
  ],
  2: [
    { x: 1, z: 0 }, { x: 0.5, z: 0.2 }, { x: 0, z: 0 },
    { x: 0.5, z: -0.2 }, { x: 1, z: 0 }, { x: 1.5, z: 0.2 },
  ],
  3: [
    { x: 3.5, z: 2 }, { x: 4, z: 2.5 }, { x: 4.5, z: 2 },
    { x: 4, z: 1.5 }, { x: 3.5, z: 2 }, { x: 3, z: 2.5 },
  ],
}
