import { useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html, Billboard } from '@react-three/drei'
import * as THREE from 'three'
import { useRigStore } from '../stores/useRigStore.js'

const POSTURE_COLORS = {
  standing: '#00b4ff',
  sitting:  '#00ffd5',
  bending:  '#ffb300',
  lying:    '#ff3b3b',
  walking:  '#00b4ff',
  unknown:  '#5a8aaa',
}

function ppeAlert(ppe) {
  return ppe.hardhat === false || ppe.vest === false || ppe.goggles === false
}

function ppeUnknown(ppe) {
  return ppe.hardhat == null || ppe.vest == null || ppe.goggles == null
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
  const bodyColor  = hasAlert ? '#ff3b3b' : hasUnknown ? '#5a8aaa' : POSTURE_COLORS[person.posture] || '#00b4ff'

  // Smooth lerp toward latest position from store
  useFrame((state , delta) => {
    if (!meshRef.current) return
    targetPos.current.set(person.x, person.y || 0, person.z)

    meshRef.current.position.lerp(targetPos.current, 5 * delta)

    // Pulse alert ring
    if (hasAlert) {
      const t = Date.now() * 0.004
      const ring = meshRef.current.getObjectByName('alertRing')
      if (ring) ring.material.emissiveIntensity = 0.4 + 0.6 * Math.abs(Math.sin(t))
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
        <meshStandardMaterial color={bodyColor} roughness={0.4} metalness={0.3}
          emissive={bodyColor} emissiveIntensity={hovered || isSelected ? 0.5 : 0.15} />
      </mesh>

      {/* Head */}
      <mesh position={[0, 0.98, 0]} castShadow userData={{ isAvatar: true, personId: person.id }}>
        <sphereGeometry args={[0.17, 14, 14]} />
        <meshStandardMaterial color="#ffccaa" roughness={0.6} />
      </mesh>

      {/* Hard hat */}
      {ppe.hardhat === true && (
        <mesh position={[0, 1.14, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <cylinderGeometry args={[0.2, 0.18, 0.08, 12]} />
          <meshStandardMaterial color="#ffdd00" roughness={0.3} metalness={0.2} />
        </mesh>
      )}

      {/* Alert ring (pulsing) */}
      {hasAlert && (
        <mesh name="alertRing" rotation={[-Math.PI/2, 0, 0]} position={[0, 0.05, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <torusGeometry args={[0.32, 0.04, 8, 32]} />
          <meshStandardMaterial color="#ff3b3b" emissive="#ff0000" emissiveIntensity={1}
            transparent opacity={0.9} />
        </mesh>
      )}

      {/* Selection ring */}
      {isSelected && (
        <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.03, 0]} userData={{ isAvatar: true, personId: person.id }}>
          <torusGeometry args={[0.42, 0.03, 8, 32]} />
          <meshBasicMaterial color="#00ffd5" />
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
            background: hasAlert ? 'rgba(180,20,20,0.92)' : 'rgba(0,20,40,0.88)',
            border: `1px solid ${hasAlert ? '#ff3b3b' : '#00b4ff'}`,
            borderRadius: 6, padding: '4px 10px',
            fontFamily: "'Share Tech Mono', monospace",
            fontSize: 13, // Slightly larger base font
            color: '#fff', whiteSpace: 'nowrap',
            boxShadow: `0 0 12px ${hasAlert ? '#ff3b3b55' : '#00b4ff33'}`,
            display: 'flex',
            flexDirection: 'column',
            gap: '2px',
            alignItems: 'center'
          }}>
            <span>P{person.id} {hasAlert ? '⚠' : hasUnknown ? '?' : '●'} {person.zone.replace(/_/g,' ').toUpperCase()}</span>
          </div>
        </Html>
      )}


    </group>
  )
}
