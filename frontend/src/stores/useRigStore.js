// useRigStore.js
// Central state store for the entire dashboard.
// In mock mode  → data is loaded from the mock files above
// In live mode  → WebSocket hook writes into this same store
// The 3D scene and UI panels only ever READ from this store — never from raw data directly.

import { create } from 'zustand'
import { mockPersons } from '../data/mockPersons'
import { mockZones }   from '../data/mockZones'
import { mockViolations } from '../data/mockViolations'

const MOCK_MODE = import.meta.env.VITE_MOCK_DATA === 'true'

const useRigStore = create((set, get) => ({

  // ─── persons ──────────────────────────────────────────────────────────────
  // Array of tracked_person objects (from rigvision:persons)
  persons: MOCK_MODE ? mockPersons : [],

  setPersons: (persons) => set({ persons }),

  getPersonById: (id) => get().persons.find((p) => p.id === id),

  // ─── zones ────────────────────────────────────────────────────────────────
  // Object keyed by zone id (from rigvision:zones)
  zones: MOCK_MODE ? mockZones : {
    zone_a:   null,
    corridor: null,
    zone_b:   null,
  },

  setZones: (zones) => set({ zones }),

  setZoneState: (zoneId, zoneState) =>
    set((s) => ({ zones: { ...s.zones, [zoneId]: zoneState } })),

  // ─── violations ───────────────────────────────────────────────────────────
  // Array of violation objects (from rigvision:violations:latest)
  violations: MOCK_MODE ? mockViolations : [],

  setViolations: (violations) => set({ violations }),

  addViolation: (v) =>
    set((s) => ({ violations: [v, ...s.violations].slice(0, 50) })), // keep last 50

  // ─── UI state ─────────────────────────────────────────────────────────────
  selectedZone: null,           // zone_id string | null
  selectedPersonId: null,       // person id | null
  anomalyReasoning: null,       // LLM response object | null (from Person D)
  isSidebarOpen: true,

  setSelectedZone:    (id)       => set({ selectedZone: id }),
  setSelectedPerson:  (id)       => set({ selectedPersonId: id }),
  setAnomalyReasoning:(reasoning)=> set({ anomalyReasoning: reasoning }),
  toggleSidebar:      ()         => set((s) => ({ isSidebarOpen: !s.isSidebarOpen })),

  // ─── helpers you'll use in the 3D scene ───────────────────────────────────
  // Maps zone status → color string for Three.js materials
  getZoneColor: (zoneId) => {
    const zone = get().zones[zoneId]
    if (!zone) return '#444444'
    return zone.status === 'critical' ? '#ef4444'   // red
         : zone.status === 'warning'  ? '#f59e0b'   // amber
         :                              '#22c55e'   // green
  },
}))

export default useRigStore
