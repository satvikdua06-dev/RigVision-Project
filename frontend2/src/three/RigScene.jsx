/**
 * RigVision-3D — 3D Scene Wrapper
 * 
 * Sets up the Three.js Canvas with:
 * - Camera positioned to see the full room layout
 * - Ambient + directional lighting
 * - OrbitControls for mouse-based rotation/zoom
 * - Grid helper on the floor
 * - All child 3D components (RigModel, PersonAvatars, SensorOverlays)
 */

import React from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Environment } from '@react-three/drei';
import RigModel from './RigModel';
import PersonAvatar from './PersonAvatar';
import SensorOverlay from './SensorOverlay';
import useRealtimeStore from '../stores/realtimeStore';

export default function RigScene() {
  const persons = useRealtimeStore((s) => s.persons);
  const showAvatars = useRealtimeStore((s) => s.showAvatars);
  const showSensors = useRealtimeStore((s) => s.showSensors);

  return (
    <Canvas
      camera={{
        position: [5, 8, 14],
        fov: 50,
        near: 0.1,
        far: 100,
      }}
      shadows
      gl={{ antialias: true, alpha: false }}
      style={{ background: '#06060b' }}
    >
      {/* Lighting */}
      <ambientLight intensity={0.4} />
      <directionalLight
        position={[8, 12, 8]}
        intensity={0.8}
        castShadow
        shadow-mapSize={[2048, 2048]}
      />
      <pointLight position={[2, 2.5, 2.5]} intensity={0.3} color="#4488ff" />
      <pointLight position={[8, 2.5, 2.5]} intensity={0.3} color="#44ff88" />

      {/* Fog for depth perception */}
      <fog attach="fog" args={['#06060b', 15, 35]} />

      {/* Grid on the floor */}
      <Grid
        args={[20, 20]}
        position={[5, -0.01, 2.5]}
        cellSize={1}
        cellThickness={0.5}
        cellColor="#1a1a30"
        sectionSize={5}
        sectionThickness={1}
        sectionColor="#252545"
        fadeDistance={25}
        infiniteGrid
      />

      {/* The 3D room model (floors, walls, zones, equipment) */}
      <RigModel />

      {/* Person avatars */}
      {showAvatars && persons.map((person) => (
        <PersonAvatar key={person.id} person={person} />
      ))}

      {/* Sensor overlays (floating cards above zones) */}
      {showSensors && <SensorOverlay />}

      {/* Camera controls */}
      <OrbitControls
        target={[5, 1, 2.5]}
        enableDamping
        dampingFactor={0.08}
        minDistance={3}
        maxDistance={25}
        maxPolarAngle={Math.PI / 2.1}
      />
    </Canvas>
  );
}
