import { useState, useEffect, useMemo } from 'react'
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

// Does this zone currently have at least one sensor over its warning/critical limit?
function sensorsBreached(zone) {
  const out = []
  if (zone && zone.sensor_meta) {
    for (const [stype, meta] of Object.entries(zone.sensor_meta)) {
      const val = zone[stype]
      if (val !== undefined && val !== null) {
        if ((meta.critical !== null && val >= meta.critical) ||
            (meta.warning !== null && val >= meta.warning)) {
          out.push(stype)
        }
      }
    }
  }
  return out
}

function findDiag(diagnostics, zoneId) {
  return diagnostics.find(
    d => d && (d.zone_id === zoneId || (ZONE_TO_KG[zoneId] && d.zone_id === ZONE_TO_KG[zoneId]))
  )
}

// ── A single anomaly card ────────────────────────────────────────────────────
function AnomalyToast({ entry, diag, isAnalyzing, onOpen, onClose }) {
  const { zone, zoneId, status } = entry
  const color = SEVERITY_COLOR[status] || '#e06054'

  // Parent only passes a diag that exactly matches the current breach and is fresh
  // (i.e. published after this signature started). When analyzing, parent sends null.
  // So here we just show "Analyzing…" while the report is in flight, otherwise show it.
  const displayDiag = !isAnalyzing ? diag : null

  let safetyStep = '', repairStep = ''
  if (displayDiag?.recommended_action) {
    const steps = displayDiag.recommended_action.split(/\d+\)\s+/).map(s => s.trim()).filter(Boolean)
    safetyStep = steps[0] || ''
    repairStep = steps[1] || ''
  }

  return (
    <div
      onClick={onOpen}
      style={{
        width: 380,
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
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color,
          letterSpacing: 1, display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span className={isAnalyzing ? 'pulse-alert' : ''} style={{ fontSize: 14 }}>🚨</span>
          <span>{status.toUpperCase()} ANOMALY: {(zone.name || zoneId).toUpperCase()}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {isAnalyzing && (
            <span className="pulse-alert" style={{
              fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--accent-amber)',
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              padding: '1px 6px', borderRadius: 4, letterSpacing: 1,
            }}>
              ANALYZING...
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onClose() }}
            style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 16, padding: 0, lineHeight: 1,
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
            Breach detected on {entry.breachedSensors.join(', ') || 'sensors'}. AI diagnostic agent is generating a root-cause report...
          </div>
        </div>
      ) : (
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8, lineHeight: 1.2 }}>
            {displayDiag.primary_diagnosis || 'Unclassified failure mode'}
          </div>

          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 12 }}>
            {safetyStep && (
              <div style={{ marginBottom: 6 }}>
                <strong style={{ color, fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', display: 'block' }}>
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

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
            <div className="alert-btn" style={{
              fontSize: 11, fontFamily: 'var(--font-mono)', color,
              border: `1px solid ${color}`, borderRadius: 4, padding: '4px 10px',
              background: 'var(--bg-card)', transition: 'all 0.2s', letterSpacing: 0.5,
            }}>
              VIEW FULL REPORT →
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Stack of all currently-active anomalies ──────────────────────────────────
export default function NotificationAlert() {
  const zones = useRigStore(s => s.zones) || {}
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const setShowModal = useRigStore(s => s.setShowDiagnosticsModal)

  // Signatures the user has dismissed (per breach instance, keyed by signature).
  const [dismissed, setDismissed] = useState({})
  // Per-zone analyzing/ready bookkeeping: { [zoneId]: { signature, startedAt, isReady } }.
  const [anomalyStates, setAnomalyStates] = useState({})

  // Every zone that currently has a real sensor breach (NOT just .find — all of them).
  const activeList = useMemo(() => {
    const list = []
    for (const [zoneId, zone] of Object.entries(zones)) {
      if (!zone || (zone.status !== 'warning' && zone.status !== 'critical')) continue
      const breachedSensors = sensorsBreached(zone)
      if (breachedSensors.length === 0) continue
      const signature = `${zoneId}:${zone.status}:${breachedSensors.slice().sort().join(',')}`
      list.push({ zoneId, zone, status: zone.status, breachedSensors, signature })
    }
    return list
  }, [zones])

  // Reconcile analyzing state for each active zone. The store updates ~10Hz, so this
  // effect re-runs often enough to flip "Analyzing…" → ready once a report arrives
  // (or after a 15s fallback). Functional update returns the same ref when unchanged,
  // so there's no render loop.
  //
  // STALENESS RULE: when the breach signature changes (e.g. {temp,vib} → {vib}), the
  // previous report is by definition stale, even if its triggered_sensors is still a
  // SUPERSET of the new breached set. We never accept a diagnostic that was published
  // before this signature started — only fresh ones (timestamp >= startedAt, with a
  // small clock-skew slack). The 15s fallback still applies if no fresh diag arrives.
  useEffect(() => {
    setAnomalyStates(prev => {
      const next = {}
      let changed = Object.keys(prev).length !== activeList.length
      for (const a of activeList) {
        const diag = findDiag(diagnostics, a.zoneId)
        const reportSensors = diag?.triggered_sensors || []
        // Exact match (not superset): the report's triggered sensors equal the
        // currently-breached ones. Prevents a stale "temp+vib" report from being
        // accepted as the diagnosis for a current "vib only" breach.
        const matchesExactly = reportSensors.length === a.breachedSensors.length &&
          a.breachedSensors.every(s => reportSensors.includes(s))
        const cur = prev[a.zoneId]
        if (!cur || cur.signature !== a.signature) {
          // New signature → don't pre-accept any cached diag (even an exact-match one),
          // because we can't yet know if it was published in response to THIS state.
          // The next reconciler tick will accept it once `diag.timestamp >= startedAt`.
          next[a.zoneId] = { signature: a.signature, startedAt: Date.now(), isReady: false }
          changed = true
        } else {
          let isReady = cur.isReady
          if (!isReady) {
            const age = Date.now() - cur.startedAt
            const diagTime = diag?.timestamp ? new Date(diag.timestamp).getTime() : 0
            const fresh = diag && matchesExactly && diagTime >= cur.startedAt - 1500
            if (fresh || age > 15000) isReady = true
          }
          next[a.zoneId] = { ...cur, isReady }
          if (isReady !== cur.isReady) changed = true
        }
      }
      return changed ? next : prev
    })
  }, [activeList, diagnostics])

  const visible = activeList.filter(a => !dismissed[a.signature])
  if (visible.length === 0) return null

  return (
    <div style={{
      position: 'fixed', top: 24, right: 24, zIndex: 99999,
      display: 'flex', flexDirection: 'column', gap: 12,
      maxHeight: 'calc(100vh - 48px)', overflowY: 'auto',
    }}>
      {/* Shared animations + button hover (rendered once for the whole stack) */}
      <style>{`
        @keyframes pulseFade { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
        .pulse-alert { animation: pulseFade 1.5s infinite ease-in-out; }
        .alert-btn:hover { background: var(--bg-card) !important; border-color: var(--border-bright) !important; color: var(--text-primary) !important; }
      `}</style>

      {visible.map(entry => {
        const diag = findDiag(diagnostics, entry.zoneId)
        const tracked = anomalyStates[entry.zoneId]
        const signatureKnown = tracked && tracked.signature === entry.signature
        // Exact-match (not superset) + freshness (arrived after the breach started):
        // both guards must hold to accept the cached diag as the live notification.
        // This is what prevents a stale "temp+vib" report from being shown when the
        // current breach is just "vib".
        const reportSensors = diag?.triggered_sensors || []
        const matchesExactly = reportSensors.length === entry.breachedSensors.length &&
          entry.breachedSensors.every(s => reportSensors.includes(s))
        const diagTime = diag?.timestamp ? new Date(diag.timestamp).getTime() : 0
        const fresh = signatureKnown && matchesExactly && diagTime >= tracked.startedAt - 1500
        const isAnalyzing = !(signatureKnown && (tracked.isReady || fresh))
        return (
          <AnomalyToast
            key={entry.zoneId}
            entry={entry}
            diag={fresh || tracked?.isReady ? diag : null}
            isAnalyzing={isAnalyzing}
            onOpen={() => setShowModal(true)}
            onClose={() => setDismissed(prev => ({ ...prev, [entry.signature]: true }))}
          />
        )
      })}
    </div>
  )
}
