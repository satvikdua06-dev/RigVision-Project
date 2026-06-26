/**
 * RigVision-3D — Person Avatar
 * 
 * Renders a capsule-shaped person in 3D space with:
 * - Smooth 60fps interpolation (lerp) despite 10Hz data
 * - Color-coded PPE status (green=safe, red=violation)
 * - Hard hat geometry if wearing one
 * - Floating ID label
 * - Ground shadow disc
 */

import React, { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';

const LERP_FACTOR = 0.12;

export default function PersonAvatar({ person }) {
  const groupRef = useRef();
  const glowRef = useRef();
  const currentPos = useRef(new THREE.Vector3(person.x, person.y + 0.9, person.z));

  // Target position from latest data (person.y is foot position, +0.9 for body center)
  const targetPos = useMemo(
    () => new THREE.Vector3(person.x, person.y + 0.9, person.z),
    [person.x, person.y, person.z]
  );

  // PPE status determines body color
  const hasAllPPE = person.ppe?.hardhat && person.ppe?.vest;
  const bodyColor = hasAllPPE ? '#22cc66' : '#ee4455';
  const headColor = '#ffcc88';

  // Smooth interpolation + glow pulse every frame
  useFrame((state) => {
    if (groupRef.current) {
      currentPos.current.lerp(targetPos, LERP_FACTOR);
      groupRef.current.position.copy(currentPos.current);
    }
    // Pulse the glow indicator for PPE violations
    if (glowRef.current && !hasAllPPE) {
      const t = state.clock.elapsedTime;
      glowRef.current.material.opacity = 0.5 + 0.4 * Math.sin(t * 4);
    }
  });

  return (
    <group ref={groupRef} position={[person.x, person.y + 0.9, person.z]} renderOrder={10}>
      {/* Ground shadow disc */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.85, 0]}>
        <circleGeometry args={[0.25, 16]} />
        <meshBasicMaterial
          color={hasAllPPE ? '#22cc66' : '#ee4455'}
          transparent
          opacity={0.15}
          depthWrite={false}
        />
      </mesh>

      {/* Body — capsule shape */}
      <mesh castShadow>
        <capsuleGeometry args={[0.18, 0.5, 8, 16]} />
        <meshStandardMaterial
          color={bodyColor}
          roughness={0.4}
          metalness={0.2}
          emissive={hasAllPPE ? '#114422' : '#441111'}
          emissiveIntensity={0.4}
        />
      </mesh>

      {/* Head — sphere */}
      <mesh position={[0, 0.52, 0]} castShadow>
        <sphereGeometry args={[0.14, 16, 16]} />
        <meshStandardMaterial color={headColor} roughness={0.5} />
      </mesh>

      {/* Hard hat — flattened cylinder (only if wearing one) */}
      {person.ppe?.hardhat && (
        <mesh position={[0, 0.68, 0]}>
          <cylinderGeometry args={[0.18, 0.2, 0.08, 16]} />
          <meshStandardMaterial
            color="#ffdd00"
            roughness={0.3}
            metalness={0.4}
            emissive="#665500"
            emissiveIntensity={0.3}
          />
        </mesh>
      )}

      {/* PPE violation indicator — pulsing red ring above head */}
      {!hasAllPPE && (
        <mesh ref={glowRef} position={[0, 0.9, 0]}>
          <torusGeometry args={[0.12, 0.03, 8, 16]} />
          <meshBasicMaterial
            color="#ff2244"
            transparent
            opacity={0.8}
          />
        </mesh>
      )}

      {/* Floating ID label */}
      <Html
        position={[0, 1.1, 0]}
        center
        distanceFactor={10}
        style={{ pointerEvents: 'none' }}
      >
        <div style={{
          background: hasAllPPE
            ? 'rgba(0, 180, 80, 0.9)'
            : 'rgba(220, 40, 60, 0.9)',
          color: '#fff',
          fontSize: '10px',
          fontWeight: 700,
          fontFamily: 'Inter, sans-serif',
          padding: '2px 8px',
          borderRadius: '10px',
          whiteSpace: 'nowrap',
          letterSpacing: '0.03em',
          boxShadow: hasAllPPE
            ? '0 0 6px rgba(0,180,80,0.5)'
            : '0 0 6px rgba(220,40,60,0.5)',
        }}>
          #{person.id}
        </div>
      </Html>
    </group>
  );
}
