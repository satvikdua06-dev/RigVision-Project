import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const SEVERITY_COLOR = {
  warning: '#d9a64e',
  critical: '#e06054',
}

// Rig zone ids → Neo4j KG Zone ids. Diagnostics are tagged with the KG id, so an
// alert overlay matches a diagnostic either by the rig id or its mapped KG id.
const ZONE_TO_KG = {
  "zone_a": "room_1", "zone_b": "room_2",
}

export default function NotificationAlert() {
  try {
    const zones = useRigStore(s => s.zones) || {}
    const diagnostics = useRigStore(s => s.diagnostics) || []
    const setShowModal = useRigStore(s => s.setShowDiagnosticsModal)

    const [dismissedSignature, setDismissedSignature] = useState('')
    const [anomalyState, setAnomalyState] = useState({
      signature: '',
      startedAt: 0,
      isReady: false,
    })

    // Find if there is any active sensor anomaly in the zones
    const activeZoneId = Object.keys(zones).find(k => {
      const zone = zones[k]
      if (!zone || (zone.status !== 'warning' && zone.status !== 'critical')) return false

      // Check if it has actual sensor breaches
      if (zone.sensor_meta) {
        for (const [stype, meta] of Object.entries(zone.sensor_meta)) {
          const val = zone[stype]
          if (val !== undefined && val !== null) {
            if ((meta.critical !== null && val >= meta.critical) ||
                (meta.warning !== null && val >= meta.warning)) {
              return true
            }
          }
        }
      }
      return false
    })

    const activeZone = activeZoneId ? zones[activeZoneId] : null
    const breachedSensors = []
    if (activeZone && activeZone.sensor_meta) {
      for (const [stype, meta] of Object.entries(activeZone.sensor_meta)) {
        const val = activeZone[stype]
        if (val !== undefined && val !== null) {
          if ((meta.critical !== null && val >= meta.critical) ||
              (meta.warning !== null && val >= meta.warning)) {
            breachedSensors.push(stype)
          }
        }
      }
    }

    const breachSignature = activeZoneId
      ? `${activeZoneId}:${activeZone.status}:${breachedSensors.slice().sort().join(',')}`
      : ''

    // Sync anomalyState with active anomaly changes
    useEffect(() => {
      if (!breachSignature) {
        if (anomalyState.signature !== '') {
          setAnomalyState({ signature: '', startedAt: 0, isReady: false })
        }
        return
      }

      if (anomalyState.signature !== breachSignature) {
        // Find latest diagnostic report for this zone
        const latestDiag = diagnostics.find(
          d => d && (d.zone_id === activeZoneId || (ZONE_TO_KG[activeZoneId] && d.zone_id === ZONE_TO_KG[activeZoneId]))
        )
        // Check if a report is already ready (covers all currently breached sensors)
        const reportSensors = latestDiag?.triggered_sensors || []
        const coversBreached = breachedSensors.every(s => reportSensors.includes(s))
        const initiallyReady = latestDiag && coversBreached

        setAnomalyState({
          signature: breachSignature,
          startedAt: Date.now(),
          isReady: !!initiallyReady,
        })
      } else if (!anomalyState.isReady) {
        // Look for the report to arrive
        const latestDiag = diagnostics.find(
          d => d && (d.zone_id === activeZoneId || (ZONE_TO_KG[activeZoneId] && d.zone_id === ZONE_TO_KG[activeZoneId]))
        )
        if (latestDiag) {
          const reportSensors = latestDiag.triggered_sensors || []
          const coversBreached = breachedSensors.every(s => reportSensors.includes(s))
          const age = Date.now() - anomalyState.startedAt
          const diagTime = latestDiag.timestamp ? new Date(latestDiag.timestamp).getTime() : 0

          // Mark ready if the report covers the breach and is recent, or fallback to ready after a timeout to prevent being stuck
          if (coversBreached && (diagTime >= anomalyState.startedAt - 8000 || age > 15000)) {
            setAnomalyState(prev => ({ ...prev, isReady: true }))
          }
        } else {
          // Timeout fallback
          const age = Date.now() - anomalyState.startedAt
          if (age > 15000) {
            setAnomalyState(prev => ({ ...prev, isReady: true }))
          }
        }
      }
    }, [breachSignature, activeZoneId, breachedSensors, diagnostics, anomalyState])

    if (!activeZoneId || !zones[activeZoneId]) {
      return null
    }

    const zone = zones[activeZoneId]
    const zoneStatus = zone.status // 'warning' or 'critical'

    // If the user has dismissed this specific telemetry alert instance, suppress the overlay
    if (dismissedSignature === breachSignature) {
      return null
    }

    const latestDiag = diagnostics.find(
      d => d && (d.zone_id === activeZoneId || (ZONE_TO_KG[activeZoneId] && d.zone_id === ZONE_TO_KG[activeZoneId]))
    )

    // Only display the cached report if it is relevant to the currently breached sensors
    const reportSensors = latestDiag?.triggered_sensors || []
    const coversBreached = breachedSensors.every(s => reportSensors.includes(s))
    const displayDiag = (latestDiag && coversBreached) ? latestDiag : null

    const isAnalyzing = !anomalyState.isReady
    const color = SEVERITY_COLOR[zoneStatus] || '#e06054'

    // Extract concise steps from the recommended action if available
    let safetyStep = ""
    let repairStep = ""

    if (displayDiag && displayDiag.recommended_action) {
      const steps = displayDiag.recommended_action.split(/\d+\)\s+/)
      const filteredSteps = steps.map(s => s.trim()).filter(Boolean)
      if (filteredSteps.length > 0) {
        safetyStep = filteredSteps[0]
      }
      if (filteredSteps.length > 1) {
        repairStep = filteredSteps[1]
      }
    }

    const handleAlertClick = () => {
      setShowModal(true)
    }

    const handleClose = (e) => {
      e.stopPropagation()
      setDismissedSignature(breachSignature)
    }

    return (
      <div
        onClick={handleAlertClick}
        style={{
          position: 'fixed',
          top: 24,
          right: 24,
          width: 380,
          zIndex: 99999,
          background: 'var(--glass-panel)',
          backdropFilter: 'blur(16px) saturate(120%)',
          WebkitBackdropFilter: 'blur(16px) saturate(120%)',
          border: '1px solid var(--border)',
          borderLeft: `3px solid ${color}`,
          borderRadius: 'var(--radius)',
          padding: '16px 20px',
          boxSizing: 'border-box',
          boxShadow: 'var(--shadow-panel), var(--inner-hi)',
          cursor: 'pointer',
          fontFamily: 'var(--font-ui)',
          color: 'var(--text-primary)',
          transition: 'border-color 0.2s ease',
        }}
      >
        {/* Subtle opacity pulse for the loading state (no neon glow) */}
        <style>{`
          @keyframes pulseFade {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.45; }
          }
          .pulse-alert { animation: pulseFade 1.5s infinite ease-in-out; }
          .alert-btn:hover {
            background: var(--bg-card) !important;
            border-color: ${color} !important;
            color: var(--text-primary) !important;
          }
        `}</style>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            color: color,
            letterSpacing: 1,
            display: 'flex',
            alignItems: 'center',
            gap: 6
          }}>
            <span className={isAnalyzing ? "pulse-alert" : ""} style={{ fontSize: 14 }}>🚨</span>
            <span>{zoneStatus.toUpperCase()} ANOMALY: {(zone.name || activeZoneId).toUpperCase()}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {isAnalyzing && (
              <span className="pulse-alert" style={{
                fontSize: 9,
                fontFamily: 'var(--font-mono)',
                color: 'var(--accent-amber)',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                padding: '1px 6px',
                borderRadius: 4,
                letterSpacing: 1
              }}>
                ANALYZING...
              </span>
            )}
            <button
              onClick={handleClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                fontSize: 16,
                padding: 0,
                lineHeight: 1
              }}
            >
              ×
            </button>
          </div>
        </div>

        {/* Content */}
        {!displayDiag ? (
          <div className="pulse-alert" style={{ margin: '10px 0' }}>
            <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
              Analyzing Telemetry...
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.4 }}>
              Breach detected on sensors. AI diagnostic agent is generating root-cause report...
            </div>
          </div>
        ) : (
          <div>
            {/* Issue title */}
            <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8, lineHeight: 1.2 }}>
              {displayDiag.primary_diagnosis || 'Unclassified failure mode'}
            </div>

            {/* Quick steps split */}
            <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 12 }}>
              {safetyStep && (
                <div style={{ marginBottom: 6 }}>
                  <strong style={{ color: color, fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', display: 'block' }}>
                    Immediate Action:
                  </strong>
                  {safetyStep.replace(/^(Immediate Safety & Isolation Protocol:|Immediate Safety:)/i, '').trim()}
                </div>
              )}
              {repairStep && (
                <div>
                  <strong style={{ color: 'var(--accent-cobalt)', fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', display: 'block' }}>
                    Repair Procedure:
                  </strong>
                  {repairStep.replace(/^(Core Repair Procedures:|Core Repair:)/i, '').trim()}
                </div>
              )}
            </div>

            {/* Button to show full diagnostics modal */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
              <div
                className="alert-btn"
                style={{
                  fontSize: 11,
                  fontFamily: 'var(--font-mono)',
                  color: color,
                  border: `1px solid ${color}`,
                  borderRadius: 4,
                  padding: '4px 10px',
                  background: 'var(--bg-card)',
                  transition: 'all 0.2s',
                  letterSpacing: 0.5
                }}
              >
                VIEW FULL REPORT →
              </div>
            </div>
          </div>
        )}
      </div>
    )
  } catch (err) {
    console.error("Error in NotificationAlert render loop:", err)
    return null
  }
}
