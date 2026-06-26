/**
 * RigVision-3D — Main Application
 * 
 * Layout: 3D Canvas (left, flex:1) + Sidebar (right, 340px)
 * 
 * The sidebar shows:
 * - Connection status indicator
 * - Toggle buttons for sensors/avatars
 * - Zone cards with status, person count, sensor summary, violations
 */

import React, { useEffect } from 'react';
import RigScene from './three/RigScene';
import useRealtimeStore from './stores/realtimeStore';
import { ZONES } from './utils/zonePositions';

/* ── Zone Card Component ─────────────────────────────────── */
function ZoneCard({ zoneId, zone }) {
  const zones = useRealtimeStore((s) => s.zones);
  const selectedZone = useRealtimeStore((s) => s.selectedZone);
  const setSelectedZone = useRealtimeStore((s) => s.setSelectedZone);
  const setHoveredZone = useRealtimeStore((s) => s.setHoveredZone);

  const zoneData = zones[zoneId];
  const status = zoneData?.status || 'normal';
  const isSelected = selectedZone === zoneId;

  return (
    <div
      className={`zone-card ${isSelected ? 'selected' : ''}`}
      data-status={status}
      onClick={() => setSelectedZone(zoneId)}
      onMouseEnter={() => setHoveredZone(zoneId)}
      onMouseLeave={() => setHoveredZone(null)}
    >
      <div className="zone-card-header">
        <span className="zone-name">{zone.name}</span>
        <span className={`zone-status-badge ${status}`}>{status}</span>
      </div>

      <div className="person-count">
        👤 <span className="count">{zoneData?.person_count ?? 0}</span> persons
      </div>

      {zoneData && (
        <div className="zone-stats">
          <Stat label="Temp" value={zoneData.temperature} unit="°C" warn={50} crit={65} />
          <Stat label="Vibr" value={zoneData.vibration} unit="g" warn={4} crit={7} />
          <Stat label="Noise" value={zoneData.noise} unit="dB" warn={90} crit={100} />
          <Stat label="H₂S" value={zoneData.gas_h2s} unit="ppm" warn={10} crit={15} />
          <Stat label="Press" value={zoneData.pressure} unit="bar" warn={20} crit={25} />
        </div>
      )}

      {zoneData?.warning_reason && (
        <div className="zone-warning-reason">
          ⚠ {zoneData.warning_reason}
        </div>
      )}

      {zoneData?.ppe_violations?.length > 0 && (
        <div className="ppe-violations">
          {zoneData.ppe_violations.map((v, i) => (
            <div key={i} className="ppe-violation">🚫 {v}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Stat Component (single sensor value) ────────────────── */
function Stat({ label, value, unit, warn, crit }) {
  let cls = 'normal';
  if (value >= crit) cls = 'critical';
  else if (value >= warn) cls = 'warning';

  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value ${cls}`}>
        {typeof value === 'number' ? value.toFixed(1) : value}{unit}
      </span>
    </div>
  );
}

/* ── Main App ────────────────────────────────────────────── */
export default function App() {
  const connected = useRealtimeStore((s) => s.connected);
  const showSensors = useRealtimeStore((s) => s.showSensors);
  const showAvatars = useRealtimeStore((s) => s.showAvatars);
  const toggleSensors = useRealtimeStore((s) => s.toggleSensors);
  const toggleAvatars = useRealtimeStore((s) => s.toggleAvatars);
  const connect = useRealtimeStore((s) => s.connect);

  // Connect WebSocket on mount
  useEffect(() => {
    connect();
    return () => useRealtimeStore.getState().disconnect();
  }, [connect]);

  return (
    <div className="app-layout">
      {/* 3D Canvas */}
      <div className="canvas-container">
        <RigScene />

        {/* HUD Overlay */}
        <div className="hud-overlay">
          <div className="hud-title">RigVision-3D</div>
          <div className="hud-subtitle">Digital Twin Dashboard</div>
        </div>
      </div>

      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-title">
            <span className="logo-icon">🛢️</span>
            <h1>RigVision-3D</h1>
          </div>
          <div className="connection-status">
            <div className={`status-dot ${connected ? 'connected' : ''}`} />
            {connected ? 'Live Connection' : 'Disconnected'}
          </div>
        </div>

        {/* Toggle Controls */}
        <div className="controls">
          <button
            className={`toggle-btn ${showAvatars ? 'active' : ''}`}
            onClick={toggleAvatars}
          >
            👤 Avatars
          </button>
          <button
            className={`toggle-btn ${showSensors ? 'active' : ''}`}
            onClick={toggleSensors}
          >
            📊 Sensors
          </button>
        </div>

        {/* Zone Cards */}
        <div className="zone-list">
          {Object.entries(ZONES).map(([zoneId, zone]) => (
            <ZoneCard key={zoneId} zoneId={zoneId} zone={zone} />
          ))}
        </div>
      </aside>
    </div>
  );
}
