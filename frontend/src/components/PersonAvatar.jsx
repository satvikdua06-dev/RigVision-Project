import { useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html, Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { useRigStore } from '../stores/useRigStore.js'

// Industrial Slate palette (hex — these drive Three.js material colors).
const POSTURE_COLORS = {
  standing: '#5b8def',
  sitting:  '#5b8def',
  bending:  '#d9a64e',
  lying:    '#e06054',
  walking:  '#5b8def',
  unknown:  '#8b93a3',
}

function ppeAlert(ppe) {
  return ppe.backpack === 'missing' || ppe.hat === 'missing'
}

function ppeUnknown(ppe) {
  return ppe.backpack == null || ppe.backpack === 'unknown' || ppe.hat == null || ppe.hat === 'unknown'
}

export default function PersonAvatar({ person }) {
  const meshRef   = useRef()
  const targetPos = useRef(new THREE.Vector3(person.x, person.y || 0, person.z))
  const selectPerson  = useRigStore(s => s.selectPerson)
  const selectedPerson = useRigStore(s => s.selectedPerson)
  const [hovered, setHovered] = useState(false)

  const isSelected = selectedPerson === person.id
  const ppe = person.ppe || {}
  const hasAlert   = ppeAlert(ppe)
  const hasUnknown = ppeUnknown(ppe)
  const bodyColor  = hasAlert ? '#e06054' : hasUnknown ? '#8b93a3' : POSTURE_COLORS[person.posture] || '#5b8def'

  // Smooth lerp toward latest position from store
  useFrame((state , delta) => {
    if (!meshRef.current) return
    targetPos.current.set(person.x, person.y || 0, person.z)

    meshRef.current.position.lerp(targetPos.current, 5 * delta)

    // Gentle alert-ring breath (subtle status cue, not a neon bloom)
    if (hasAlert) {
      const t = Date.now() * 0.003
      const ring = meshRef.current.getObjectByName('alertRing')
      if (ring) ring.material.emissiveIntensity = 0.2 + 0.25 * Math.abs(Math.sin(t))
    }
  })

  const showDiagnosticsModal = useRigStore(s => s.showDiagnosticsModal)

  return (
    <group 
      ref={meshRef} 
      position={[person.x, person.y || 0, person.z]}
      scale={[1, 1, 1]} 
      onClick={(e) => { e.stopPropagation(); selectPerson(person.id) }}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
      userData={{ isAvatar: true, personId: person.id }}
    >
      {/* Shadow blob */}
      <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.01, 0]}>
        <circleGeometry args={[0.2, 16]} />
        <meshBasicMaterial color="#000" transparent opacity={0.35} />
      </mesh>

      {/* Body */}
      <mesh position={[0, 0.45, 0]} castShadow userData={{ isAvatar: true, personId: person.id }}>
        <cylinderGeometry args={[0.14, 0.16, 0.7, 12]} />
        <meshStandardMaterial color={bodyColor} roughness={0.5} metalness={0.2}
          emissive={bodyColor} emissiveIntensity={hovered || isSelected ? 0.25 : 0.06} />
      </mesh>

      {/* Head */}
      <mesh position={[0, 0.98, 0]} castShadow userData={{ isAvatar: true, personId: person.id }}>
        <sphereGeometry args={[0.17, 14, 14]} />
        <meshStandardMaterial color="#ffccaa" roughness={0.6} />
      </mesh>

      {/* Hard hat — shown when head protection is detected */}
      {ppe.hat === 'detected' && (
        <mesh position={[0, 1.14, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <cylinderGeometry args={[0.2, 0.18, 0.08, 12]} />
          <meshStandardMaterial color="#ffdd00" roughness={0.3} metalness={0.2} />
        </mesh>
      )}

      {/* Alert ring (pulsing) */}
      {hasAlert && (
        <mesh name="alertRing" rotation={[-Math.PI/2, 0, 0]} position={[0, 0.05, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <torusGeometry args={[0.32, 0.04, 8, 32]} />
          <meshStandardMaterial color="#e06054" emissive="#e06054" emissiveIntensity={0.3}
            transparent opacity={0.9} />
        </mesh>
      )}

      {/* Selection ring */}
      {isSelected && (
        <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.03, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <torusGeometry args={[0.42, 0.03, 8, 32]} />
          <meshBasicMaterial color="#5b8def" />
        </mesh>
      )}

      {/* Floating label */}
      {!showDiagnosticsModal && (
        <Html 
          position={[0, 1.8, 0]} // Pushed slightly higher above the head
          center 
          distanceFactor={22} // stays readable and not too small
          style={{ pointerEvents: 'none' }}
        >
          <div style={{
            background: 'rgba(18, 22, 29, 0.55)',
            backdropFilter: 'blur(6px)',
            WebkitBackdropFilter: 'blur(6px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 999, padding: '3px 10px',
            fontFamily: 'var(--font-mono)',
            fontSize: 12, fontWeight: 500,
            color: 'rgba(230,233,239,0.92)', whiteSpace: 'nowrap',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
              background: hasAlert ? '#e06054' : hasUnknown ? '#8b93a3' : '#5b8def',
            }} />
            <span>P{person.id} · {person.zone.replace(/_/g,' ').toUpperCase()}</span>
          </div>
        </Html>
      )}


    </group>
  )
}
