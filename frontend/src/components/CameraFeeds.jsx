import { useState, useEffect, useMemo } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const POSTURE_COLORS = {
  standing: '#00b4ff',
  sitting:  '#00ffd5',
  bending:  '#ffb300',
  lying:    '#ff3b3b',
  walking:  '#00b4ff',
  unknown:  '#5a8aaa',
}

function ppeStatus(val) {
  if (val === true) return { label: '✓', color: '#00e676', bg: 'rgba(0, 230, 118, 0.08)', border: 'rgba(0, 230, 118, 0.3)' }
  if (val === false) return { label: '✗', color: '#ff3b3b', bg: 'rgba(255, 59, 59, 0.08)', border: 'rgba(255, 59, 59, 0.3)' }
  return { label: '?', color: '#5a8aaa', bg: 'rgba(90, 138, 170, 0.08)', border: 'rgba(90, 138, 170, 0.3)' }
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

  return (
    <div style={{
      position: 'absolute', top: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 12, zIndex: 10,
      background: 'rgba(5,15,28,0.95)', border: '1px solid rgba(0,180,255,0.4)', borderRadius: 8, padding: 12,
      boxShadow: '0 4px 20px rgba(0,0,0,0.8)',
      width: 344,
    }}>
      {/* Person Detailed Info Card */}
      {person ? (() => {
        return (
          <div style={{
            borderBottom: '1px solid rgba(0,180,255,0.25)',
            paddingBottom: 12,
            marginBottom: 2,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontFamily: "'Barlow Condensed'", fontSize: 18, fontWeight: 700, letterSpacing: 1.5, color: '#00ffd5' }}>
                PERSON #{person.id}
              </span>
              {hasAlert ? (
                <span style={{
                  background: 'rgba(255, 59, 59, 0.15)',
                  border: '1px solid #ff3b3b',
                  color: '#ff3b3b',
                  fontFamily: "'Share Tech Mono', monospace",
                  fontSize: 10,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 600,
                  letterSpacing: 1,
                  animation: 'pulse 1.5s infinite'
                }}>PPE VIOLATION</span>
              ) : hasUnknown ? (
                <span style={{
                  background: 'rgba(90, 138, 170, 0.15)',
                  border: '1px solid #5a8aaa',
                  color: '#5a8aaa',
                  fontFamily: "'Share Tech Mono', monospace",
                  fontSize: 10,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 600,
                  letterSpacing: 1
                }}>UNMONITORED</span>
              ) : (
                <span style={{
                  background: 'rgba(0, 230, 118, 0.15)',
                  border: '1px solid #00e676',
                  color: '#00e676',
                  fontFamily: "'Share Tech Mono', monospace",
                  fontSize: 10,
                  padding: '2px 8px',
                  borderRadius: 4,
                  fontWeight: 600,
                  letterSpacing: 1
                }}>COMPLIANT</span>
              )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px', fontFamily: "'Share Tech Mono', monospace", fontSize: 12, color: '#e0f4ff', marginBottom: 12 }}>
              <div>
                <span style={{ color: '#5a8aaa' }}>Zone:</span>{' '}
                <span style={{ color: '#00b4ff', fontWeight: 'bold' }}>{person.zone.replace(/_/g, ' ').toUpperCase()}</span>
              </div>
              <div>
                <span style={{ color: '#5a8aaa' }}>Posture:</span>{' '}
                <span style={{ color: POSTURE_COLORS[person.posture] || '#00ffd5', fontWeight: 'bold' }}>
                  {person.posture.charAt(0).toUpperCase() + person.posture.slice(1)}
                </span>
              </div>
              <div>
                <span style={{ color: '#5a8aaa' }}>Conf:</span>{' '}
                <span style={{ color: '#00e676', fontWeight: 'bold' }}>{(person.confidence * 100).toFixed(0)}%</span>
              </div>
              <div>
                <span style={{ color: '#5a8aaa' }}>Cams:</span>{' '}
                <span style={{ color: '#e0f4ff', fontWeight: 'bold' }}>{person.cameras_visible} / {cameraIds.length}</span>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, fontFamily: "'Share Tech Mono', monospace", fontSize: 11 }}>
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
                  background: status.bg,
                  border: `1px solid ${status.border}`,
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
          borderBottom: '1px solid rgba(0,180,255,0.25)',
          paddingBottom: 12,
          marginBottom: 2,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontFamily: "'Barlow Condensed'", fontSize: 18, fontWeight: 700, letterSpacing: 1.5, color: '#5a8aaa' }}>
              PERSON #{selectedPerson}
            </span>
            <span style={{
              background: 'rgba(255, 179, 0, 0.15)',
              border: '1px solid #ffb300',
              color: '#ffb300',
              fontFamily: "'Share Tech Mono', monospace",
              fontSize: 10,
              padding: '2px 8px',
              borderRadius: 4,
              fontWeight: 600,
              letterSpacing: 1
            }}>TRACKING LOST</span>
          </div>
          <div style={{ fontFamily: "'Share Tech Mono', monospace", fontSize: 12, color: '#5a8aaa', lineHeight: 1.5 }}>
            Personnel #{selectedPerson} is not currently detected by any active camera. Live feeds are shown below.
          </div>
        </div>
      )}

      <div style={{ fontFamily: "'Barlow Condensed'", fontSize: 12, color: '#5a8aaa', fontWeight: 600, letterSpacing: 1 }}>
        LIVE FEED STREAM
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
                  style={{ width: 320, height: 180, borderRadius: 6, border: '1px solid #2a4a5a', objectFit: 'cover', color: 'transparent' }}
                  onError={() => {
                    setFailedCams(prev => ({ ...prev, [camId]: true }))
                  }}
                />
              ) : (
                <div style={{
                  display: 'flex', width: 320, height: 180, borderRadius: 6, border: '1px solid rgba(255,255,255,0.1)',
                  background: 'rgba(0,0,0,0.5)', color: '#5a8aaa', fontFamily: "'Share Tech Mono'", fontSize: 12,
                  justifyContent: 'center', alignItems: 'center'
                }}>
                  CAM {camId} OFFLINE
                </div>
              )}
              <div style={{
                position: 'absolute', top: 6, left: 6, background: 'rgba(0,0,0,0.7)', color: '#00b4ff',
                fontFamily: "'Share Tech Mono'", fontSize: 10, padding: '2px 6px', borderRadius: 4,
                border: '1px solid rgba(0,180,255,0.3)'
              }}>CAM {camId}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
