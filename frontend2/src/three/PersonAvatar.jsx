/**
 * RigVision-3D — Person Avatar
 * 
 * Renders a capsule-shaped person in 3D space with:
 * - Smooth 60fps interpolation (lerp) despite 10Hz data
 * - Color-coded PPE status (green=safe, red=violation)
 * - Hard hat geometry if wearing one
 * - Dynamic posture adjustment (standing, sitting, bending, lying) with smooth animations
 * - Floating ID label
 * - Ground shadow disc
 */

import React, { useRef, useMemo, useState, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';

const LERP_FACTOR = 0.12;

export default function PersonAvatar({ person }) {
  const groupRef = useRef();
  const postureGroupRef = useRef();
  const indicatorRef = useRef();
  const labelGroupRef = useRef();
  const shadowRef = useRef();
  const glowRef = useRef();
  
  // Target position from latest data (group stays on the floor)
  const targetPos = useMemo(
    () => new THREE.Vector3(person.x, person.y, person.z),
    [person.x, person.y, person.z]
  );
  
  const currentPos = useRef(new THREE.Vector3(person.x, person.y, person.z));
  const [hovered, setHovered] = useState(false);

  // PPE status determines body color
  const hasAllPPE = person.ppe?.hardhat && person.ppe?.vest;
  const bodyColor = hasAllPPE ? '#22cc66' : '#ee4455';
  const headColor = '#ffcc88';

  const posture = person.posture || 'standing';

  // Calculate target posture offsets and scales
  const targets = useMemo(() => {
    switch (posture) {
      case 'sitting':
        return {
          bodyPos: new THREE.Vector3(0, 0.5, 0.1),
          bodyRot: new THREE.Euler(0.2, 0, 0),
          bodyScale: new THREE.Vector3(1, 0.7, 1),
          indicatorPos: new THREE.Vector3(0, 1.1, 0.2),
          labelPos: new THREE.Vector3(0, 1.3, 0.2),
          shadowScale: 0.8,
        };
      case 'bending':
        return {
          bodyPos: new THREE.Vector3(0, 0.7, 0.35),
          bodyRot: new THREE.Euler(0.7, 0, 0),
          bodyScale: new THREE.Vector3(1, 0.9, 1),
          indicatorPos: new THREE.Vector3(0, 1.1, 0.7),
          labelPos: new THREE.Vector3(0, 1.3, 0.7),
          shadowScale: 1.1,
        };
      case 'lying':
        return {
          bodyPos: new THREE.Vector3(0, 0.18, 0),
          bodyRot: new THREE.Euler(Math.PI / 2, 0, 0),
          bodyScale: new THREE.Vector3(1, 1, 1),
          indicatorPos: new THREE.Vector3(0, 0.45, 0.7),
          labelPos: new THREE.Vector3(0, 0.65, 0.7),
          shadowScale: 1.4,
        };
      case 'standing':
      default:
        return {
          bodyPos: new THREE.Vector3(0, 0.9, 0),
          bodyRot: new THREE.Euler(0, 0, 0),
          bodyScale: new THREE.Vector3(1, 1, 1),
          indicatorPos: new THREE.Vector3(0, 1.8, 0),
          labelPos: new THREE.Vector3(0, 2.0, 0),
          shadowScale: 1.0,
        };
    }
  }, [posture]);

  // Smooth interpolation + glow pulse every frame
  useFrame((state) => {
    if (groupRef.current) {
      currentPos.current.lerp(targetPos, LERP_FACTOR);
      groupRef.current.position.copy(currentPos.current);
    }

    // Lerp posture body parts
    if (postureGroupRef.current) {
      postureGroupRef.current.position.lerp(targets.bodyPos, LERP_FACTOR);
      postureGroupRef.current.scale.lerp(targets.bodyScale, LERP_FACTOR);
      postureGroupRef.current.rotation.x += (targets.bodyRot.x - postureGroupRef.current.rotation.x) * LERP_FACTOR;
    }

    // Lerp indicator
    if (indicatorRef.current) {
      indicatorRef.current.position.lerp(targets.indicatorPos, LERP_FACTOR);
    }

    // Lerp label group
    if (labelGroupRef.current) {
      labelGroupRef.current.position.lerp(targets.labelPos, LERP_FACTOR);
    }

    // Lerp shadow scale
    if (shadowRef.current) {
      const currentScale = shadowRef.current.scale.x;
      const targetScale = targets.shadowScale;
      const nextScale = currentScale + (targetScale - currentScale) * LERP_FACTOR;
      shadowRef.current.scale.set(nextScale, nextScale, 1);
    }

    // Pulse the glow indicator for PPE violations
    if (glowRef.current && !hasAllPPE) {
      const t = state.clock.elapsedTime;
      glowRef.current.material.opacity = 0.5 + 0.4 * Math.sin(t * 4);
    }
  });

  // Cleanup cursor on unmount if hovered
  useEffect(() => {
    return () => {
      if (hovered) {
        document.body.style.cursor = 'default';
      }
    };
  }, [hovered]);

  return (
    <group
      ref={groupRef}
      position={[person.x, person.y, person.z]}
      renderOrder={10}
      scale={hovered ? 1.15 : 1.0}
      onPointerOver={(e) => {
        e.stopPropagation();
        setHovered(true);
        document.body.style.cursor = 'pointer';
      }}
      onPointerOut={(e) => {
        e.stopPropagation();
        setHovered(false);
        document.body.style.cursor = 'default';
      }}
      onClick={(e) => {
        e.stopPropagation();
        const camIds = person.camera_ids ? person.camera_ids.join(',') : '';
        window.open(`/cameras.html?personId=${person.id}&cameras=${camIds}`, '_blank');
      }}
    >
      {/* Ground shadow disc - placed exactly on the floor */}
      <mesh ref={shadowRef} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]} scale={[targets.shadowScale, targets.shadowScale, 1]}>
        <circleGeometry args={[0.25, 16]} />
        <meshBasicMaterial
          color={hasAllPPE ? '#22cc66' : '#ee4455'}
          transparent
          opacity={0.15}
          depthWrite={false}
        />
      </mesh>

      {/* Posture body group */}
      <group
        ref={postureGroupRef}
        position={[targets.bodyPos.x, targets.bodyPos.y, targets.bodyPos.z]}
        rotation={[targets.bodyRot.x, targets.bodyRot.y, targets.bodyRot.z]}
        scale={[targets.bodyScale.x, targets.bodyScale.y, targets.bodyScale.z]}
      >
        {/* Body — capsule shape centered at [0, 0, 0] inside posture group */}
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

        {/* Head — sphere relative to body center */}
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
      </group>

      {/* PPE violation indicator group */}
      <group ref={indicatorRef} position={[targets.indicatorPos.x, targets.indicatorPos.y, targets.indicatorPos.z]}>
        {!hasAllPPE && (
          <mesh ref={glowRef}>
            <torusGeometry args={[0.12, 0.03, 8, 16]} />
            <meshBasicMaterial
              color="#ff2244"
              transparent
              opacity={0.8}
            />
          </mesh>
        )}
      </group>

      {/* Floating ID label group */}
      <group ref={labelGroupRef} position={[targets.labelPos.x, targets.labelPos.y, targets.labelPos.z]}>
        <Html
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
    </group>
  );
}
