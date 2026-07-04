import { Suspense, useState, useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, GizmoHelper, GizmoViewport, Grid, Environment, Html } from '@react-three/drei'
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

// ── Facility dimensions (one bay) ───────────────────────────────────────────────
// Each room is a 5m (X) × 3.85m (Z) bay, 3m tall. Built procedurally in local space
// spanning x∈[0,5], z∈[0,3.85], y∈[0,3]; the group is shifted up by `baseY` per floor.
const BAY_W = 5, BAY_D = 3.85, BAY_H = 3.0

// Shared material presets (memo-friendly plain objects fed to <meshStandardMaterial/>).
const STEEL_DARK = { color: '#262c35', metalness: 0.85, roughness: 0.5 }
const STEEL_MID  = { color: '#39424f', metalness: 0.8, roughness: 0.42 }
const STEEL_LITE = { color: '#4a5563', metalness: 0.75, roughness: 0.4 }

// A reusable steel beam/box.
function Beam({ args, position, mat = STEEL_MID, castShadow = true }) {
  return (
    <mesh position={position} castShadow={castShadow} receiveShadow>
      <boxGeometry args={args} />
      <meshStandardMaterial {...mat} />
    </mesh>
  )
}

// ── Hand-built rig room shell ───────────────────────────────────────────────────
function RigRoom({ baseY, zoneId, isUpper }) {
  const wallOpacity = useRigStore(s => s.wallOpacity)
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const selectZone = useRigStore(s => s.selectZone)
  const selectPerson = useRigStore(s => s.selectPerson)

  const handleClick = zoneSelectMode ? (e) => {
    e.stopPropagation()
    const id = findAvatarInIntersections(e.intersections)
    if (id !== null) selectPerson(id); else selectZone(zoneId)
  } : undefined

  // Plain solid walls: opacity directly driven by wallOpacity, becoming fully opaque at 1.0.
  const wallOpacityValue = wallOpacity
  const isWallTransparent = wallOpacity < 1.0

  const floorHeight = isUpper ? 0.14 : 0.02
  const floorPosY = isUpper ? -0.07 : 0.01
  const inlaidPosY = isUpper ? 0.011 : 0.021

  return (
    <group position={[0, baseY, 0]}>
      {/* Floor deck (primary click target) */}
      <mesh position={[BAY_W / 2, floorPosY, BAY_D / 2]} receiveShadow
        raycast={zoneSelectMode ? undefined : null} onClick={handleClick}>
        <boxGeometry args={[BAY_W, floorHeight, BAY_D]} />
        <meshStandardMaterial color="#1c222b" metalness={0.65} roughness={0.7} />
      </mesh>
      {/* Inlaid deck panel (subtle two-tone) */}
      <mesh position={[BAY_W / 2, inlaidPosY, BAY_D / 2]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[BAY_W - 0.5, BAY_D - 0.5]} />
        <meshStandardMaterial color="#222a34" metalness={0.55} roughness={0.65} />
      </mesh>

      {/* Plain walls (4 sides, full-height) */}
      {[
        { args: [BAY_W, BAY_H, 0.03], pos: [BAY_W / 2, BAY_H / 2, 0] },
        { args: [BAY_W, BAY_H, 0.03], pos: [BAY_W / 2, BAY_H / 2, BAY_D] },
        { args: [0.03, BAY_H, BAY_D], pos: [0, BAY_H / 2, BAY_D / 2] },
        { args: [0.03, BAY_H, BAY_D], pos: [BAY_W, BAY_H / 2, BAY_D / 2] },
      ].map((w, i) => (
        <mesh key={`wall${i}`} position={w.pos} raycast={null}>
          <boxGeometry args={w.args} />
          <meshStandardMaterial color="#39424f" transparent={isWallTransparent} opacity={wallOpacityValue}
            metalness={0.15} roughness={0.85} depthWrite={!isWallTransparent} side={THREE.DoubleSide} />
        </mesh>
      ))}
    </group>
  )
}

// ── Equipment props ─────────────────────────────────────────────────────────────
// Stylised, type-specific machinery built from primitives. Each prop is clickable
// (selects its zone) and highlights on hover.
function EquipmentProp({ item, zoneId }) {
  const [hovered, setHovered] = useState(false)
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const selectZone = useRigStore(s => s.selectZone)
  const [w, h, d] = item.size
  const emissive = hovered ? '#5b8def' : '#000000'
  const ei = hovered ? 0.35 : 0
  const mat = { color: item.color, metalness: 0.7, roughness: 0.5, emissive, emissiveIntensity: ei }

  // Body shapes per equipment type.
  const body = (() => {
    switch (item.type) {
      case 'pump':
        return (
          <group position={[0, 0, 0]}>
            {/* Main horizontal pump body */}
            <mesh position={[0, -h * 0.15, 0]} castShadow receiveShadow>
              <boxGeometry args={[w * 0.85, h * 0.7, d * 0.85]} />
              <meshStandardMaterial {...mat} />
            </mesh>
            {/* Cylindrical motor drive on the side */}
            <mesh position={[w * 0.45, -h * 0.25, 0]} rotation={[0, 0, Math.PI / 2]} castShadow>
              <cylinderGeometry args={[h * 0.22, h * 0.22, w * 0.3, 16]} />
              <meshStandardMaterial color="#2b323c" metalness={0.8} roughness={0.4} emissive={emissive} emissiveIntensity={ei} />
            </mesh>
            {/* Small outlet pipe */}
            <mesh position={[-w * 0.2, h * 0.35, 0]} castShadow>
              <cylinderGeometry args={[0.08, 0.08, h * 0.3, 12]} />
              <meshStandardMaterial color="#4a5563" metalness={0.7} roughness={0.4} />
            </mesh>
          </group>
        )
      case 'compressor':
        return (
          <group position={[0, 0, 0]}>
            {/* Bottom support base plate */}
            <mesh position={[0, -h * 0.5 + 0.04, 0]} castShadow receiveShadow>
              <boxGeometry args={[w * 0.95, 0.08, d * 0.95]} />
              <meshStandardMaterial color="#2b323c" metalness={0.6} roughness={0.6} />
            </mesh>
            {/* Large horizontal cylindrical tank */}
            <mesh position={[0, -h * 0.5 + 0.08 + d * 0.35, 0]} rotation={[0, 0, Math.PI / 2]} castShadow receiveShadow>
              <cylinderGeometry args={[d * 0.35, d * 0.35, w * 0.85, 20]} />
              <meshStandardMaterial {...mat} />
            </mesh>
            {/* Top motor box */}
            <mesh position={[0, h * 0.5 - h * 0.125, 0]} castShadow>
              <boxGeometry args={[w * 0.45, h * 0.25, d * 0.6]} />
              <meshStandardMaterial color="#46505d" metalness={0.78} roughness={0.4} emissive={emissive} emissiveIntensity={ei} />
            </mesh>
          </group>
        )
      case 'wellhead':
        return (
          <group position={[0, 0, 0]}>
            {/* Main vertical pipe column */}
            <mesh position={[0, 0, 0]} castShadow receiveShadow>
              <cylinderGeometry args={[w * 0.18, w * 0.18, h, 16]} />
              <meshStandardMaterial {...mat} />
            </mesh>
            {/* Flange ring 1 */}
            <mesh position={[0, -h * 0.25, 0]} castShadow>
              <cylinderGeometry args={[w * 0.28, w * 0.28, h * 0.08, 16]} />
              <meshStandardMaterial color="#2b323c" metalness={0.8} roughness={0.5} />
            </mesh>
            {/* Flange ring 2 */}
            <mesh position={[0, h * 0.25, 0]} castShadow>
              <cylinderGeometry args={[w * 0.28, w * 0.28, h * 0.08, 16]} />
              <meshStandardMaterial color="#2b323c" metalness={0.8} roughness={0.5} />
            </mesh>
            {/* Sleek horizontal hand valve wheel at the top */}
            <mesh position={[0, h * 0.45, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
              <torusGeometry args={[w * 0.26, 0.035, 8, 24]} />
              <meshStandardMaterial color="#c2543f" metalness={0.65} roughness={0.4} emissive={emissive} emissiveIntensity={ei} />
            </mesh>
          </group>
        )
      case 'control_panel':
        return (
          <group position={[0, 0, 0]}>
            {/* Sleek vertical terminal body */}
            <mesh position={[0, 0, 0]} castShadow receiveShadow>
              <boxGeometry args={[w, h, d]} />
              <meshStandardMaterial {...mat} />
            </mesh>
            {/* Integrated glowing interface display screen */}
            <mesh position={[0, h * 0.15, d / 2 + 0.01]}>
              <planeGeometry args={[w * 0.8, h * 0.45]} />
              <meshStandardMaterial color="#0b111a" emissive="#5b8def" emissiveIntensity={hovered ? 1.0 : 0.6} />
            </mesh>
          </group>
        )
      default: // storage (Cabinet / Locker)
        return (
          <group position={[0, 0, 0]}>
            {/* Main double-door locker box */}
            <mesh position={[0, 0, 0]} castShadow receiveShadow>
              <boxGeometry args={[w, h, d]} />
              <meshStandardMaterial {...mat} />
            </mesh>
            {/* Vertical door seam line */}
            <mesh position={[0, 0, d / 2 + 0.005]}>
              <boxGeometry args={[0.015, h * 0.92, 0.01]} />
              <meshStandardMaterial color="#1f2937" />
            </mesh>
            {/* Sleek metal handles */}
            {[-0.08, 0.08].map((ox) => (
              <mesh key={ox} position={[ox, 0, d / 2 + 0.015]} castShadow>
                <cylinderGeometry args={[0.008, 0.008, h * 0.15, 8]} />
                <meshStandardMaterial color="#d1d5db" metalness={0.9} roughness={0.2} />
              </mesh>
            ))}
          </group>
        )
    }
  })()

  return (
    <group position={item.position}
      raycast={zoneSelectMode ? undefined : null}
      onClick={zoneSelectMode ? (e) => { e.stopPropagation(); selectZone(zoneId) } : undefined}
      onPointerOver={zoneSelectMode ? (e) => { e.stopPropagation(); setHovered(true) } : undefined}
      onPointerOut={zoneSelectMode ? (e) => { e.stopPropagation(); setHovered(false) } : undefined}
    >
      {body}
      {hovered && (
        <Html position={[0, h * 0.7 + 0.3, 0]} center distanceFactor={12} style={{ pointerEvents: 'none' }}>
          <div style={{
            background: 'rgba(18,22,29,0.6)', backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
            border: '1px solid rgba(255,255,255,0.1)', borderRadius: 999, padding: '3px 10px',
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'rgba(230,233,239,0.95)', whiteSpace: 'nowrap',
          }}>{item.name}</div>
        </Html>
      )}
    </group>
  )
}

function Equipment({ zoneId }) {
  const zone = ZONES[zoneId]
  if (!zone) return null
  return zone.equipment.map((item) => <EquipmentProp key={item.id} item={item} zoneId={zoneId} />)
}

// ── Lighting & Floor ──────────────────────────────────────────────────────────
function Lighting() {
  return (
    <>
      {/* Cool, soft ambient light to fill the scene and add dark indigo depth to shadows */}
      <ambientLight intensity={0.5} color="#141d2b" />
      
      {/* Strong, warm white key light (sun-like) casting soft shadows across the rooms */}
      <directionalLight 
        position={[12, 22, 10]} 
        intensity={2.2} 
        castShadow
        shadow-mapSize={[2048, 2048]} 
        shadow-camera-far={40}
        shadow-camera-left={-10} 
        shadow-camera-right={10}
        shadow-camera-top={10} 
        shadow-camera-bottom={-10} 
        shadow-bias={-0.0005}
      />
      
      {/* Warm orange-gold key fill point lights inside the rooms to illuminate the machines */}
      <pointLight position={[2.5, 1.2, 1.9]} intensity={60} distance={10} decay={2} color="#ffd4a3" /> {/* Room A Key Fill */}
      <pointLight position={[2.5, 4.2, 1.9]} intensity={60} distance={10} decay={2} color="#ffb480" /> {/* Room B Key Fill */}

      {/* Cool cyan-blue fill point lights to bounce back and provide dual-colored aesthetic reflections on the metal equipment */}
      <pointLight position={[1.2, 2.2, 3.2]} intensity={35} distance={9} decay={2} color="#5b8def" /> {/* Room A Cool Fill */}
      <pointLight position={[3.8, 5.2, 0.8]} intensity={35} distance={9} decay={2} color="#5b8def" /> {/* Room B Cool Fill */}
      
      {/* Hemisphere light for ground bounce and sky glow contrast */}
      <hemisphereLight skyColor="#1a2b4c" groundColor="#0a0f1d" intensity={0.7} />
    </>
  )
}

function Floor({ showFloor0, showFloor1 }) {
  // Rooms share the 5×3.85m footprint centred at x=2.5, z=1.925. Floor-0 grid sits at y=0
  // (Room A), floor-1 grid at y=3.0 (Room B's deck / Room A's ceiling line).
  return (
    <>
      {/* Background ground plane */}
      {showFloor0 && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[2.5, -0.01, 1.925]} receiveShadow>
          <planeGeometry args={[36, 28]} />
          <meshStandardMaterial color="#070b11" roughness={0.4} metalness={0.7} />
        </mesh>
      )}

      {/* Grid for Floor 0 (Room A) */}
      {showFloor0 && (
        <Grid position={[2.5, 0, 1.925]} args={[BAY_W, BAY_D]} cellSize={1} cellThickness={0.4} cellColor="#14202d" sectionSize={2.5} sectionThickness={0.8} sectionColor="#243a4f" fadeDistance={30} fadeStrength={2.5} infiniteGrid={false} />
      )}

      {/* Grid for Floor 1 (Room B, stacked 3m above) */}
      {showFloor1 && (
        <Grid position={[2.5, 2.86, 1.925]} args={[BAY_W, BAY_D]} cellSize={1} cellThickness={0.4} cellColor="#14202d" sectionSize={2.5} sectionThickness={0.8} sectionColor="#243a4f" fadeDistance={30} fadeStrength={2.5} infiniteGrid={false} />
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

  // Segmented-control button style (active = filled cobalt, inactive = flat steel).
  const segBtn = (active) => ({
    flex: 1,
    background: active ? 'var(--accent-cobalt)' : 'var(--bg-card)',
    border: `1px solid ${active ? 'var(--accent-cobalt)' : 'var(--border)'}`,
    borderRadius: '4px',
    color: active ? 'var(--bg-deep)' : 'var(--text-muted)',
    padding: '6px 4px',
    fontSize: '11px',
    cursor: 'pointer',
    transition: 'all 0.15s',
    fontFamily: 'var(--font-mono)',
  })
  const sliderStyle = { width: '100%', background: 'var(--bg-card)', cursor: 'pointer', accentColor: 'var(--accent-cobalt)' }
  const labelStyle = { fontSize: '10px', color: 'var(--text-muted)', letterSpacing: '1px', textTransform: 'uppercase' }

  return (
    <div style={{
      position: 'absolute',
      bottom: 20,
      right: 20,
      zIndex: 1000,
      fontFamily: 'var(--font-mono)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'flex-end',
    }}>
      {/* Toggle Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: 'var(--glass-panel)',
          backdropFilter: 'blur(16px) saturate(120%)',
          WebkitBackdropFilter: 'blur(16px) saturate(120%)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--text-primary)',
          padding: '9px 14px',
          cursor: 'pointer',
          transition: 'all 0.15s',
          fontSize: '11px',
          boxShadow: 'var(--shadow-card)',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          marginBottom: isOpen ? '10px' : '0px',
        }}
      >
        <span style={{ opacity: 0.7 }}>⚙</span>
        <span>{isOpen ? 'CLOSE CONTROLS' : 'STREAM CONTROLS'}</span>
      </button>

      {/* Main Panel */}
      {isOpen && (
        <div style={{
          width: '288px',
          background: 'var(--glass-panel)',
          backdropFilter: 'blur(16px) saturate(120%)',
          WebkitBackdropFilter: 'blur(16px) saturate(120%)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: '18px',
          boxShadow: 'var(--shadow-panel), var(--inner-hi)',
          color: 'var(--text-primary)',
          display: 'flex',
          flexDirection: 'column',
          gap: '18px',
        }}>
          <div style={{ borderBottom: '1px solid var(--border)', paddingBottom: '8px', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', letterSpacing: '0.5px', fontFamily: 'var(--font-ui)', textTransform: 'uppercase' }}>
            RigVision Control Panel
          </div>

          {/* Floor Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Floor View Filter</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              {['all', 0, 1].map((f) => (
                <button key={f} onClick={() => setFloorFilter(f)}
                  style={{ ...segBtn(floorFilter === f), textTransform: 'uppercase' }}>
                  {f === 'all' ? 'All' : `F${f}`}
                </button>
              ))}
            </div>
          </div>

          {/* Click Interaction Target Toggle */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={labelStyle}>Click Interaction Target</span>
            <div style={{ display: 'flex', gap: '4px' }}>
              <button onClick={() => setZoneSelectMode(true)} style={segBtn(zoneSelectMode)}>
                Zones
              </button>
              <button onClick={() => setZoneSelectMode(false)} style={segBtn(!zoneSelectMode)}>
                Avatars
              </button>
            </div>
          </div>

          {/* Wall Opacity Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
              <span style={{ color: 'var(--text-muted)' }}>WALL OPACITY</span>
              <span style={{ color: 'var(--accent-cobalt)' }}>{(wallOpacity * 100).toFixed(0)}%</span>
            </div>
            <input type="range" min="0.1" max="1.0" step="0.05" value={wallOpacity}
              onChange={(e) => setWallOpacity(parseFloat(e.target.value))} style={sliderStyle} />
          </div>

          {/* FPS Limiter Slider */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
              <span style={{ color: 'var(--text-muted)' }}>SCENE RE-POLL / FPS LIMIT</span>
              <span style={{ color: 'var(--accent-cobalt)' }}>{fpsLimit} FPS</span>
            </div>
            <input type="range" min="1" max="30" step="1" value={fpsLimit}
              onChange={(e) => setFpsLimit(parseInt(e.target.value))} style={sliderStyle} />
          </div>

          {/* Toggles and Buttons */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '4px' }}>
            {/* Clear Tracking Cache Button */}
            <button
              onClick={handleClearCache}
              disabled={clearing}
              style={{
                width: '100%',
                background: 'var(--bg-card)',
                border: '1px solid var(--accent-red)',
                borderRadius: '4px',
                color: 'var(--accent-red)',
                padding: '8px',
                fontSize: '11px',
                cursor: clearing ? 'not-allowed' : 'pointer',
                letterSpacing: '0.5px',
                transition: 'all 0.15s',
                marginTop: '4px',
                opacity: clearing ? 0.6 : 1,
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

  // Orbit target Y: mid-height of whichever floor(s) are shown. Room A centres at
  // y≈1.5, Room B at y≈4.5, and the full stack at y≈3.0.
  const targetY = floorFilter === 'all' ? 3.0 : (floorFilter === 1 ? 4.5 : 1.5)

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Canvas
        shadows={{ type: THREE.PCFShadowMap }}
        camera={{ position: [9, 7, 10], fov: 45, near: 0.1, far: 500 }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#0b0e13' }}
        onClick={clearSelection}
      >
        <Environment preset="city" />
        <Lighting />
        <Floor showFloor0={showFloor0} showFloor1={showFloor1} />
        <RenderThrottler />

        <Suspense fallback={null}>
          {/* ROOM A — ground floor (zone_a), built in place spanning x∈[0,8], z∈[0,6] */}
          {showFloor0 && (
            <>
              <RigRoom baseY={0} zoneId="zone_a" isUpper={false} />
              <Equipment zoneId="zone_a" />
            </>
          )}

          {/* ROOM B — first floor (zone_b), stacked directly above Room A at y=3.0 */}
          {showFloor1 && (
            <>
              <RigRoom baseY={3.0} zoneId="zone_b" isUpper={true} />
              <Equipment zoneId="zone_b" />
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
              {/* Each zone now has 2 overlapping cameras (cameras[]); render an indicator for each. */}
              {(zone.cameras || []).map(camera => (
                <CameraIndicator key={camera.id} camera={camera} />
              ))}
              {(zone.sensors || []).map(sensor => (
                <SensorIndicator key={sensor.id} sensor={sensor} />
              ))}
            </group>
          )
        })}

        <OrbitControls
          target={[2.5, targetY, 1.925]}
          enableDamping dampingFactor={0.08}
          minDistance={3} maxDistance={70}
          minPolarAngle={0.1} maxPolarAngle={Math.PI / 2.05}
          makeDefault
        />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport axisColors={['#e06054', '#46b17f', '#5b8def']} labelColor="#e6e9ef" />
        </GizmoHelper>
      </Canvas>

      {/* Settings Overlay */}
      <SettingsPanel />
    </div>
  )
}