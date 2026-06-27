import React, { useState } from 'react';
import { Html } from '@react-three/drei';

const SENSOR_COLORS = {
  temperature: '#ff6600',
  vibration: '#00ccff',
  gas_h2s: '#ffcc00',
  noise: '#cc33ff',
  pressure: '#00ff66',
  default: '#ffffff'
};

export default function SensorIndicator({ sensor }) {
  const [hovered, setHovered] = useState(false);
  const color = SENSOR_COLORS[sensor.type] || SENSOR_COLORS.default;

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

      {/* Outer Glow Ring */}
      <mesh>
        <sphereGeometry args={[0.1, 16, 16]} />
        <meshBasicMaterial color={color} transparent opacity={hovered ? 0.4 : 0.15} depthWrite={false} />
      </mesh>

      {hovered && (
        <Html position={[0, 0.2, 0]} center distanceFactor={6} zIndexRange={[100, 0]}>
          <div style={{
            background: 'rgba(20, 20, 30, 0.85)',
            border: `1px solid ${color}`,
            borderRadius: '4px',
            padding: '4px 8px',
            color: '#fff',
            fontSize: '11px',
            fontFamily: 'Inter, sans-serif',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            boxShadow: `0 0 10px ${color}40`
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
