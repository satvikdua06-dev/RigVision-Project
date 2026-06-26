/**
 * RigVision-3D — 3D Room Model
 * 
 * Renders the procedural 3D model:
 * - 2 rooms (Room A, Room B) connected by a corridor
 * - Floor planes with concrete material
 * - Walls with door openings
 * - Zone bounding volumes (subtle tint + wireframe edges, color by status)
 * - Equipment boxes with labels
 * - Hover/click interaction for zones
 */

import React, { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html, Edges, Line } from '@react-three/drei';
import * as THREE from 'three';
import { ZONES, getZoneColor, getZoneOpacity } from '../utils/zonePositions';
import useRealtimeStore from '../stores/realtimeStore';
import CameraIndicator from './CameraIndicator';
import SensorIndicator from './SensorIndicator';

/* ── Floor Component ─────────────────────────────────────── */
function Floor() {
  return (
    <group>
      {/* Main floor — dark concrete */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[5, 0, 2.5]} receiveShadow>
        <planeGeometry args={[10, 5]} />
        <meshStandardMaterial color="#1a1a24" roughness={0.9} metalness={0.1} />
      </mesh>
      {/* Floor accent lines for rooms */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[2, 0.002, 2.5]} receiveShadow>
        <planeGeometry args={[3.8, 4.8]} />
        <meshStandardMaterial color="#1c1c28" roughness={0.95} metalness={0} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[8, 0.002, 2.5]} receiveShadow>
        <planeGeometry args={[3.8, 4.8]} />
        <meshStandardMaterial color="#1c1c28" roughness={0.95} metalness={0} />
      </mesh>
    </group>
  );
}

/* ── Wall Component ──────────────────────────────────────── */
function Wall({ position, size }) {
  return (
    <mesh position={position} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color="#22223a" roughness={0.75} metalness={0.05} />
      <Edges color="#333355" />
    </mesh>
  );
}

/* ── Walls Layout ────────────────────────────────────────── */
function Walls() {
  const wallThickness = 0.1;
  const wallHeight = 3;
  
  return (
    <group>
      {/* Room A walls */}
      <Wall position={[2, wallHeight/2, -wallThickness/2]} size={[4, wallHeight, wallThickness]} />
      <Wall position={[2, wallHeight/2, 5 + wallThickness/2]} size={[4, wallHeight, wallThickness]} />
      <Wall position={[-wallThickness/2, wallHeight/2, 2.5]} size={[wallThickness, wallHeight, 5]} />
      {/* Right wall of Room A - with corridor opening */}
      <Wall position={[4 + wallThickness/2, wallHeight/2, 0.75]} size={[wallThickness, wallHeight, 1.5]} />
      <Wall position={[4 + wallThickness/2, wallHeight/2, 4.25]} size={[wallThickness, wallHeight, 1.5]} />

      {/* Room B walls */}
      <Wall position={[8, wallHeight/2, -wallThickness/2]} size={[4, wallHeight, wallThickness]} />
      <Wall position={[8, wallHeight/2, 5 + wallThickness/2]} size={[4, wallHeight, wallThickness]} />
      <Wall position={[10 + wallThickness/2, wallHeight/2, 2.5]} size={[wallThickness, wallHeight, 5]} />
      <Wall position={[6 - wallThickness/2, wallHeight/2, 0.75]} size={[wallThickness, wallHeight, 1.5]} />
      <Wall position={[6 - wallThickness/2, wallHeight/2, 4.25]} size={[wallThickness, wallHeight, 1.5]} />

      {/* Corridor walls */}
      <Wall position={[5, wallHeight/2, 1.5 - wallThickness/2]} size={[2, wallHeight, wallThickness]} />
      <Wall position={[5, wallHeight/2, 3.5 + wallThickness/2]} size={[2, wallHeight, wallThickness]} />
    </group>
  );
}

/* ── Zone Volume ─────────────────────────────────────────── */
function ZoneVolume({ zoneId, zone }) {
  const meshRef = useRef();
  const edgesRef = useRef();
  const zones = useRealtimeStore((s) => s.zones);
  const hoveredZone = useRealtimeStore((s) => s.hoveredZone);
  const selectedZone = useRealtimeStore((s) => s.selectedZone);
  const setHoveredZone = useRealtimeStore((s) => s.setHoveredZone);
  const setSelectedZone = useRealtimeStore((s) => s.setSelectedZone);

  const zoneData = zones[zoneId];
  const status = zoneData?.status || 'normal';
  const isHovered = hoveredZone === zoneId;
  const isSelected = selectedZone === zoneId;

  const color = getZoneColor(status);
  const baseOpacity = getZoneOpacity(status);

  // Animate opacity on hover/select
  useFrame(() => {
    if (meshRef.current) {
      const targetOpacity = isHovered || isSelected ? baseOpacity * 3 : baseOpacity;
      meshRef.current.material.opacity +=
        (targetOpacity - meshRef.current.material.opacity) * 0.12;
    }
  });

  return (
    <group>
      {/* Transparent fill — very subtle tint, renders behind everything */}
      <mesh
        ref={meshRef}
        position={zone.center}
        renderOrder={-1}
        onPointerOver={(e) => { e.stopPropagation(); setHoveredZone(zoneId); }}
        onPointerOut={() => setHoveredZone(null)}
        onClick={(e) => { e.stopPropagation(); setSelectedZone(zoneId); }}
      >
        <boxGeometry args={zone.size} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={baseOpacity}
          depthWrite={false}
          side={THREE.BackSide}
        />
      </mesh>
      {/* Wireframe edges — always visible */}
      <mesh position={zone.center}>
        <boxGeometry args={zone.size} />
        <meshBasicMaterial visible={false} />
        <Edges
          color={color}
          linewidth={isHovered || isSelected ? 2 : 1}
          threshold={15}
        />
      </mesh>
      {/* Zone label on the floor */}
      <Html
        position={[zone.center[0], 0.05, zone.center[2] - zone.size[2] / 2 + 0.4]}
        center
        distanceFactor={12}
        style={{ pointerEvents: 'none' }}
      >
        <div style={{
          color: color,
          fontSize: '11px',
          fontWeight: 600,
          fontFamily: 'Inter, sans-serif',
          opacity: 0.6,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          textShadow: `0 0 8px ${color}40`,
        }}>
          {zone.name}
        </div>
      </Html>
    </group>
  );
}

/* ── Equipment Box ──────────────────────────────────────── */
function EquipmentBox({ equipment }) {
  const [hovered, setHovered] = React.useState(false);

  return (
    <group>
      <mesh
        position={equipment.position}
        castShadow
        onPointerOver={() => setHovered(true)}
        onPointerOut={() => setHovered(false)}
      >
        <boxGeometry args={equipment.size} />
        <meshStandardMaterial
          color={hovered ? '#8899aa' : equipment.color}
          roughness={0.6}
          metalness={0.3}
        />
        <Edges color="#334455" />
      </mesh>
      {hovered && (
        <Html
          position={[
            equipment.position[0],
            equipment.position[1] + equipment.size[1] / 2 + 0.3,
            equipment.position[2],
          ]}
          center
          distanceFactor={8}
          style={{ pointerEvents: 'none' }}
        >
          <div style={{
            background: 'rgba(12, 12, 20, 0.92)',
            backdropFilter: 'blur(8px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: '8px',
            padding: '6px 12px',
            fontSize: '12px',
            fontFamily: 'Inter, sans-serif',
            color: '#e8e8f0',
            whiteSpace: 'nowrap',
          }}>
            {equipment.name}
          </div>
        </Html>
      )}
    </group>
  );
}

/* ── Main Room Model ────────────────────────────────────── */
export default function RigModel() {
  return (
    <group>
      <Floor />
      <Walls />

      {/* Zone volumes */}
      {Object.entries(ZONES).map(([zoneId, zone]) => (
        <ZoneVolume key={zoneId} zoneId={zoneId} zone={zone} />
      ))}

      {/* Equipment */}
      {Object.values(ZONES).flatMap((zone) =>
        zone.equipment.map((eq) => (
          <EquipmentBox key={eq.id} equipment={eq} />
        ))
      )}

      {/* Cameras */}
      {Object.values(ZONES).map((zone) => 
        zone.camera && <CameraIndicator key={zone.camera.id} camera={zone.camera} />
      )}

      {/* Sensors */}
      {Object.values(ZONES).flatMap((zone) =>
        (zone.sensors || []).map((sensor) => (
          <SensorIndicator key={sensor.id} sensor={sensor} />
        ))
      )}
    </group>
  );
}
