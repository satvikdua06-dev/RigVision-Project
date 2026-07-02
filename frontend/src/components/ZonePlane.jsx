import { useRef, useState } from 'react'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { useRigStore } from '../stores/useRigStore.js'

// Status tints use the Industrial Slate accent palette (hex, since Three.js materials
// need real colors). Kept subtle — a flat floor wash, no neon bloom.
const STATUS_COLORS = {
  normal:   { base: '#46b17f', opacity: 0.07 },
  warning:  { base: '#d9a64e', opacity: 0.13 },
  critical: { base: '#e06054', opacity: 0.18 },
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
      {/* Filled floor tint — flat, low emissive (no glow bloom) */}
      <mesh ref={planeRef} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[sx, sz]} />
        <meshStandardMaterial
          color={col.base} emissive={col.base}
          emissiveIntensity={isSelected || hovered ? 0.18 : 0.08}
          transparent opacity={col.opacity} depthWrite={false}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Zone label — flat type, no neon text-shadow */}
      {!showDiagnosticsModal && (
        <Html position={[0, 0.35, 0]} center distanceFactor={25}
          style={{ pointerEvents: 'none' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 7,
            background: 'rgba(18, 22, 29, 0.5)',
            backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 999, padding: '4px 12px',
            fontFamily: 'var(--font-ui)',
            fontSize: 13, fontWeight: 500, letterSpacing: 0.4,
            color: 'rgba(230,233,239,0.95)', textTransform: 'uppercase',
            whiteSpace: 'nowrap',
            opacity: hovered || isSelected ? 1 : 0.82,
            transition: 'opacity 0.2s',
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: col.base, flexShrink: 0 }} />
            {zone.label || zoneId.replace(/_/g, ' ').toUpperCase()}
          </div>
        </Html>
      )}

      {/* Hover / selected sensor popup — flat steel card, sharp border */}
      {isSelected && !showDiagnosticsModal && (
        <Html position={[0, 1.2, 0]} center distanceFactor={25}
          style={{ pointerEvents: 'none', width: 195 }}>
          <div style={{
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderLeft: `2px solid ${col.base}`,
            borderRadius: 6, padding: '10px 13px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11, color: 'var(--text-primary)', lineHeight: 1.85,
          }}>
            <div style={{
              fontFamily: 'var(--font-ui)', fontSize: 14, fontWeight: 600,
              letterSpacing: 0.5, color: col.base, marginBottom: 7,
              display: 'flex', justifyContent: 'space-between',
            }}>
              {zone.status.toUpperCase()}
              <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1 }}>
                {zone.person_count}p
              </span>
            </div>
            {[
              ['🌡', 'Temp', 'temperature', zone.temperature, '°C'],
              ['💨', 'H₂S',  'gas_h2s',     zone.gas_h2s,    'ppm'],
              ['📳', 'Vibr', 'vibration',   zone.vibration,  'g'],
              ['🔊', 'Noise','noise',       zone.noise,       'dB'],
              ['⚙',  'Pres', 'pressure',    zone.pressure,    'bar'],
            ].filter(([, , type]) => (zone.sensor_types || ['temperature','gas_h2s','vibration','noise']).includes(type))
             .map(([icon, lbl, , val, unit]) => (
              <div key={lbl} style={{ display:'flex', justifyContent:'space-between' }}>
                <span style={{ color:'var(--text-muted)' }}>{icon} {lbl}</span>
                <span>{val != null ? `${val} ${unit}` : '—'}</span>
              </div>
            ))}
          </div>
        </Html>
      )}
    </group>
  )
}
