// mockViolations.js
// Matches schema: rigvision:violations:latest
// Written by Person C (compliance engine) in production
// Severity options: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"

export const mockViolations = [
  {
    id: "v-001",
    rule_id: "PPE-001",
    zone: "zone_b",
    severity: "HIGH",
    message: "Person 4 entered Zone B without hardhat, vest, or goggles",
    person_ids: [4],
    timestamp: Math.floor(Date.now() / 1000) - 45,   // 45 seconds ago
  },
  {
    id: "v-002",
    rule_id: "ENV-003",
    zone: "zone_b",
    severity: "MEDIUM",
    message: "Noise level in Zone B exceeds 85dB — hearing protection required",
    person_ids: [4, 5],
    timestamp: Math.floor(Date.now() / 1000) - 120,  // 2 minutes ago
  },
  {
    id: "v-003",
    rule_id: "PPE-001",
    zone: "zone_a",
    severity: "HIGH",
    message: "Person 1 missing safety vest in Zone A",
    person_ids: [1],
    timestamp: Math.floor(Date.now() / 1000) - 300,  // 5 minutes ago
  },
  {
    id: "v-004",
    rule_id: "PPE-002",
    zone: "zone_a",
    severity: "MEDIUM",
    message: "Person 2 missing safety goggles in Zone A",
    person_ids: [2],
    timestamp: Math.floor(Date.now() / 1000) - 410,  // ~7 minutes ago
  },
]
