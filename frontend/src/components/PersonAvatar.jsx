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
  return !ppe.hardhat || !ppe.vest || !ppe.goggles
}

export default function PersonAvatar({ person }) {
  const meshRef   = useRef()
  const targetPos = useRef(new THREE.Vector3(person.x, 0, person.z))
  const selectPerson  = useRigStore(s => s.selectPerson)
  const selectedPerson = useRigStore(s => s.selectedPerson)
  const [hovered, setHovered] = useState(false)

  const isSelected = selectedPerson === person.id
  const hasAlert   = ppeAlert(person.ppe)
  const bodyColor  = hasAlert ? '#ff3b3b' : POSTURE_COLORS[person.posture] || '#00b4ff'

  // Smooth lerp toward latest position from store
  useFrame((state , delta) => {
    if (!meshRef.current) return
    targetPos.current.set(person.x, 0, person.z)

    meshRef.current.position.lerp(targetPos.current, 5 * delta)

    // Pulse alert ring
    if (hasAlert) {
      const t = Date.now() * 0.004
      const ring = meshRef.current.getObjectByName('alertRing')
      if (ring) ring.material.emissiveIntensity = 0.4 + 0.6 * Math.abs(Math.sin(t))
    }
  })

  return (
    <group 
      ref={meshRef} 
      position={[person.x, 0, person.z]}
      // 👇 Crank these numbers up to match your new room size!
      scale={[6, 6, 6]} 
      onClick={(e) => { e.stopPropagation(); selectPerson(person.id) }}
      onPointerOver={() => setHovered(true)}
      onPointerOut={() => setHovered(false)}
    >
      {/* Shadow blob */}
      <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.01, 0]}>
        <circleGeometry args={[0.2, 16]} />
        <meshBasicMaterial color="#000" transparent opacity={0.35} />
      </mesh>

      {/* Body */}
      <mesh position={[0, 0.45, 0]} castShadow>
        <cylinderGeometry args={[0.14, 0.16, 0.7, 12]} />
        <meshStandardMaterial color={bodyColor} roughness={0.4} metalness={0.3}
          emissive={bodyColor} emissiveIntensity={hovered || isSelected ? 0.5 : 0.15} />
      </mesh>

      {/* Head */}
      <mesh position={[0, 0.98, 0]} castShadow>
        <sphereGeometry args={[0.17, 14, 14]} />
        <meshStandardMaterial color="#ffccaa" roughness={0.6} />
      </mesh>

      {/* Hard hat */}
      {person.ppe.hardhat && (
        <mesh position={[0, 1.14, 0]}>
          <cylinderGeometry args={[0.2, 0.18, 0.08, 12]} />
          <meshStandardMaterial color="#ffdd00" roughness={0.3} metalness={0.2} />
        </mesh>
      )}

      {/* Alert ring (pulsing) */}
      {hasAlert && (
        <mesh name="alertRing" rotation={[-Math.PI/2, 0, 0]} position={[0, 0.05, 0]}>
          <torusGeometry args={[0.32, 0.04, 8, 32]} />
          <meshStandardMaterial color="#ff3b3b" emissive="#ff0000" emissiveIntensity={1}
            transparent opacity={0.9} />
        </mesh>
      )}

      {/* Selection ring */}
      {isSelected && (
        <mesh rotation={[-Math.PI/2, 0, 0]} position={[0, 0.03, 0]}>
          <torusGeometry args={[0.42, 0.03, 8, 32]} />
          <meshBasicMaterial color="#00ffd5" />
        </mesh>
      )}

      {/* Floating label */}
     {/* Floating label (P1 / ZONE A) */}
      <Billboard follow lockX={false} lockY={false} lockZ={false}>
        <Html 
          position={[0, 1.8, 0]} // Pushed slightly higher above the head
          center 
          distanceFactor={25} // Increased from 8 so it stays readable when zoomed out
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
          }}>
            P{person.id} {hasAlert ? '⚠' : '●'} {person.zone.replace('_',' ').toUpperCase()}
          </div>
        </Html>
      </Billboard>

      {/* Hover / selected detail popup */}
      {(hovered || isSelected) && (
        <Html 
          position={[0.8, 1.2, 0]} // Shifted further right to clear the bigger avatar body
          distanceFactor={25} // Increased from 7
          style={{ pointerEvents: 'none', width: 180 }} // Made slightly wider to fit text cleanly
        >
          <div style={{
            background: 'rgba(5,15,28,0.95)',
            border: '1px solid rgba(0,180,255,0.4)',
            borderRadius: 8, padding: '10px 12px',
            fontFamily: "'Share Tech Mono', monospace",
            fontSize: 12, // Slightly larger base font
            color: '#e0f4ff', lineHeight: 1.7,
            boxShadow: '0 4px 20px rgba(0,0,0,0.8)',
          }}>
            <div style={{ color: '#00ffd5', marginBottom: 6, fontSize: 14, fontWeight: 'bold' }}>
              PERSON #{person.id}
            </div>
            <div>Zone: <span style={{ color:'#00b4ff' }}>{person.zone.replace('_',' ')}</span></div>
            <div>Posture: <span style={{ color: POSTURE_COLORS[person.posture] }}>{person.posture}</span></div>
            <div>Conf: <span style={{ color:'#00e676' }}>{(person.confidence*100).toFixed(0)}%</span></div>
            <div>Cams: {person.cameras_visible}</div>
            <div style={{ marginTop: 6, borderTop:'1px solid rgba(0,180,255,0.3)', paddingTop: 6 }}>
              🪖 {person.ppe.hardhat ? <span style={{color:'#00e676'}}>✓</span> : <span style={{color:'#ff3b3b'}}>✗</span>}
              {' '}🦺 {person.ppe.vest ? <span style={{color:'#00e676'}}>✓</span> : <span style={{color:'#ff3b3b'}}>✗</span>}
              {' '}🥽 {person.ppe.goggles ? <span style={{color:'#00e676'}}>✓</span> : <span style={{color:'#ff3b3b'}}>✗</span>}
            </div>
          </div>
        </Html>
      )}
  
    </group>
  )
}
