// mockZones.js
// Matches schema: rigvision:zones
// Written by Person C (sensor engine) at ~1Hz in production
// Status options: "normal" | "warning" | "critical"

export const mockZones = {
  zone_a: {
    status: "warning",
    warning_reason: "H2S concentration above safe threshold (>10 ppm)",
    temperature: 61.4,       // °C  — elevated but not critical
    vibration: 1.9,          // g RMS
    noise: 78.0,             // dB
    gas_h2s: 11.4,           // ppm — above 10ppm alert threshold
    pressure: 3.1,           // bar
    person_count: 2,
    ppe_violations: [
      "Person 1 missing safety vest",
      "Person 2 missing safety goggles",
    ],
    updated_at: Math.floor(Date.now() / 1000),
  },

  corridor: {
    status: "normal",
    warning_reason: null,
    temperature: 34.2,
    vibration: 0.4,
    noise: 61.0,
    gas_h2s: 0.8,
    pressure: 1.0,
    person_count: 1,
    ppe_violations: [],
    updated_at: Math.floor(Date.now() / 1000),
  },

  zone_b: {
    status: "critical",
    warning_reason: "Multiple PPE violations + noise exceeds 85dB limit",
    temperature: 43.7,
    vibration: 3.8,          // g RMS — above 3σ threshold
    noise: 91.2,             // dB — exceeds 85dB limit
    gas_h2s: 2.1,
    pressure: 4.6,
    person_count: 2,
    ppe_violations: [
      "Person 4 missing hardhat",
      "Person 4 missing safety vest",
      "Person 4 missing goggles",
    ],
    updated_at: Math.floor(Date.now() / 1000),
  },
}
