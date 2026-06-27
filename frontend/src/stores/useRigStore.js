import { create } from 'zustand'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
const WS_URL = `ws://${host}:8000/ws/realtime`;

export const useRigStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────
  persons: [],
  zones: {
    zone_a: { status: 'normal', temperature: 25, vibration: 0, noise: 40, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    corridor: { status: 'normal', temperature: 22, vibration: 0, noise: 35, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_b: { status: 'normal', temperature: 26, vibration: 0, noise: 45, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() }
  },
  violations: [],
  connected: false,
  
  // Selection & UI State
  selectedPerson: null,
  selectedZone: null,
  sidebarTab: 'zones',
  showSensors: true,
  showAvatars: true,

  // ── WebSocket ──────────────────────────────────────────
  _ws: null,
  _reconnectTimer: null,

  connectToBackend: () => {
    const state = get();
    if (state._ws) return; // Already connected

    console.log('[ws] Connecting to', WS_URL);
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[ws] Connected');
      set({ connected: true, _ws: ws });
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'realtime_update') {
          // Keep existing keys if payload drops them
          set((state) => ({
            persons: data.persons || state.persons,
            zones: data.zones || state.zones,
            violations: data.violations || state.violations,
          }));
        } else {
          if (data.type === 'rigvision:persons') set({ persons: data.payload })
          if (data.type === 'rigvision:zones') set({ zones: data.payload })
          if (data.type === 'rigvision:violations:latest') set({ violations: data.payload })
        }
      } catch (err) {
        console.error('[ws] Parse error:', err);
      }
    };

    ws.onclose = () => {
      console.log('[ws] Disconnected. Reconnecting in 2s...');
      set({ connected: false, _ws: null });

      // Auto-reconnect after 2 seconds
      const timer = setTimeout(() => {
        get().connectToBackend();
      }, 2000);
      set({ _reconnectTimer: timer });
    };

    ws.onerror = (err) => {
      console.error('[ws] Error:', err);
      ws.close();
    };

    set({ _ws: ws });
  },

  disconnect: () => {
    const state = get();
    if (state._reconnectTimer) {
      clearTimeout(state._reconnectTimer);
    }
    if (state._ws) {
      state._ws.close();
    }
    set({ connected: false, _ws: null, _reconnectTimer: null });
  },

  // ── UI Actions ─────────────────────────────────────────
  selectPerson: (id) => set({ selectedPerson: id, selectedZone: null }),
  selectZone: (id) => set({ selectedZone: id, selectedPerson: null }),
  clearSelection: () => set({ selectedPerson: null, selectedZone: null }),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  toggleSensors: () => set((state) => ({ showSensors: !state.showSensors })),
  toggleAvatars: () => set((state) => ({ showAvatars: !state.showAvatars })),
}))