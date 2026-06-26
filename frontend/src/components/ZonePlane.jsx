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

// ------------------------------------------------------------------------
// 🗺️ STATIC LAYOUT CONFIGURATION
// Since the room doesn't move, we store the X,Y,Z coordinates here 
// rather than expecting the WebSocket to send them 10 times a second.
// (You may need to tweak these numbers to perfectly fit your new larger room!)
// ------------------------------------------------------------------------
const ZONE_LAYOUTS = {
  zone_a:   { position: [-22, 0, 0], size: [25, 0, 20] }, // Wraps Room A on the left
  corridor: { position: [0, 0, 0],   size: [20, 0, 8] },  // Wraps the new Bridge in the middle
  zone_b:   { position: [22, 0, 0],  size: [25, 0, 20] }, // Wraps Room B on the right
}

export default function ZonePlane({ zoneId, zone }) {
  const planeRef  = useRef()
  const borderRef = useRef()
  const [hovered, setHovered] = useState(false)
  
  const selectZone    = useRigStore(s => s.selectZone)
  const selectedZone  = useRigStore(s => s.selectedZone)
  const isSelected    = selectedZone === zoneId
  
  const col = STATUS_COLORS[zone.status] || STATUS_COLORS.normal
  
  // Safely grab the static physical layout for this specific zone ID
  // If the ID isn't found, default to a box in the middle of the room
  const layout = ZONE_LAYOUTS[zoneId] || { position: [0,0,0], size: [5,0,5] }
  const [px, , pz] = layout.position
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
      position={[px, 0.02, pz]}
      onClick={(e) => { e.stopPropagation(); selectZone(zoneId) }}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
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

      {/* Corner posts for zone boundary */}
      {[[-sx/2,-sz/2],[sx/2,-sz/2],[sx/2,sz/2],[-sx/2,sz/2]].map(([cx,cz], i) => (
        <mesh key={i} position={[cx, 0.15, cz]}>
          <cylinderGeometry args={[0.08, 0.08, 0.5, 6]} />
          <meshStandardMaterial color={col.base} emissive={col.base}
            emissiveIntensity={0.6} />
        </mesh>
      ))}

      {/* Zone label */}
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
          {zoneId.replace('_', ' ')} {/* Fallback to ID since label isn't in Redis */}
        </div>
      </Html>

      {/* Hover / selected sensor popup */}
      {(hovered || isSelected) && (
        <Html position={[sx * 0.45, 0.7, 0]} distanceFactor={25}
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