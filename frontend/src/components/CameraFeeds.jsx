import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const POSTURE_COLORS = {
  standing: '#00b4ff',
  sitting:  '#00ffd5',
  bending:  '#ffb300',
  lying:    '#ff3b3b',
  walking:  '#00b4ff',
  unknown:  '#5a8aaa',
}

export default function CameraFeeds() {
  const selectedPerson = useRigStore(s => s.selectedPerson)
  const persons = useRigStore(s => s.persons)
  const [failedCams, setFailedCams] = useState({})
  const [retryCounts, setRetryCounts] = useState({})

  // Reset states when selectedPerson changes
  useEffect(() => {
    setFailedCams({})
    setRetryCounts({})
  }, [selectedPerson])

  // Handle retry interval for failed cameras
  useEffect(() => {
    const failedCamIds = Object.keys(failedCams).filter(id => failedCams[id])
    if (failedCamIds.length === 0) return

    const timer = setTimeout(() => {
      setFailedCams(prev => {
        const next = { ...prev }
        failedCamIds.forEach(id => {
          next[id] = false // Try loading again
        })
        return next
      })
      setRetryCounts(prev => {
        const next = { ...prev }
        failedCamIds.forEach(id => {
          next[id] = (next[id] || 0) + 1
        })
        return next
      })
    }, 4000) // Retry loading every 4 seconds

    return () => clearTimeout(timer)
  }, [failedCams])

  if (selectedPerson === null || selectedPerson === undefined) return null

  const person = persons.find(p => p.id === selectedPerson)
  const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname

  return (
    <div style={{
      position: 'absolute', top: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 12, zIndex: 10,
      background: 'rgba(5,15,28,0.95)', border: '1px solid rgba(0,180,255,0.4)', borderRadius: 8, padding: 12,
      boxShadow: '0 4px 20px rgba(0,0,0,0.8)',
      width: 344,
    }}>
      {/* Pulse keyframe injection */}
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }`}</style>

      {/* Person Detailed Info Card */}
      {person ? (() => {
        const hasAlert = !person.ppe.hardhat || !person.ppe.vest || !person.ppe.goggles
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
                <span style={{ color: '#e0f4ff', fontWeight: 'bold' }}>{person.cameras_visible} / 3</span>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 6, fontFamily: "'Share Tech Mono', monospace", fontSize: 11 }}>
              {[
                { label: '🪖 Hat', ok: person.ppe.hardhat },
                { label: '🦺 Vest', ok: person.ppe.vest },
                { label: '🥽 Goggles', ok: person.ppe.goggles },
              ].map(({ label, ok }) => (
                <div key={label} style={{
                  flex: 1,
                  textAlign: 'center',
                  padding: '4px 6px',
                  borderRadius: 4,
                  background: ok ? 'rgba(0, 230, 118, 0.08)' : 'rgba(255, 59, 59, 0.08)',
                  border: `1px solid ${ok ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 59, 59, 0.3)'}`,
                  color: ok ? '#00e676' : '#ff3b3b',
                  fontWeight: 500,
                }}>
                  {label} {ok ? '✓' : '✗'}
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
        {[0, 1, 2].map(camId => {
          const isFailed = failedCams[camId]
          const retry = retryCounts[camId] || 0
          return (
            <div key={camId} style={{ position: 'relative' }}>
              {!isFailed ? (
                <img 
                  src={`http://${host}:8000/api/video/mjpeg/${camId}?t=${retry}`} 
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
