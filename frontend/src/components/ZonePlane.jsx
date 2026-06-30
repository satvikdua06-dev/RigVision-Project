import { useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { useRigStore } from '../stores/useRigStore.js'

const STATUS_COLORS = {
  normal:   { base: '#00e676', emissive: '#00e676', opacity: 0.10 },
  warning:  { base: '#ffb300', emissive: '#ffb300', opacity: 0.16 },
  critical: { base: '#ff3b3b', emissive: '#ff0000', opacity: 0.22 },
}

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

export default function ZonePlane({ zoneId, zone, staticDef }) {
  const planeRef  = useRef()
  const borderRef = useRef()
  const [hovered, setHovered] = useState(false)
  
  const selectZone    = useRigStore(s => s.selectZone)
  const selectPerson  = useRigStore(s => s.selectPerson)
  const selectedZone  = useRigStore(s => s.selectedZone)
  const zoneSelectMode = useRigStore(s => s.zoneSelectMode)
  const showDiagnosticsModal = useRigStore(s => s.showDiagnosticsModal)
  const isSelected    = selectedZone === zoneId
  
  const col = STATUS_COLORS[zone.status] || STATUS_COLORS.normal
  
  // Use static physical layout from ZONES if provided, otherwise default fallback
  const layout = staticDef || { center: [0, 0, 0], size: [5, 3, 5] }
  const [px, , pz] = layout.center
  const [sx, , sz] = layout.size

  useFrame(() => {
    if (!planeRef.current) return
    if (zone.status === 'critical') {
      const t = Date.now() * 0.003
      planeRef.current.material.opacity = col.opacity + 0.1 * Math.abs(Math.sin(t))
      planeRef.current.material.emissiveIntensity = 0.3 + 0.3 * Math.abs(Math.sin(t))
    }
  })

  return (
    <group
      position={[px, layout.center[1] - layout.size[1] / 2 + 0.02, pz]}
      onClick={zoneSelectMode ? (e) => {
        e.stopPropagation()
        const clickedAvatarId = findAvatarInIntersections(e.intersections)
        if (clickedAvatarId !== null) {
          selectPerson(clickedAvatarId)
        } else {
          selectZone(zoneId)
        }
      } : undefined}
      onPointerOver={zoneSelectMode ? () => setHovered(true) : undefined}
      onPointerOut={zoneSelectMode ? () => setHovered(false) : undefined}
      raycast={zoneSelectMode ? undefined : null}
    >
      {/* Filled floor tint */}
      <mesh ref={planeRef} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[sx, sz]} />
        <meshStandardMaterial
          color={col.base} emissive={col.emissive}
          emissiveIntensity={isSelected || hovered ? 0.5 : 0.25}
          transparent opacity={col.opacity} depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>



      {/* Zone label */}
      {!showDiagnosticsModal && (
        <Html position={[0, 0.35, 0]} center distanceFactor={25}
          style={{ pointerEvents: 'none' }}>
          <div style={{
            fontFamily: "'Barlow Condensed', sans-serif",
            fontSize: 16, fontWeight: 700, letterSpacing: 3,
            color: col.base, textTransform: 'uppercase',
            textShadow: `0 0 14px ${col.base}`,
            whiteSpace: 'nowrap',
            opacity: hovered || isSelected ? 1 : 0.65,
            transition: 'opacity 0.2s',
          }}>
            {zoneId.replace(/_/g, ' ').toUpperCase()} {/* Fallback to ID since label isn't in Redis */}
          </div>
        </Html>
      )}

      {/* Hover / selected sensor popup */}
      {isSelected && !showDiagnosticsModal && (
        <Html position={[0, 1.2, 0]} center distanceFactor={25}
          style={{ pointerEvents: 'none', width: 195 }}>
          <div style={{
            background: 'rgba(4,12,22,0.97)',
            border: `1px solid ${col.base}55`,
            borderRadius: 10, padding: '10px 13px',
            fontFamily: "'Share Tech Mono', monospace",
            fontSize: 11, color: '#e0f4ff', lineHeight: 1.85,
            boxShadow: `0 0 24px ${col.base}18, 0 4px 20px rgba(0,0,0,0.7)`,
          }}>
            <div style={{
              fontFamily: "'Barlow Condensed'", fontSize: 15, fontWeight: 700,
              letterSpacing: 2, color: col.base, marginBottom: 7,
              display: 'flex', justifyContent: 'space-between',
            }}>
              {zone.status.toUpperCase()}
              <span style={{ fontSize: 10, color: '#5a8aaa', letterSpacing: 1 }}>
                {zone.person_count}p
              </span>
            </div>
            {[
              ['🌡', 'Temp', zone.temperature, '°C'],
              ['💨', 'H₂S',  zone.gas_h2s,    'ppm'],
              ['📳', 'Vibr', zone.vibration,  'g'],
              ['🔊', 'Noise',zone.noise,       'dB'],
              ['⚙',  'Pres', zone.pressure,    'bar'],
            ].map(([icon, lbl, val, unit]) => (
              <div key={lbl} style={{ display:'flex', justifyContent:'space-between' }}>
                <span style={{ color:'#5a8aaa' }}>{icon} {lbl}</span>
                <span>{val} {unit}</span>
              </div>
            ))}
          </div>
        </Html>
      )}
    </group>
  )
}