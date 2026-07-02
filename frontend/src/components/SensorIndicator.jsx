import React, { useState } from 'react';
import { Html } from '@react-three/drei';
import { useRigStore } from '../stores/useRigStore.js';

// Muted, distinguishable sensor-type tints (within the refined slate palette).
const SENSOR_COLORS = {
  temperature: '#d98a4e',
  vibration: '#5b8def',
  gas_h2s: '#c9b84e',
  noise: '#9b8fc4',
  pressure: '#46b17f',
  default: '#8b93a3'
};

export default function SensorIndicator({ sensor }) {
  const [hovered, setHovered] = useState(false);
  const color = SENSOR_COLORS[sensor.type] || SENSOR_COLORS.default;
  const showDiagnosticsModal = useRigStore(s => s.showDiagnosticsModal);

  return (
    <group position={sensor.position}>
      {/* Glowing Node */}
      <mesh 
        onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
        onPointerOut={(e) => { e.stopPropagation(); setHovered(false); }}
      >
        <sphereGeometry args={[hovered ? 0.08 : 0.05, 16, 16]} />
        <meshBasicMaterial color={color} />
      </mesh>

      {/* Soft halo (subtle, no neon bloom) */}
      <mesh>
        <sphereGeometry args={[0.1, 16, 16]} />
        <meshBasicMaterial color={color} transparent opacity={hovered ? 0.25 : 0.1} depthWrite={false} />
      </mesh>

      {hovered && !showDiagnosticsModal && (
        <Html position={[0, 0.2, 0]} center distanceFactor={6} zIndexRange={[100, 0]}>
          <div style={{
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderLeft: `2px solid ${color}`,
            borderRadius: '4px',
            padding: '4px 8px',
            color: 'var(--text-primary)',
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            boxShadow: '0 2px 8px rgba(0,0,0,0.5)'
          }}>
            <strong style={{ color }}>{sensor.type.toUpperCase()}</strong>
            <br />
            {sensor.id}
          </div>
        </Html>
      )}
    </group>
  );
}
