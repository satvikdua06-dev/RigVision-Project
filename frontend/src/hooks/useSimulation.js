import { useEffect, useRef } from 'react'
import { useRigStore } from '../stores/useRigStore.js'
import { MOVEMENT_PATHS } from '../data/dummyData.js'

// Simulates WebSocket push from Redis at ~1Hz
// In Phase 2: replace with actual WebSocket connection
export function useSimulation() {
  const frameRefs = useRef({})   // path frame index per person
  const { updatePersonPosition, setZones, setViolations } = useRigStore.getState()

  useEffect(() => {
    // Initialize frame indices
    Object.keys(MOVEMENT_PATHS).forEach(id => { frameRefs.current[id] = 0 })

    const interval = setInterval(() => {
      // Advance each person along their path
      Object.entries(MOVEMENT_PATHS).forEach(([id, path]) => {
        const fi = frameRefs.current[id]
        const { x, z } = path[fi]
        updatePersonPosition(Number(id), x, z)
        frameRefs.current[id] = (fi + 1) % path.length
      })

      // Occasionally update sensor readings (simulate drift)
      setZones(prev => {
        const next = { ...prev }
        Object.keys(next).forEach(zid => {
          next[zid] = {
            ...next[zid],
            temperature: +(next[zid].temperature + (Math.random() - 0.5) * 0.4).toFixed(1),
            vibration:   +(next[zid].vibration   + (Math.random() - 0.5) * 0.1).toFixed(2),
            gas_h2s:     +(Math.max(0, next[zid].gas_h2s + (Math.random() - 0.48) * 0.3)).toFixed(1),
            noise:       +(next[zid].noise        + (Math.random() - 0.5) * 1.5).toFixed(0),
            updated_at:  Date.now(),
          }
        })
        return next
      })
    }, 1000)

    return () => clearInterval(interval)
  }, [])
}
