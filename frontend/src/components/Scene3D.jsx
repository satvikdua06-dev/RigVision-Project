import { Suspense, useState, useMemo, useEffect, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, useGLTF, GizmoHelper, GizmoViewport, Grid, Environment, Html } from '@react-three/drei'
import * as THREE from 'three'

import { useRigStore } from '../stores/useRigStore.js'
import PersonAvatar from './PersonAvatar.jsx'
import ZonePlane from './ZonePlane.jsx'
import CameraIndicator from './CameraIndicator.jsx'
import SensorIndicator from './SensorIndicator.jsx'
import { ZONES } from '../utils/zonePositions.js'

// ── GPU Throttler (WebGL Render Call Limiter) ──────────────────────────────────
function RenderThrottler() {
  const fpsLimit = useRigStore(s => s.fpsLimit)
  const lastRender = useRef(0)
  
  useFrame(({ gl, scene, camera }) => {
    const now = performance.now()
    const delay = 1000 / fpsLimit
    if (now - lastRender.current >= delay) {
      lastRender.current = now
      gl.render(scene, camera)
    }
  }, 1) // priority > 0 disables automatic rendering
  
  return null
}

// Helper to check if raycast hit an avatar group/ancestor
function findAvatarInIntersections(intersections) {
  if (!intersections) return null
  for (const intersect of intersections) {
    let curr = intersect.object
    while (curr) {
      if (curr.userData && curr.userData.isAvatar) {
        return curr.userData.personId
      }
      curr = curr.parent
    }
  }
  return null
}

// ── Reusable Room Component ───────────────────────────────────────────────────
function RigRoom({ positionOffset, rotationY, label, zoneId }) {
  const { scene } = useGLTF('/kitchen_interior/scene.gltf')
  const [hoveredPart, setHoveredPart] = useState(null)
  const wallOpacity = useRigStore(s => s.wallOpacity)
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const selectZone = useRigStore(s => s.selectZone)
  const selectPerson = useRigStore(s => s.selectPerson)

  // Deep clone the scene and its materials so Room A and Room B are independent
  const { clonedScene, scale, basePosition } = useMemo(() => {
    const clone = scene.clone()
    clone.traverse((node) => {
      if (node.isMesh && node.material) {
        node.material = node.material.clone()
      }
    })

    clone.updateMatrixWorld(true)
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
        if (child.material) {
          child.material.transparent = wallOpacity < 1.0
          child.material.opacity = wallOpacity
          // Depth-write settings to prevent translucency z-fighting
          child.material.depthWrite = wallOpacity >= 0.95
        }
      }
    })
  }, [clonedScene, wallOpacity])

  return (
    <group position={positionOffset} rotation={[0, rotationY, 0]}>
      <primitive 
        object={clonedScene} 
        scale={scale} 
        position={basePosition}
        raycast={zoneSelectMode ? undefined : null}
        onClick={zoneSelectMode ? (e) => {
          e.stopPropagation()
          const clickedAvatarId = findAvatarInIntersections(e.intersections)
          if (clickedAvatarId !== null) {
            selectPerson(clickedAvatarId)
          } else {
            selectZone(zoneId)
          }
        } : undefined}
        onPointerOver={zoneSelectMode ? (e) => {
          e.stopPropagation()
          setHoveredPart({ name: e.object.name || 'Unknown', point: e.point })
          if (e.object.material) {
             e.object.material.emissive = new THREE.Color('#0055ff')
             e.object.material.emissiveIntensity = 0.3
           }
        } : undefined}
        onPointerOut={zoneSelectMode ? (e) => {
          e.stopPropagation()
          setHoveredPart(null)
          if (e.object.material) {
             e.object.material.emissive = new THREE.Color(0x000000)
          }
        } : undefined}
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
function CorridorBridge({ positionOffset, zoneId }) {
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const selectZone = useRigStore(s => s.selectZone)
  const selectPerson = useRigStore(s => s.selectPerson)
  return (
    <group 
      position={positionOffset} 
      raycast={zoneSelectMode ? undefined : null}
      onClick={zoneSelectMode ? (e) => {
        e.stopPropagation()
        const clickedAvatarId = findAvatarInIntersections(e.intersections)
        if (clickedAvatarId !== null) {
          selectPerson(clickedAvatarId)
        } else {
          selectZone(zoneId)
        }
      } : undefined}
    >
      {/* Catwalk platform base (X size 2.2 to overlap 10cm into rooms, closing all gaps) */}
      <mesh position={[0, -0.025, 0]} receiveShadow>
        <boxGeometry args={[2.2, 0.05, 2.0]} />
        <meshStandardMaterial color="#111d2e" roughness={0.3} metalness={0.85} />
      </mesh>
      
      {/* Corner/Structural support pillars (extending down 3 meters to floor below or ground) */}
      <mesh position={[-1.1, -1.5, -0.95]}>
        <cylinderGeometry args={[0.04, 0.04, 3.0]} />
        <meshStandardMaterial color="#0b1320" roughness={0.4} metalness={0.9} />
      </mesh>
      <mesh position={[1.1, -1.5, -0.95]}>
        <cylinderGeometry args={[0.04, 0.04, 3.0]} />
        <meshStandardMaterial color="#0b1320" roughness={0.4} metalness={0.9} />
      </mesh>
      <mesh position={[-1.1, -1.5, 0.95]}>
        <cylinderGeometry args={[0.04, 0.04, 3.0]} />
        <meshStandardMaterial color="#0b1320" roughness={0.4} metalness={0.9} />
      </mesh>
      <mesh position={[1.1, -1.5, 0.95]}>
        <cylinderGeometry args={[0.04, 0.04, 3.0]} />
        <meshStandardMaterial color="#0b1320" roughness={0.4} metalness={0.9} />
      </mesh>

      {/* Side Handrails on both sides (Z = -0.95 and Z = 0.95) */}
      {[-0.95, 0.95].map((zVal, idx) => (
        <group key={`handrail-${idx}`} position={[0, 0, zVal]}>
          {/* Vertical safety stanchions/posts */}
          {[-1.1, -0.36, 0.36, 1.1].map((xVal, pIdx) => (
            <mesh key={`post-${pIdx}`} position={[xVal, 0.5, 0]} castShadow>
              <cylinderGeometry args={[0.02, 0.02, 1.0]} />
              <meshStandardMaterial color="#00b4ff" metalness={0.95} roughness={0.15} emissive="#004488" emissiveIntensity={0.2} />
            </mesh>
          ))}
          
          {/* Horizontal Top handrail tube */}
          <mesh position={[0, 1.0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow>
            <cylinderGeometry args={[0.015, 0.015, 2.2]} />
            <meshStandardMaterial color="#00b4ff" metalness={0.95} roughness={0.15} emissive="#004488" emissiveIntensity={0.2} />
          </mesh>

          {/* Horizontal Mid safety tube */}
          <mesh position={[0, 0.5, 0]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.01, 0.01, 2.2]} />
            <meshStandardMaterial color="#00b4ff" metalness={0.9} roughness={0.2} />
          </mesh>

          {/* Semi-transparent safety glass panel inside the rail frame */}
          <mesh position={[0, 0.48, 0]}>
            <boxGeometry args={[2.16, 0.82, 0.012]} />
            <meshStandardMaterial color="#00ffd5" transparent opacity={0.15} roughness={0.05} metalness={0.9} />
          </mesh>
        </group>
      ))}
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
      <pointLight position={[5, 1.5, 2.5]} intensity={15} color="#ffaa00" /> {/* Corridor F0 Amber Glow */}
      <pointLight position={[5, 4.5, 2.5]} intensity={15} color="#ffaa00" /> {/* Corridor F1 Amber Glow */}
      <hemisphereLight skyColor="#0a1f3a" groundColor="#050a0f" intensity={0.6} />
    </>
  )
}

function Floor({ showFloor0, showFloor1 }) {
  return (
    <>
      {/* Background Floor Plane at Floor 0 */}
      {showFloor0 && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[5, -0.01, 2.5]} receiveShadow>
          <planeGeometry args={[30, 20]} />
          <meshStandardMaterial color="#03080e" roughness={0.35} metalness={0.8} />
        </mesh>
      )}
      
      {/* Grid aligned to [0,10]x[0,5] for Floor 0 */}
      {showFloor0 && (
        <Grid position={[5, 0.002, 2.5]} args={[30, 20]} cellSize={1} cellThickness={0.4} cellColor="#102e45" sectionSize={5} sectionThickness={0.8} sectionColor="#18527a" fadeDistance={30} fadeStrength={2} infiniteGrid={false} />
      )}

      {/* Grid aligned for Floor 1 */}
      {showFloor1 && (
        <Grid position={[5, 3.002, 2.5]} args={[30, 20]} cellSize={1} cellThickness={0.4} cellColor="#102e45" sectionSize={5} sectionThickness={0.8} sectionColor="#18527a" fadeDistance={30} fadeStrength={2} infiniteGrid={false} />
      )}
    </>
  )
}

// ── Sleek Floating Settings Panel UI ───────────────────────────────────────────
function SettingsPanel() {
  const [isOpen, setIsOpen] = useState(true)
  const wallOpacity = useRigStore(s => s.wallOpacity)
  const setWallOpacity = useRigStore(s => s.setWallOpacity)
  const fpsLimit = useRigStore(s => s.fpsLimit)
  const setFpsLimit = useRigStore(s => s.setFpsLimit)
  const floorFilter = useRigStore(s => s.floorFilter)
  const setFloorFilter = useRigStore(s => s.setFloorFilter)
  const clearTrackingCache = useRigStore(s => s.clearTrackingCache)
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const setZoneSelectMode = useRigStore(s => s.setZoneSelectMode)
  const [clearing, setClearing] = useState(false)

  const handleClearCache = async () => {
    setClearing(true)
    await clearTrackingCache()
    setTimeout(() => setClearing(false), 1000)
  }

  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      right: 20,
      zIndex: 1000,
      fontFamily: "'Share Tech Mono', monospace",
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'flex-end',
    }}>
      {/* Toggle Button */}
      <button 
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: 'rgba(5, 15, 28, 0.85)',
          border: '1px solid #00b4ff',
          borderRadius: '6px',
          color: '#00ffd5',
          padding: '8px 12px',
          cursor: 'pointer',
          boxShadow: '0 0 10px rgba(0, 180, 255, 0.3)',
          transition: 'all 0.2s',
          fontSize: '11px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          marginBottom: isOpen ? '10px' : '0px',
        }}
      >
        <span>⚙</span>
        <span>{isOpen ? 'CLOSE CONTROLS' : 'STREAM CONTROLS'}</span>
      </button>

      {/* Main Panel */}
      {isOpen && (
        <div style={{
          width: '280px',
          background: 'rgba(5, 15, 28, 0.8)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(0, 180, 255, 0.35)',
          borderRadius: '10px',
          padding: '16px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)',
          color: '#e0f4ff',
          display: 'flex',
          flexDirection: 'column',
          gap: '14px',
        }}>
          <div style={{ borderBottom: '1px solid rgba(0, 180, 255, 0.2)', paddingBottom: '8px', fontSize: '13px', fontWeight: 'bold', color: '#00ffd5', letterSpacing: '1px' }}>
            RIGVISION CONTROL PANEL
          </div>

          {/* Floor Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: '#5a8aaa' }}>FLOOR VIEW FILTER</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              {['all', 0, 1].map((f) => (
                <button
                  key={f}
                  onClick={() => setFloorFilter(f)}
                  style={{
                    flex: 1,
                    background: floorFilter === f ? '#00b4ff44' : 'rgba(10, 25, 47, 0.6)',
                    border: `1px solid ${floorFilter === f ? '#00ffd5' : 'rgba(0, 180, 255, 0.25)'}`,
                    borderRadius: '4px',
                    color: floorFilter === f ? '#fff' : '#8892b0',
                    padding: '6px 4px',
                    fontSize: '11px',
                    cursor: 'pointer',
                    textTransform: 'uppercase',
                    transition: 'all 0.15s',
                  }}
                >
                  {f === 'all' ? 'All' : `F${f}`}
                </button>
              ))}
            </div>
          </div>

          {/* Click Interaction Target Toggle */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: '#5a8aaa' }}>CLICK INTERACTION TARGET</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              <button
                onClick={() => setZoneSelectMode(true)}
                style={{
                  flex: 1,
                  background: zoneSelectMode ? '#00b4ff44' : 'rgba(10, 25, 47, 0.6)',
                  border: `1px solid ${zoneSelectMode ? '#00ffd5' : 'rgba(0, 180, 255, 0.25)'}`,
                  borderRadius: '4px',
                  color: zoneSelectMode ? '#fff' : '#8892b0',
                  padding: '6px 4px',
                  fontSize: '11px',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  fontFamily: "'Share Tech Mono', monospace",
                }}
              >
                Zones
              </button>
              <button
                onClick={() => setZoneSelectMode(false)}
                style={{
                  flex: 1,
                  background: !zoneSelectMode ? '#00b4ff44' : 'rgba(10, 25, 47, 0.6)',
                  border: `1px solid ${!zoneSelectMode ? '#00ffd5' : 'rgba(0, 180, 255, 0.25)'}`,
                  borderRadius: '4px',
                  color: !zoneSelectMode ? '#fff' : '#8892b0',
                  padding: '6px 4px',
                  fontSize: '11px',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  fontFamily: "'Share Tech Mono', monospace",
                }}
              >
                Avatars
              </button>
            </div>
          </div>

          {/* Wall Opacity Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
              <span style={{ color: '#5a8aaa' }}>WALL OPACITY</span>
              <span style={{ color: '#00ffd5' }}>{(wallOpacity * 100).toFixed(0)}%</span>
            </div>
            <input 
              type="range" 
              min="0.1" 
              max="1.0" 
              step="0.05" 
              value={wallOpacity} 
              onChange={(e) => setWallOpacity(parseFloat(e.target.value))}
              style={{
                width: '100%',
                background: 'rgba(10, 25, 47, 0.8)',
                cursor: 'pointer',
                accentColor: '#00b4ff',
              }}
            />
          </div>

          {/* FPS Limiter Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
              <span style={{ color: '#5a8aaa' }}>SCENE RE-POLL / FPS LIMIT</span>
              <span style={{ color: '#00ffd5' }}>{fpsLimit} FPS</span>
            </div>
            <input 
              type="range" 
              min="1" 
              max="30" 
              step="1" 
              value={fpsLimit} 
              onChange={(e) => setFpsLimit(parseInt(e.target.value))}
              style={{
                width: '100%',
                background: 'rgba(10, 25, 47, 0.8)',
                cursor: 'pointer',
                accentColor: '#00b4ff',
              }}
            />
          </div>

          {/* Toggles and Buttons */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '4px' }}>
            {/* Clear Tracking Cache Button */}
            <button
              onClick={handleClearCache}
              disabled={clearing}
              style={{
                width: '100%',
                background: clearing ? '#ff3b3b44' : 'rgba(255, 59, 59, 0.1)',
                border: `1px solid ${clearing ? '#ff3b3b' : 'rgba(255, 59, 59, 0.4)'}`,
                borderRadius: '4px',
                color: '#ff8888',
                padding: '8px',
                fontSize: '11px',
                cursor: clearing ? 'not-allowed' : 'pointer',
                letterSpacing: '0.5px',
                transition: 'all 0.2s',
                marginTop: '4px',
              }}
            >
              {clearing ? 'COMMAND SENT...' : 'CLEAR TRACKING CACHE'}
            </button>
          </div>
        </div>
      )}
      
    </div>
  )
}

// ── Main Scene ────────────────────────────────────────────────────────────────
export default function Scene3D() {
  const persons = useRigStore(s => s.persons)
  const zones = useRigStore(s => s.zones)
  const showAvatars = useRigStore(s => s.showAvatars)
  const showSensors = useRigStore(s => s.showSensors)
  const floorFilter = useRigStore(s => s.floorFilter)
  const clearSelection = useRigStore(s => s.clearSelection)

  const showFloor0 = floorFilter === 'all' || floorFilter === 0
  const showFloor1 = floorFilter === 'all' || floorFilter === 1

  // Dynamically calculate camera center Y coordinate based on floor view
  const targetY = floorFilter === 'all' ? 3.0 : (floorFilter === 1 ? 4.5 : 1.5)

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        camera={{ position: [5, 8, 12], fov: 45, near: 0.1, far: 500 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#050a0f' }}
        onClick={clearSelection}
      >
        <Environment preset="city" /> 
        <Lighting />
        <Floor showFloor0={showFloor0} showFloor1={showFloor1} />
        <RenderThrottler />

        <Suspense fallback={null}>
          {/* FLOOR 0 (height = 0m to 3m) */}
          {showFloor0 && (
            <>
              {/* ROOM A (Center at x=2, z=2.5) */}
              <RigRoom positionOffset={[2, 0, 2.5]} rotationY={0} label="ZONE A (F0)" zoneId="zone_a" />
              
              {/* CORRIDOR (Center at x=5, z=2.5) */}
              <CorridorBridge positionOffset={[5, 0.01, 2.5]} zoneId="corridor" />

              {/* ROOM B (Center at x=8, z=2.5) */}
              <RigRoom positionOffset={[8, 0, 2.5]} rotationY={Math.PI} label="ZONE B (F0)" zoneId="zone_b" />
            </>
          )}

          {/* FLOOR 1 (height = 3m to 6m) */}
          {showFloor1 && (
            <>
              {/* ROOM A (Center at x=2, y=3, z=2.5) */}
              <RigRoom positionOffset={[2, 3, 2.5]} rotationY={0} label="ZONE A (F1)" zoneId="zone_a_f1" />
              
              {/* CORRIDOR (Center at x=5, y=3, z=2.5) */}
              <CorridorBridge positionOffset={[5, 3.01, 2.5]} zoneId="corridor_f1" />

              {/* ROOM B (Center at x=8, y=3, z=2.5) */}
              <RigRoom positionOffset={[8, 3, 2.5]} rotationY={Math.PI} label="ZONE B (F1)" zoneId="zone_b_f1" />
            </>
          )}
        </Suspense>

        {/* Zone Overlays */}
        {Object.entries(zones).map(([id, zone]) => {
          const staticDef = ZONES[id]
          if (!staticDef) return null
          
          // Filter zone by floor view
          const zoneFloor = staticDef.floor ?? 0
          const isVisible = floorFilter === 'all' || zoneFloor === floorFilter
          if (!isVisible) return null

          return <ZonePlane key={id} zoneId={id} zone={zone} staticDef={staticDef} />
        })}

        {/* Personnel Avatars */}
        {showAvatars && persons.map(p => {
          // Default missing floor to floor 0
          const personFloor = p.floor ?? 0
          const isVisible = floorFilter === 'all' || personFloor === floorFilter
          if (!isVisible) return null

          return <PersonAvatar key={p.id} person={p} />
        })}

        {/* Cameras and Sensors */}
        {showSensors && Object.entries(ZONES).map(([id, zone], idx) => {
          const zoneFloor = zone.floor ?? 0
          const isVisible = floorFilter === 'all' || zoneFloor === floorFilter
          if (!isVisible) return null

          return (
            <group key={`zone-sensors-${idx}`}>
              {zone.camera && <CameraIndicator camera={zone.camera} />}
              {(zone.sensors || []).map(sensor => (
                <SensorIndicator key={sensor.id} sensor={sensor} />
              ))}
            </group>
          )
        })}

        <OrbitControls 
          target={[5, targetY, 2.5]} 
          enableDamping dampingFactor={0.08} 
          minDistance={2} maxDistance={50} 
          minPolarAngle={0.1} maxPolarAngle={Math.PI / 2.1} 
          makeDefault 
        />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport axisColors={['#ff3b3b', '#00e676', '#00b4ff']} labelColor="#fff" />
        </GizmoHelper>
      </Canvas>
      
      {/* Settings Overlay */}
      <SettingsPanel />
    </div>
  )
}
useGLTF.preload('/kitchen_interior/scene.gltf')