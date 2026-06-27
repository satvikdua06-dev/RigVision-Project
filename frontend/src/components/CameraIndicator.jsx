import React, { useLayoutEffect, useRef } from 'react';
import * as THREE from 'three';

export default function CameraIndicator({ camera }) {
  const groupRef = useRef();

  useLayoutEffect(() => {
    if (groupRef.current && camera.lookAt) {
      // Point the camera towards its lookAt target
      const target = new THREE.Vector3(...camera.lookAt);
      groupRef.current.lookAt(target);
    }
  }, [camera.lookAt]);

  return (
    <group position={camera.position} ref={groupRef}>
      {/* Camera Body (Cylinder) */}
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0.15]}>
        <cylinderGeometry args={[0.08, 0.08, 0.3, 16]} />
        <meshStandardMaterial color="#222222" roughness={0.4} metalness={0.8} />
      </mesh>
      
      {/* Camera Lens */}
      <mesh position={[0, 0, 0.3]}>
        <sphereGeometry args={[0.05, 16, 16]} />
        <meshStandardMaterial color="#050505" roughness={0.1} metalness={0.9} />
      </mesh>

      {/* Mount Base */}
      <mesh position={[0, 0, 0]}>
        <boxGeometry args={[0.1, 0.1, 0.05]} />
        <meshStandardMaterial color="#333333" />
      </mesh>

      {/* Subtle FOV Cone */}
      <mesh position={[0, 0, 1.5]} rotation={[-Math.PI / 2, 0, 0]}>
        <coneGeometry args={[1.2, 3, 32]} />
        <meshBasicMaterial color="#ffffff" transparent opacity={0.03} depthWrite={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}
