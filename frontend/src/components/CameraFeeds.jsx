import { useState, useEffect, useMemo } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const POSTURE_COLORS = {
  standing: 'var(--accent-cobalt)',
  sitting:  'var(--accent-cobalt)',
  bending:  'var(--accent-amber)',
  lying:    'var(--accent-red)',
  walking:  'var(--accent-cobalt)',
  unknown:  'var(--text-muted)',
}

function ppeStatus(val) {
  if (val === true) return { label: '✓', color: 'var(--accent-green)' }
  if (val === false) return { label: '✗', color: 'var(--accent-red)' }
  return { label: '?', color: 'var(--text-muted)' }
}

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

export default function CameraFeeds() {
  const selectedPerson = useRigStore(s => s.selectedPerson)
  const persons = useRigStore(s => s.persons)
  const [failedCams, setFailedCams] = useState({})
  const [retryCounts, setRetryCounts] = useState({})

  useEffect(() => {
    setFailedCams({})
    setRetryCounts({})
  }, [selectedPerson])

  useEffect(() => {
    const failedCamIds = Object.keys(failedCams).filter(id => failedCams[id])
    if (failedCamIds.length === 0) return

    const timer = setTimeout(() => {
      setFailedCams(prev => {
        const next = { ...prev }
        failedCamIds.forEach(id => { next[id] = false })
        return next
      })
      setRetryCounts(prev => {
        const next = { ...prev }
        failedCamIds.forEach(id => { next[id] = (next[id] || 0) + 1 })
        return next
      })
    }, 4000)

    return () => clearTimeout(timer)
  }, [failedCams])

  const cameraIds = useMemo(() => {
    const ids = new Set()
    persons.forEach(p => {
      if (p.camera_ids) p.camera_ids.forEach(id => ids.add(id))
    })
    return ids.size > 0 ? [...ids].sort((a, b) => a - b) : [0, 1, 2]
  }, [persons])

  if (selectedPerson === null || selectedPerson === undefined) return null

  const person = persons.find(p => p.id === selectedPerson)

  const ppe = person?.ppe || {}
  const hatStatus = ppeStatus(ppe.hardhat)
  const vestStatus = ppeStatus(ppe.vest)
  const gogglesStatus = ppeStatus(ppe.goggles)

  const hasAlert = ppe.hardhat === false || ppe.vest === false || ppe.goggles === false
  const hasUnknown = ppe.hardhat == null || ppe.vest == null || ppe.goggles == null

  // Small flat status pill helper (sharp border, no glow).
  const pill = (text, color) => (
    <span style={{
      background: 'var(--bg-card)', border: `1px solid ${color}`, color,
      fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 8px',
      borderRadius: 4, fontWeight: 500, letterSpacing: 0.5,
    }}>{text}</span>
  )

  return (
    <div style={{
      position: 'absolute', top: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 14, zIndex: 10,
      background: 'var(--glass-panel)',
      backdropFilter: 'blur(16px) saturate(120%)', WebkitBackdropFilter: 'blur(16px) saturate(120%)',
      border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 14,
      boxShadow: 'var(--shadow-panel), var(--inner-hi)',
      width: 348,
    }}>
      {/* Person Detailed Info Card */}
      {person ? (() => {
        return (
          <div style={{
            borderBottom: '1px solid var(--border)',
            paddingBottom: 12,
            marginBottom: 2,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontFamily: 'var(--font-ui)', fontSize: 16, fontWeight: 600, letterSpacing: 0.3, color: 'var(--text-primary)' }}>
                PERSON #{person.id}
              </span>
              {hasAlert ? pill('PPE VIOLATION', 'var(--accent-red)')
                : hasUnknown ? pill('UNMONITORED', 'var(--text-muted)')
                : pill('COMPLIANT', 'var(--accent-green)')}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)', marginBottom: 12 }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Zone:</span>{' '}
                <span style={{ color: 'var(--accent-cobalt)', fontWeight: 600 }}>{person.zone.replace(/_/g, ' ').toUpperCase()}</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Posture:</span>{' '}
                <span style={{ color: POSTURE_COLORS[person.posture] || 'var(--text-primary)', fontWeight: 600 }}>
                  {person.posture.charAt(0).toUpperCase() + person.posture.slice(1)}
                </span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Conf:</span>{' '}
                <span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>{(person.confidence * 100).toFixed(0)}%</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Cams:</span>{' '}
                <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{person.cameras_visible} / {cameraIds.length}</span>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              {[
                { label: '🪖 Hat', status: hatStatus },
                { label: '🦺 Vest', status: vestStatus },
                { label: '🥽 Goggles', status: gogglesStatus },
              ].map(({ label, status }) => (
                <div key={label} style={{
                  flex: 1,
                  textAlign: 'center',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: 'var(--bg-card)',
                  border: `1px solid ${status.color}`,
                  color: status.color,
                  fontWeight: 500,
                }}>
                  {label} {status.label}
                </div>
              ))}
            </div>
          </div>
        )
      })() : (
        <div style={{
          borderBottom: '1px solid var(--border)',
          paddingBottom: 12,
          marginBottom: 2,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontFamily: 'var(--font-ui)', fontSize: 16, fontWeight: 600, letterSpacing: 0.3, color: 'var(--text-muted)' }}>
              PERSON #{selectedPerson}
            </span>
            {pill('TRACKING LOST', 'var(--accent-amber)')}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            Personnel #{selectedPerson} is not currently detected by any active camera. Live feeds are shown below.
          </div>
        </div>
      )}

      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', fontWeight: 500, letterSpacing: 1.5, textTransform: 'uppercase' }}>
        Live Feed Stream
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {cameraIds.map(camId => {
          const isFailed = failedCams[camId]
          const retry = retryCounts[camId] || 0
          return (
            <div key={camId} style={{ position: 'relative' }}>
              {!isFailed ? (
                <img
                  src={`${API_BASE}/video/mjpeg/${camId}?t=${retry}`}
                  alt={`Camera ${camId}`}
                  style={{ width: 320, height: 180, borderRadius: 6, border: '1px solid var(--border)', objectFit: 'cover', color: 'transparent' }}
                  onError={() => {
                    setFailedCams(prev => ({ ...prev, [camId]: true }))
                  }}
                />
              ) : (
                <div style={{
                  display: 'flex', width: 320, height: 180, borderRadius: 6, border: '1px solid var(--border)',
                  background: 'var(--bg-deep)', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12,
                  justifyContent: 'center', alignItems: 'center'
                }}>
                  CAM {camId} OFFLINE
                </div>
              )}
              <div style={{
                position: 'absolute', top: 6, left: 6, background: 'var(--bg-deep)', color: 'var(--accent-cobalt)',
                fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 6px', borderRadius: 4,
                border: '1px solid var(--border)'
              }}>CAM {camId}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
