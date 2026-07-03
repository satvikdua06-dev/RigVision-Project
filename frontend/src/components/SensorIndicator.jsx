import React, { useState } from 'react';
import { Html, Billboard } from '@react-three/drei';
import { useRigStore } from '../stores/useRigStore.js';

// Muted, distinguishable sensor-type tints (within the refined slate palette).
const SENSOR_COLORS = {
  temperature: '#d98a4e',
  vibration:   '#5b8def',
  gas_h2s:     '#c9b84e',
  noise:       '#9b8fc4',
  pressure:    '#46b17f',
  default:     '#8b93a3',
};

const SENSOR_GLYPH = {
  temperature: 'T',
  vibration:   '~',
  gas_h2s:     'G',
  noise:       'dB',
  pressure:    'P',
};

// Render a sensor as a small floor disc, a thin stem rising to ~human eye level
// above any equipment, and an always-visible color pin with a glyph. The previous
// design (5 cm sphere at the sensor's metric Y) put several sensors *inside* the
// equipment they monitor — making them invisible. This stem version guarantees
// every sensor reads cleanly from any orbit angle.
export default function SensorIndicator({ sensor }) {
  const [hovered, setHovered] = useState(false);
  const color = SENSOR_COLORS[sensor.type] || SENSOR_COLORS.default;
  const glyph = SENSOR_GLYPH[sensor.type] || '•';
  const showDiagnosticsModal = useRigStore(s => s.showDiagnosticsModal);

  const [x, y, z] = sensor.position;
  // The pin sits at a fixed height above the sensor's actual location so it always
  // clears the equipment props (max prop height in the bay is ~2.6m relative to
  // the floor). The stem visually connects pin → real metric position.
  const PIN_HEIGHT = 0.9;
  const pinY = y + PIN_HEIGHT;

  return (
    <group>
      {/* Floor disc + thin stem rising to the pin (raycast disabled so they don't
          eat clicks meant for the deck or equipment behind them). */}
      <mesh position={[x, y + 0.005, z]} rotation={[-Math.PI / 2, 0, 0]} raycast={null}>
        <circleGeometry args={[0.12, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.55} depthWrite={false} />
      </mesh>
      <mesh position={[x, y + PIN_HEIGHT / 2, z]} raycast={null}>
        <cylinderGeometry args={[0.012, 0.012, PIN_HEIGHT, 8]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} depthWrite={false} />
      </mesh>

      {/* Always-visible billboarded pin — the click/hover target. */}
      <Billboard position={[x, pinY, z]} follow>
        <mesh
          onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
          onPointerOut={(e) => { e.stopPropagation(); setHovered(false); }}
        >
          <circleGeometry args={[hovered ? 0.16 : 0.13, 32]} />
          <meshBasicMaterial color={color} />
        </mesh>
        {/* outline ring */}
        <mesh position={[0, 0, -0.001]}>
          <ringGeometry args={[hovered ? 0.16 : 0.13, hovered ? 0.18 : 0.15, 32]} />
          <meshBasicMaterial color="#0e1116" />
        </mesh>
        {/* glyph */}
        <Html center transform distanceFactor={1.6} style={{ pointerEvents: 'none' }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 7, fontWeight: 700,
            color: '#0e1116', letterSpacing: 0, lineHeight: 1, userSelect: 'none',
          }}>
            {glyph}
          </div>
        </Html>
      </Billboard>

      {/* Hover detail card. distanceFactor raised so it's readable at orbit distance. */}
      {hovered && !showDiagnosticsModal && (
        <Html position={[x, pinY + 0.35, z]} center distanceFactor={14} zIndexRange={[100, 0]}>
          <div style={{
            background: 'var(--glass-panel)',
            backdropFilter: 'blur(10px) saturate(120%)',
            WebkitBackdropFilter: 'blur(10px) saturate(120%)',
            border: '1px solid var(--border)',
            borderLeft: `2px solid ${color}`,
            borderRadius: 8,
            padding: '8px 12px',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
            boxShadow: 'var(--shadow-panel), var(--inner-hi)',
            lineHeight: 1.35,
          }}>
            <div style={{ color, fontSize: 11, fontWeight: 600, letterSpacing: 1, textTransform: 'uppercase' }}>
              {sensor.type.replace('_', ' ')}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-primary)', marginTop: 2 }}>
              {sensor.id}
            </div>
          </div>
        </Html>
      )}
    </group>
  );
}
