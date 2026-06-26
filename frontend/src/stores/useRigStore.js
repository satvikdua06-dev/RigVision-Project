import { create } from 'zustand'
let mockInterval = null;
export const useRigStore = create((set, get) => ({
  // 1. Initial State (Empty, just like when an app first loads)
  persons: [],
  zones: {
    zone_a: { status: 'normal', temperature: 25, vibration: 0, noise: 40, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    corridor: { status: 'normal', temperature: 22, vibration: 0, noise: 35, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_b: { status: 'normal', temperature: 26, vibration: 0, noise: 45, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() }
  },
  violations: [],
  selectedPerson: null,
  selectedZone: null,
  sidebarTab: 'zones',

  // UI Actions
  selectPerson: (id) => set({ selectedPerson: id, selectedZone: null }),
  selectZone: (id) => set({ selectedZone: id, selectedPerson: null }),
  clearSelection: () => set({ selectedPerson: null, selectedZone: null }),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),

  // ----------------------------------------------------------------------
  // 2. THE WEBSOCKET CONNECTION
  // ----------------------------------------------------------------------
  connectToBackend: () => {
    // 🔮 FUTURE REAL CODE (Leave this commented out for when backend is ready)
    /*
    const ws = new WebSocket('ws://your-backend-url')
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'rigvision:persons') set({ persons: data.payload })
      if (data.type === 'rigvision:zones') set({ zones: data.payload })
      if (data.type === 'rigvision:violations:latest') set({ violations: data.payload })
    }
    */
    if (mockInterval) {
      clearInterval(mockInterval);
    }
    // 🛠️ CURRENT MOCK CODE (Simulates the 10Hz Redis stream)
    let time = 0;
    
    mockInterval = setInterval(() => {
      time += 0.1;
      
      // Generate mock persons strictly adhering to your 'tracked_person' schema
// Inside useRigStore.js -> connectToBackend -> setInterval
      
      const mockPersons = [
        {
          id: 1,
          // 👇 CHANGED: Base X is now -22 so they spawn in Zone A
          // Adding the Math.sin lets them pace back and forth inside the room
          x: -22 + Math.sin(time) * 3, 
          y: 0,
          z: -3,
          zone: "zone_a",
          posture: "standing",
          ppe: { hardhat: true, vest: true, goggles: true },
          confidence: 0.95,
          cameras_visible: 2
        },
        {
          id: 2,
          // 👇 CHANGED: Base X is now 0 so they spawn in the Corridor
          x: 0, 
          y: 0,
          z: Math.cos(time * 0.5) * 5, // Walking along the Z axis of the corridor
          zone: "corridor",
          posture: "walking",
          ppe: { hardhat: true, vest: false, goggles: true }, 
          confidence: 0.88,
          cameras_visible: 1
        },
        {
          id: 3,
          // 👇 CHANGED: Base X is now 22 so they spawn in Zone B
          x: 22, 
          y: 0,
          z: 2 + Math.cos(time) * 2, // Slight pacing in Zone B
          zone: "zone_b",
          posture: "bending",
          ppe: { hardhat: false, vest: false, goggles: false }, 
          confidence: 0.72,
          cameras_visible: 3
        }
      ];

      // Update the store! 
      // Because Scene3D uses useFrame to interpolate toward these coordinates,
      // updating this at 10Hz will make the humans walk around smoothly in 3D.
      set({ persons: mockPersons });
      
    }, 100); // 100ms = 10Hz
  }
}))