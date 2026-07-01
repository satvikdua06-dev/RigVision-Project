import { create } from 'zustand'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = import.meta.env.VITE_WS_URL || `${wsProtocol}//${host}:8000/ws/realtime`;
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`;

export const useRigStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────
  persons: [],
  zones: {
    zone_a: { status: 'normal', temperature: 25, vibration: 0, noise: 40, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    corridor: { status: 'normal', temperature: 22, vibration: 0, noise: 35, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_b: { status: 'normal', temperature: 26, vibration: 0, noise: 45, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_a_f1: { status: 'normal', temperature: 25, vibration: 0, noise: 40, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    corridor_f1: { status: 'normal', temperature: 22, vibration: 0, noise: 35, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_b_f1: { status: 'normal', temperature: 26, vibration: 0, noise: 45, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() }
  },
  diagnostics: [],
  connected: false,
  // Selection & UI State
  selectedPerson: null,
  selectedZone: null,
  sidebarTab: 'zones',
  showSensors: true,
  showAvatars: true,
  showDiagnosticsModal: false,

  // Stream controls
  wallOpacity: 0.4,
  fpsLimit: 30,
  floorFilter: 'all',
  zoneSelectMode: true,

  // ── WebSocket & Rendering Decoupler ─────────────────────
  _ws: null,
  _reconnectTimer: null,
  _rafId: null,
  _latestRawData: null,
  _lastRenderTime: 0,

  _startRenderLoop: () => {
    const loop = (now) => {
      const state = get();
      const minInterval = 1000 / state.fpsLimit;
      if (now - state._lastRenderTime >= minInterval) {
        const raw = state._latestRawData;
        if (raw) {
          set({
            persons: raw.persons !== undefined ? raw.persons : state.persons,
            zones: raw.zones !== undefined ? raw.zones : state.zones,
            diagnostics: raw.diagnostics !== undefined ? raw.diagnostics : state.diagnostics,
            _latestRawData: null,
            _lastRenderTime: now,
          });
        }
      }
      set({ _rafId: requestAnimationFrame(loop) });
    };

    if (get()._rafId) cancelAnimationFrame(get()._rafId);
    set({ _rafId: requestAnimationFrame(loop) });
  },

  _restartRenderLoop: () => {
    if (get()._rafId) cancelAnimationFrame(get()._rafId);
    get()._startRenderLoop();
  },

  connectToBackend: () => {
    const state = get();
    if (state._ws) return; // Already connected

    state._startRenderLoop();

    console.log('[ws] Connecting to', WS_URL);
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[ws] Connected');
      set({ connected: true, _ws: ws });
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const state = get();
        const nextState = {};

        if (data.type === 'realtime_update') {
          nextState._latestRawData = {
            persons: data.persons,
            zones: data.zones,
            diagnostics: data.diagnostics,
          };
          set(nextState);
        } else {
          // old format fallback
          const currentRaw = state._latestRawData || {
            persons: state.persons,
            zones: state.zones,
            diagnostics: state.diagnostics,
          };
          if (data.type === 'rigvision:persons') currentRaw.persons = data.payload;
          if (data.type === 'rigvision:zones') currentRaw.zones = data.payload;
          if (data.type === 'rigvision:diagnostics') currentRaw.diagnostics = data.payload;
          
          nextState._latestRawData = currentRaw;
          set(nextState);
        }
      } catch (err) {
        console.error('[ws] Parse error:', err);
      }
    };

    ws.onclose = () => {
      console.log('[ws] Disconnected. Reconnecting in 2s...');
      set({ connected: false, _ws: null });
      if (get()._rafId) cancelAnimationFrame(get()._rafId);

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
    if (state._rafId) {
      cancelAnimationFrame(state._rafId);
    }
    if (state._ws) {
      state._ws.close();
    }
    set({ connected: false, _ws: null, _reconnectTimer: null, _rafId: null });
  },

  // ── UI Actions ─────────────────────────────────────────
  setWallOpacity: (val) => set({ wallOpacity: val }),
  setFpsLimit: (val) => {
    set({ fpsLimit: val });
    get()._restartRenderLoop();
  },
  setFloorFilter: (val) => set({ floorFilter: val }),
  setZoneSelectMode: (val) => set({ zoneSelectMode: val }),
  
  clearTrackingCache: async () => {
    try {
      const res = await fetch(`${API_BASE}/control/clear_cache`, { method: 'POST' });
      if (res.ok) {
        console.log('Tracking cache cleared successfully');
      } else {
        console.error('Failed to clear tracking cache');
      }
    } catch (err) {
      console.error('Error clearing tracking cache:', err);
    }
  },

  selectPerson: (id) => set({ selectedPerson: id, selectedZone: null }),
  selectZone: (id) => set({ selectedZone: id, selectedPerson: null }),
  clearSelection: () => set({ selectedPerson: null, selectedZone: null }),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  toggleSensors: () => set((state) => ({ showSensors: !state.showSensors })),
  toggleAvatars: () => set((state) => ({ showAvatars: !state.showAvatars })),
  setShowDiagnosticsModal: (val) => set({ showDiagnosticsModal: val }),
}))