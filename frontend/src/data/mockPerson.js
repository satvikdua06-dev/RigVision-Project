// mockPersons.js
// Matches schema: rigvision:persons
// Written by Person B (CV pipeline) at ~10Hz in production
// Zone options:  "zone_a" | "corridor" | "zone_b" | "unknown"
// Posture options: "standing" | "sitting" | "bending" | "lying" | "unknown"

export const mockPersons = [
  {
    id: 1,
    x: 3.2,
    y: 0.0,
    z: 2.5,
    zone: "zone_a",
    posture: "standing",
    ppe: {
      hardhat: true,
      vest: false,       // ← missing vest, should trigger PPE-001 violation
      goggles: true,
    },
    confidence: 0.93,
    cameras_visible: 2,
  },
  {
    id: 2,
    x: 8.7,
    y: 0.0,
    z: 1.1,
    zone: "zone_a",
    posture: "bending",
    ppe: {
      hardhat: true,
      vest: true,
      goggles: false,    // ← missing goggles
    },
    confidence: 0.87,
    cameras_visible: 1,
  },
  {
    id: 3,
    x: 14.0,
    y: 0.0,
    z: 4.3,
    zone: "corridor",
    posture: "standing",
    ppe: {
      hardhat: true,
      vest: true,
      goggles: true,     // ← fully compliant
    },
    confidence: 0.95,
    cameras_visible: 2,
  },
  {
    id: 4,
    x: 20.5,
    y: 0.0,
    z: 6.8,
    zone: "zone_b",
    posture: "sitting",
    ppe: {
      hardhat: false,    // ← missing hardhat, HIGH severity violation
      vest: false,       // ← missing vest too
      goggles: false,
    },
    confidence: 0.78,
    cameras_visible: 1,
  },
  {
    id: 5,
    x: 22.1,
    y: 0.0,
    z: 3.9,
    zone: "zone_b",
    posture: "standing",
    ppe: {
      hardhat: true,
      vest: true,
      goggles: true,
    },
    confidence: 0.91,
    cameras_visible: 2,
  },
]
