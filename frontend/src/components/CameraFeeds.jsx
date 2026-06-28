import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

export default function CameraFeeds() {
  const selectedPerson = useRigStore(s => s.selectedPerson)
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

  const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname

  return (
    <div style={{
      position: 'absolute', top: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 12, zIndex: 10,
      background: 'rgba(5,15,28,0.95)', border: '1px solid rgba(0,180,255,0.4)', borderRadius: 8, padding: 12,
      boxShadow: '0 4px 20px rgba(0,0,0,0.8)',
    }}>
      <div style={{ fontFamily: "'Barlow Condensed'", fontSize: 14, color: '#00b4ff', fontWeight: 600, letterSpacing: 1 }}>
        LIVE CAMERA FEEDS · PERSON #{selectedPerson}
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
