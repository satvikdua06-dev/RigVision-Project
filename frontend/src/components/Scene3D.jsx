import { Suspense, useState, useMemo, useEffect } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, useGLTF, GizmoHelper, GizmoViewport, Grid, Environment, Html } from '@react-three/drei'
import * as THREE from 'three'

import { useRigStore } from '../stores/useRigStore.js'
import PersonAvatar from './PersonAvatar.jsx'
import ZonePlane from './ZonePlane.jsx'
import CameraIndicator from './CameraIndicator.jsx'
import SensorIndicator from './SensorIndicator.jsx'
import { ZONES } from '../utils/zonePositions.js'

// ── Reusable Room Component ───────────────────────────────────────────────────
function RigRoom({ positionOffset, rotationY, label }) {
  const { scene } = useGLTF('/kitchen_interior/scene.gltf')
  const [hoveredPart, setHoveredPart] = useState(null)

  // Deep clone the scene and its materials so Room A and Room B are independent
  const { clonedScene, scale, basePosition } = useMemo(() => {
    const clone = scene.clone()
    clone.traverse((node) => {
      if (node.isMesh && node.material) {
        node.material = node.material.clone()
      }
    })

    const box = new THREE.Box3().setFromObject(clone)
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())

    // Scale to fit approximately 4x5 meters
    const TARGET_SIZE = 5; 
    const computedScale = TARGET_SIZE / Math.max(size.x, size.y, size.z)

    const computedPosition = [
      -center.x * computedScale,
      -box.min.y * computedScale,
      -center.z * computedScale
    ]

    return { clonedScene: clone, scale: computedScale, basePosition: computedPosition }
  }, [scene])

  useEffect(() => {
    clonedScene.traverse((child) => {
      if (child.isMesh) {
        child.receiveShadow = true
        child.castShadow = false 
      }
    })
  }, [clonedScene])

  return (
    <group position={positionOffset} rotation={[0, rotationY, 0]}>
      <primitive 
        object={clonedScene} 
        scale={scale} 
        position={basePosition}
        onPointerOver={(e) => {
          e.stopPropagation()
          setHoveredPart({ name: e.object.name || 'Unknown', point: e.point })
          if (e.object.material) {
             e.object.material.emissive = new THREE.Color('#0055ff')
             e.object.material.emissiveIntensity = 0.3
          }
        }}
        onPointerOut={(e) => {
          e.stopPropagation()
          setHoveredPart(null)
          if (e.object.material) {
             e.object.material.emissive = new THREE.Color(0x000000)
          }
        }}
      />
      
      {/* Hover Popup */}
      {hoveredPart && (
        <Html position={hoveredPart.point} center distanceFactor={8} style={{ pointerEvents: 'none', zIndex: 100 }}>
          <div style={{
            background: 'rgba(5, 15, 28, 0.95)', border: '1px solid #00b4ff', borderRadius: '6px',
            padding: '4px 8px', color: '#e0f4ff', fontFamily: "'Share Tech Mono', monospace",
            fontSize: '10px', boxShadow: '0 4px 20px rgba(0,0,0,0.8)', whiteSpace: 'nowrap'
          }}>
            <span style={{ color: '#5a8aaa' }}>{label} PART:</span> <br/>
            <span style={{ color: '#00ffd5', fontSize: '11px' }}>{hoveredPart.name}</span>
          </div>
        </Html>
      )}
    </group>
  )
}

// ── Visual Bridge for the Corridor ────────────────────────────────────────────
function CorridorBridge() {
  return (
    <group position={[5, 0.01, 2.5]}>
      {/* Physical Floor of the bridge connecting x=4 to x=6 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[2, 2]} />
        <meshStandardMaterial color="#0a1a2a" roughness={0.8} metalness={0.2} />
      </mesh>
      {/* Side Rails */}
      <mesh position={[0, 0.5, -1]}>
        <boxGeometry args={[2, 1, 0.1]} />
        <meshStandardMaterial color="#00b4ff" transparent opacity={0.2} />
      </mesh>
      <mesh position={[0, 0.5, 1]}>
        <boxGeometry args={[2, 1, 0.1]} />
        <meshStandardMaterial color="#00b4ff" transparent opacity={0.2} />
      </mesh>
    </group>
  )
}

// ── Lighting & Floor ──────────────────────────────────────────────────────────
function Lighting() {
  return (
    <>
      <ambientLight intensity={0.7} color="#b0d8ff" />
      <directionalLight position={[5, 15, 5]} intensity={1.5} castShadow shadow-mapSize={[2048, 2048]} />
      <pointLight position={[2, 5, 2.5]} intensity={20} color="#00b4ff" /> {/* Zone A Light */}
      <pointLight position={[8, 5, 2.5]} intensity={20} color="#00ffd5" />  {/* Zone B Light */}
      <hemisphereLight skyColor="#0a1f3a" groundColor="#050a0f" intensity={0.6} />
    </>
  )
}

function Floor() {
  return (
    <>
      {/* Background Floor Plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[5, -0.01, 2.5]} receiveShadow>
        <planeGeometry args={[30, 20]} />
        <meshStandardMaterial color="#060e18" roughness={1} metalness={0} />
      </mesh>
      {/* Grid aligned to [0,10]x[0,5] */}
      <Grid position={[5, 0.002, 2.5]} args={[30, 20]} cellSize={1} cellThickness={0.4} cellColor="#0d2a3f" sectionSize={5} sectionThickness={0.8} sectionColor="#0a3a55" fadeDistance={30} fadeStrength={2} infiniteGrid={false} />
    </>
  )
}

// ── Main Scene ────────────────────────────────────────────────────────────────
export default function Scene3D() {
  const persons = useRigStore(s => s.persons)
  const zones = useRigStore(s => s.zones)
  const showAvatars = useRigStore(s => s.showAvatars)
  const showSensors = useRigStore(s => s.showSensors)
  const clearSelection = useRigStore(s => s.clearSelection)

  return (
    <Canvas
      shadows
      camera={{ position: [5, 8, 12], fov: 45, near: 0.1, far: 500 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: '#050a0f' }}
      onClick={clearSelection}
    >
      <Environment preset="city" /> 
      <Lighting />
      <Floor />

      <Suspense fallback={null}>
        {/* ROOM A (Center at x=2, z=2.5) */}
        <RigRoom positionOffset={[2, 0, 2.5]} rotationY={0} label="ZONE A" />
        
        {/* CORRIDOR (Center at x=5, z=2.5) */}
        <CorridorBridge />

        {/* ROOM B (Center at x=8, z=2.5) */}
        <RigRoom positionOffset={[8, 0, 2.5]} rotationY={Math.PI} label="ZONE B" />
      </Suspense>

      {/* Zone Overlays */}
      {Object.entries(zones).map(([id, zone]) => {
        // Find the matching ZONES definition for accurate positioning if available
        const staticDef = ZONES[id]
        if (!staticDef) return null
        return <ZonePlane key={id} zoneId={id} zone={zone} staticDef={staticDef} />
      })}

      {/* Personnel Avatars */}
      {showAvatars && persons.map(p => (
        <PersonAvatar key={p.id} person={p} />
      ))}

      {/* Cameras and Sensors */}
      {showSensors && Object.values(ZONES).map((zone, idx) => (
        <group key={`zone-sensors-${idx}`}>
          {zone.camera && <CameraIndicator camera={zone.camera} />}
          {(zone.sensors || []).map(sensor => (
            <SensorIndicator key={sensor.id} sensor={sensor} />
          ))}
        </group>
      ))}

      <OrbitControls 
        target={[5, 1.5, 2.5]} 
        enableDamping dampingFactor={0.08} 
        minDistance={2} maxDistance={50} 
        minPolarAngle={0.1} maxPolarAngle={Math.PI / 2.1} 
        makeDefault 
      />
      <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
        <GizmoViewport axisColors={['#ff3b3b', '#00e676', '#00b4ff']} labelColor="#fff" />
      </GizmoHelper>
    </Canvas>
  )
}
useGLTF.preload('/kitchen_interior/scene.gltf')