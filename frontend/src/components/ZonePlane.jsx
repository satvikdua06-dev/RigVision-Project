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
      {(
        <Html position={[0, 0.15, 0]} center distanceFactor={12}
          style={{ pointerEvents: 'none' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            background: 'rgba(18, 22, 29, 0.5)',
            backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 999, padding: '2px 8px',
            fontFamily: 'var(--font-ui)',
            fontSize: 10, fontWeight: 500, letterSpacing: 0.4,
            color: 'rgba(230,233,239,0.95)', textTransform: 'uppercase',
            whiteSpace: 'nowrap',
            opacity: hovered || isSelected ? 1 : 0.82,
            transition: 'opacity 0.2s',
          }}>
            <span style={{ width: 5, height: 5, borderRadius: '50%', background: col.base, flexShrink: 0 }} />
            {zone.label || zoneId.replace(/_/g, ' ').toUpperCase()}
          </div>
        </Html>
      )}

      {/* Zone detail popup moved to DOM overlay in App.jsx */}
    </group>
  )
}
