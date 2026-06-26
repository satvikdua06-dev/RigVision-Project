/**
 * RigVision-3D — Sensor Overlay
 * 
 * Floating sensor data cards positioned above each zone in 3D space.
 * Uses drei's <Html> component to render DOM elements in 3D.
 * 
 * Visible when a zone is hovered or selected.
 * Color-coded values based on warning/critical thresholds.
 */

import React from 'react';
import { Html } from '@react-three/drei';
import { ZONES } from '../utils/zonePositions';
import useRealtimeStore from '../stores/realtimeStore';

function getValueClass(value, warning, critical) {
  if (value >= critical) return 'critical';
  if (value >= warning) return 'warning';
  return 'normal';
}

function ZoneSensorCard({ zoneId, zone }) {
  const zones = useRealtimeStore((s) => s.zones);
  const hoveredZone = useRealtimeStore((s) => s.hoveredZone);
  const selectedZone = useRealtimeStore((s) => s.selectedZone);

  const zoneData = zones[zoneId];
  const isVisible = hoveredZone === zoneId || selectedZone === zoneId;

  if (!isVisible || !zoneData) return null;

  const sensors = [
    { label: 'Temp', value: zoneData.temperature, unit: '°C', warning: 50, critical: 65 },
    { label: 'Vibration', value: zoneData.vibration, unit: 'g', warning: 4, critical: 7 },
    { label: 'Noise', value: zoneData.noise, unit: 'dB', warning: 90, critical: 100 },
    { label: 'H₂S', value: zoneData.gas_h2s, unit: 'ppm', warning: 10, critical: 15 },
    { label: 'Pressure', value: zoneData.pressure, unit: 'bar', warning: 20, critical: 25 },
    { label: 'Persons', value: zoneData.person_count, unit: '', warning: 99, critical: 99 },
  ];

  return (
    <Html
      position={[zone.center[0], zone.center[1] + 1.8, zone.center[2]]}
      center
      distanceFactor={8}
      style={{ pointerEvents: 'none' }}
    >
      <div className="sensor-overlay">
        <div className="sensor-overlay-title">{zone.name}</div>
        {sensors.map((s) => (
          <div className="sensor-row" key={s.label}>
            <span className="sensor-label">{s.label}</span>
            <span
              className="sensor-value"
              style={{
                color: getValueClass(s.value, s.warning, s.critical) === 'critical'
                  ? '#ff4455'
                  : getValueClass(s.value, s.warning, s.critical) === 'warning'
                    ? '#ffaa00'
                    : '#e8e8f0',
              }}
            >
              {typeof s.value === 'number' ? s.value.toFixed(1) : s.value}{s.unit}
            </span>
          </div>
        ))}
      </div>
    </Html>
  );
}

export default function SensorOverlay() {
  return (
    <group>
      {Object.entries(ZONES).map(([zoneId, zone]) => (
        <ZoneSensorCard key={zoneId} zoneId={zoneId} zone={zone} />
      ))}
    </group>
  );
}
