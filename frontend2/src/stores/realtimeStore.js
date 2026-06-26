/**
 * RigVision-3D — Zustand Real-time Store
 * 
 * Central state management with WebSocket connection.
 * 
 * WHAT IS ZUSTAND?
 * ────────────────
 * Zustand is a tiny state management library for React.
 * Unlike Redux (boilerplate-heavy), Zustand uses a simple hook:
 * 
 *   const persons = useRealtimeStore(state => state.persons);
 * 
 * When 'persons' changes, only components reading it re-render.
 * This is critical for 60fps 3D rendering — we can't re-render
 * the entire app 10 times per second.
 * 
 * WEBSOCKET LIFECYCLE:
 *   1. Store creates WebSocket to ws://localhost:8000/ws/realtime
 *   2. Server pushes {persons, zones, violations} at ~10Hz
 *   3. Store updates state → React re-renders affected components
 *   4. If connection drops, auto-reconnect after 2 seconds
 */

import { create } from 'zustand';

const WS_URL = `ws://${window.location.hostname}:8000/ws/realtime`;

const useRealtimeStore = create((set, get) => ({
  // ── State ──────────────────────────────────────────────
  persons: [],
  zones: {},
  violations: [],
  connected: false,
  hoveredZone: null,
  selectedZone: null,
  showSensors: true,
  showAvatars: true,

  // ── WebSocket ──────────────────────────────────────────
  _ws: null,
  _reconnectTimer: null,

  connect: () => {
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
          set({
            persons: data.persons || [],
            zones: data.zones || {},
            violations: data.violations || [],
          });
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
        get().connect();
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
  setHoveredZone: (zoneId) => set({ hoveredZone: zoneId }),
  setSelectedZone: (zoneId) => set((state) => ({
    selectedZone: state.selectedZone === zoneId ? null : zoneId,
  })),
  toggleSensors: () => set((state) => ({ showSensors: !state.showSensors })),
  toggleAvatars: () => set((state) => ({ showAvatars: !state.showAvatars })),
}));

export default useRealtimeStore;
