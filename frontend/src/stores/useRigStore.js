import { create } from 'zustand'
import { authHeaders } from '../utils/api.js'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname;
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = import.meta.env.VITE_WS_URL || `${wsProtocol}//${host}:8000/ws/realtime`;
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`;

let globalRafId = null;

export const useRigStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────
  persons: [],
  // Two stacked zones: Room A (ground floor) and Room B (first floor). No corridor.
  zones: {
    zone_a: { status: 'normal', temperature: 25, vibration: 0, noise: 40, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() },
    zone_b: { status: 'normal', temperature: 26, vibration: 0, noise: 45, gas_h2s: 0, pressure: 1, person_count: 0, ppe_violations: [], updated_at: Date.now() }
  },
  diagnostics: [],
  // Live per-event diagnosis progress { event_id: { stage, zone_id, subgraph, chunks, report, ... } }
  diagProgress: {},
  // PPE detection demo (cv/ppe_demo.py → rigvision:ppe:latest). Per-item status:
  // detected | missing | no_person | unknown. `proof` is set on a "missing" commit.
  ppe: { person_present: false },
  connected: false,
  // Selection & UI State
  selectedPerson: null,
  selectedZone: null,
  sidebarTab: 'zones',
  showSensors: true,
  showAvatars: true,
  showDiagnosticsModal: false,
  hasReceivedData: false,
  preexistingSignatures: [],
  isNotificationsInitialized: false,

  // Stream controls
  wallOpacity: 0.4,
  fpsLimit: 30,
  floorFilter: 'all',
  zoneSelectMode: true,

  // ── WebSocket & Rendering Decoupler ─────────────────────
  _ws: null,
  _reconnectTimer: null,
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
            diagProgress: raw.diagProgress !== undefined ? raw.diagProgress : state.diagProgress,
            ppe: raw.ppe !== undefined ? raw.ppe : state.ppe,
            hasReceivedData: true,
            _latestRawData: null,
            _lastRenderTime: now,
          });
        }
      }
      globalRafId = requestAnimationFrame(loop);
    };

    if (globalRafId) cancelAnimationFrame(globalRafId);
    globalRafId = requestAnimationFrame(loop);
  },

  _restartRenderLoop: () => {
    if (globalRafId) cancelAnimationFrame(globalRafId);
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
          const nextRaw = {
            persons: data.persons,
          };

          // Stabilize zones (prevent unnecessary rerenders if data is equivalent)
          if (JSON.stringify(state.zones) !== JSON.stringify(data.zones)) {
            nextRaw.zones = data.zones;
          } else {
            nextRaw.zones = state.zones;
          }

          // Stabilize diagnostics
          if (JSON.stringify(state.diagnostics) !== JSON.stringify(data.diagnostics)) {
            nextRaw.diagnostics = data.diagnostics;
          } else {
            nextRaw.diagnostics = state.diagnostics;
          }

          // Stabilize diagProgress
          if (JSON.stringify(state.diagProgress) !== JSON.stringify(data.diag_progress)) {
            nextRaw.diagProgress = data.diag_progress;
          } else {
            nextRaw.diagProgress = state.diagProgress;
          }

          // Stabilize ppe
          if (JSON.stringify(state.ppe) !== JSON.stringify(data.ppe)) {
            nextRaw.ppe = data.ppe;
          } else {
            nextRaw.ppe = state.ppe;
          }

          nextState._latestRawData = nextRaw;
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
      set({ connected: false, _ws: null, hasReceivedData: false, preexistingSignatures: [], isNotificationsInitialized: false });
      if (globalRafId) cancelAnimationFrame(globalRafId);

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
    if (globalRafId) {
      cancelAnimationFrame(globalRafId);
    }
    if (state._ws) {
      state._ws.close();
    }
    set({ connected: false, _ws: null, _reconnectTimer: null, hasReceivedData: false, preexistingSignatures: [], isNotificationsInitialized: false });
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
      const res = await fetch(`${API_BASE}/control/clear_cache`, { method: 'POST', headers: authHeaders() });
      if (res.ok) {
        console.log('Tracking cache cleared successfully');
      } else {
        console.error('Failed to clear tracking cache');
      }
    } catch (err) {
      console.error('Error clearing tracking cache:', err);
    }
  },

  clearDiagnostics: async () => {
    try {
      const res = await fetch(`${API_BASE}/diagnostics/clear`, { method: 'POST', headers: authHeaders() });
      if (res.ok) {
        console.log('Diagnostics cleared successfully');
        set({ diagnostics: [] });
      } else {
        console.error('Failed to clear diagnostics');
      }
    } catch (err) {
      console.error('Error clearing diagnostics:', err);
    }
  },

  selectPerson: (id) => set({ selectedPerson: id, selectedZone: null }),
  selectZone: (id) => set({ selectedZone: id, selectedPerson: null }),
  clearSelection: () => set({ selectedPerson: null, selectedZone: null }),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  toggleSensors: () => set((state) => ({ showSensors: !state.showSensors })),
  toggleAvatars: () => set((state) => ({ showAvatars: !state.showAvatars })),
  setShowDiagnosticsModal: (val) => set({ showDiagnosticsModal: val }),

  setPreexistingSignatures: (sigs) => set({ preexistingSignatures: sigs }),
  addPreexistingSignature: (sig) => set((state) => ({
    preexistingSignatures: state.preexistingSignatures.includes(sig)
      ? state.preexistingSignatures
      : [...state.preexistingSignatures, sig]
  })),
  removePreexistingSignature: (sig) => set((state) => ({
    preexistingSignatures: state.preexistingSignatures.filter((x) => x !== sig)
  })),
  setNotificationsInitialized: (val) => set({ isNotificationsInitialized: val }),
}))