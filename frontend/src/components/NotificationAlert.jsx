import { useState, useEffect, useMemo, useRef } from 'react'
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
        const isHighBreach = (meta.critical != null && val >= meta.critical) ||
                             (meta.warning != null && val >= meta.warning);
        const isLowBreach = (meta.critical_low != null && val <= meta.critical_low) ||
                            (meta.warning_low != null && val <= meta.warning_low);
        if (isHighBreach || isLowBreach) {
          out.push(stype)
        }
      }
    }
  }
  return out
}

// Parse the pipeline's warning_reason string to identify the trigger.
// Handles: "temperature 54.0°C >= warning (60) [temp_a]"  → ['temperature']
//           "2 PPE violation(s)"                           → ['PPE']
//           "Overcrowded: 4/3 persons"                     → ['occupancy']
function parseWarningReason(reason) {
  if (!reason) return ['sensors']
  if (/ppe/i.test(reason)) return ['PPE']
  if (/overcrowd/i.test(reason)) return ['occupancy']
  const m = reason.match(/^(\w+)\s/)
  return m ? [m[1]] : ['sensors']
}

function findDiag(diagnostics, zoneId) {
  return diagnostics.find(
    d => d && (d.zone_id === zoneId || (ZONE_TO_KG[zoneId] && d.zone_id === ZONE_TO_KG[zoneId]))
  )
}

// Maps pipeline stage → progress % for the in-toast bar.
const STAGE_STEPS = ['generating_query', 'getting_subgraph', 'subgraph_ready', 'getting_chunks', 'chunks_ready', 'writing_answer', 'done']
function StageBar({ stage }) {
  const idx = STAGE_STEPS.indexOf(stage)
  const pct = idx < 0 ? 4 : Math.round(((idx + 1) / STAGE_STEPS.length) * 100)
  const label = stage ? stage.replace(/_/g, ' ') : 'queued'
  return (
    <div>
      <div style={{ height: 2, background: 'var(--border-solid)', borderRadius: 2, overflow: 'hidden', marginBottom: 4 }}>
        <div style={{
          height: '100%', width: `${pct}%`, borderRadius: 2,
          background: 'var(--accent-cobalt)',
          transition: 'width 0.5s ease',
        }} />
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 8.5, color: 'var(--text-dim)', letterSpacing: 0.5 }}>
        {label}
      </div>
    </div>
  )
}

// ── A single anomaly card ────────────────────────────────────────────────────
function AnomalyToast({ entry, diag, isAnalyzing, progress, age, onOpen, onClose }) {
  const { zone, zoneId, status } = entry
  const color = SEVERITY_COLOR[status] || '#e06054'

  let safetyStep = '', repairStep = ''
  if (diag?.recommended_action) {
    const steps = diag.recommended_action.split(/\d+\)\s+/).map(s => s.trim()).filter(Boolean)
    safetyStep = steps[0] || ''
    repairStep = steps[1] || ''
  }

  // Determine stage label for in-progress analysis
  let progressText = 'AI diagnostic agent is generating a root-cause report...'
  if (progress) {
    if (progress.stage === 'generating_query') {
      progressText = 'Parsing alert parameters and generating knowledge graph queries...'
    } else if (progress.stage === 'getting_subgraph') {
      progressText = 'Querying the Neo4j knowledge graph topology...'
    } else if (progress.stage === 'subgraph_ready') {
      progressText = 'Extracting topological context and facility connectivity...'
    } else if (progress.stage === 'getting_chunks') {
      progressText = 'Searching official device manuals and safety standards (RAG)...'
    } else if (progress.stage === 'chunks_ready') {
      progressText = 'Loading manuals and preparing prompt context...'
    } else if (progress.stage === 'writing_answer') {
      progressText = 'Local LLM (Gemma) is compiling the negative reasoning and mitigation report...'
    }
  }

  return (
    <div
      onClick={onOpen}
      style={{
        width: 380,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderLeft: `3px solid ${color}`,
        borderRadius: 'var(--radius)',
        padding: '16px 20px',
        boxSizing: 'border-box',
        boxShadow: 'var(--shadow-panel)',
        cursor: 'pointer',
        fontFamily: 'var(--font-ui)',
        color: 'var(--text-primary)',
        transition: 'border-color 0.2s ease',
        animation: 'toast-in 0.25s ease both',
      }}
      title="Click to view live diagnostics pipeline"
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
          {isAnalyzing && progress?.stage !== 'error' && (
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
      {diag ? (
        <div>
          <div style={{ fontSize: 17, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 8, lineHeight: 1.2 }}>
            {diag.primary_diagnosis || 'Unclassified failure mode'}
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
      ) : progress?.stage === 'error' ? (
        <div style={{ margin: '10px 0' }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--accent-red)', marginBottom: 4 }}>
            ⚠️ Diagnostic Failed
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.4 }}>
            {progress.error || 'The diagnostic pipeline encountered an error.'}
          </div>
        </div>
      ) : age > 30000 ? (
        <div style={{ margin: '10px 0' }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--accent-amber)', marginBottom: 4 }}>
            ⚠️ Diagnostic Timeout
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.4 }}>
            The diagnosis request timed out. Please check if the local LLM or Neo4j database is offline.
          </div>
        </div>
      ) : (
        <div style={{ margin: '10px 0' }}>
          <div className="pulse-alert" style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
            Analyzing Telemetry...
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.4, marginBottom: 10 }}>
            Breach detected on {entry.breachedSensors.join(', ') || 'sensors'}. {progressText}
          </div>
          {/* Pipeline stage progress bar */}
          <StageBar stage={progress?.stage} />
        </div>
      )}
    </div>
  )
}

// ── Stack of all currently-active anomalies ──────────────────────────────────
export default function NotificationAlert() {
  const zones = useRigStore(s => s.zones) || {}
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const diagProgress = useRigStore(s => s.diagProgress) || {}
  const hasReceivedData = useRigStore(s => s.hasReceivedData)
  const preexistingSignatures = useRigStore(s => s.preexistingSignatures) || []
  const isNotificationsInitialized = useRigStore(s => s.isNotificationsInitialized)
  const setPreexistingSignatures = useRigStore(s => s.setPreexistingSignatures)
  const removePreexistingSignature = useRigStore(s => s.removePreexistingSignature)
  const setNotificationsInitialized = useRigStore(s => s.setNotificationsInitialized)

  // Open the live diagnostics window in a NEW TAB. Anchor to the diagnosis the toast
  // is currently showing (`shownDiag`) so a click always opens THAT report — not an
  // older event. While still analyzing (no shown report yet) fall back to the newest
  // in-flight progress entry for the zone.
  // (Default window.open keeps `window.opener` so the new tab inherits the session
  // via authHandoff.js — do NOT add 'noopener' here.)
  const openLive = (zoneId, shownDiag) => {
    let eid = shownDiag?.event_id
    if (!eid) {
      const matches = Object.values(diagProgress).filter(
        p => p && (p.zone_id === zoneId || p.zone_id === ZONE_TO_KG[zoneId])
      )
      eid = matches.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0))[0]?.event_id
    }
    window.open(eid ? `/diagnostics/${eid}` : '/diagnostics', '_blank')
  }

  // Signatures the user has dismissed (per breach instance, keyed by signature).
  const [dismissed, setDismissed] = useState({})
  // Per-zone analyzing/ready bookkeeping: { [zoneId]: { signature, startedAt, isReady } }.
  const [anomalyStates, setAnomalyStates] = useState({})
  // When this component mounted. A diagnostic whose timestamp predates this is a
  // pre-existing report for an ongoing breach (e.g. the page was refreshed) — show
  // it immediately rather than a bogus "Analyzing…".
  const mountedAt = useRef(Date.now())

  // Every zone that currently has a real sensor breach (NOT just .find — all of them).
  const activeList = useMemo(() => {
    const list = []
    for (const [zoneId, zone] of Object.entries(zones)) {
      if (!zone || (zone.status !== 'warning' && zone.status !== 'critical')) continue
      // Prefer sensor_meta threshold check; fall back to warning_reason when resolved
      // thresholds differ from sensor_meta (e.g. Neo4j limits are tighter).
      // PPE violations and overcrowding do NOT generate anomaly notifications.
      const breachedSensors = sensorsBreached(zone)
      const displaySensors = breachedSensors.length > 0
        ? breachedSensors
        : parseWarningReason(zone.warning_reason)
      if (displaySensors.some(s => s === 'PPE' || s === 'occupancy' || s === 'sensors')) continue
      const signature = `${zoneId}:${zone.status}:${displaySensors.slice().sort().join(',')}`
      list.push({ zoneId, zone, status: zone.status, breachedSensors: displaySensors, signature })
    }
    return list
  }, [zones])

  // Track standing breaches at connection initialization so they are not toasted
  useEffect(() => {
    if (!hasReceivedData) return

    if (!isNotificationsInitialized) {
      const sigs = activeList.map(a => a.signature)
      setPreexistingSignatures(sigs)
      setNotificationsInitialized(true)
      console.log('[NotificationAlert] Initialized global pre-existing anomaly signatures:', sigs)
    } else {
      // Reconcile preexistingSignatures: if a signature is no longer present in activeList,
      // we remove it from the global store so that if a new breach occurs later
      // with the same signature, it correctly triggers a notification toast.
      const currentActiveSigs = new Set(activeList.map(a => a.signature))
      for (const sig of preexistingSignatures) {
        if (!currentActiveSigs.has(sig)) {
          removePreexistingSignature(sig)
          console.log('[NotificationAlert] Cleared pre-existing signature:', sig)
        }
      }
    }
  }, [hasReceivedData, activeList, preexistingSignatures, isNotificationsInitialized, setPreexistingSignatures, removePreexistingSignature, setNotificationsInitialized])

  // Reconcile analyzing state for each active zone. The store updates ~10Hz, so this
  // effect re-runs often enough to flip "Analyzing…" → ready once a report arrives
  // (or after a 30s fallback).
  useEffect(() => {
    setAnomalyStates(prev => {
      const next = {}
      let changed = Object.keys(prev).length !== activeList.length
      for (const a of activeList) {
        const diag = findDiag(diagnostics, a.zoneId)
        const reportSensors = diag?.triggered_sensors || []
        const matchesExactly = reportSensors.length === a.breachedSensors.length &&
          a.breachedSensors.every(s => reportSensors.includes(s))
        
        const cur = prev[a.zoneId]
        const startedAt = cur ? cur.startedAt : Date.now()
        
        const diagTime = diag?.timestamp ? new Date(diag.timestamp).getTime() : 0
        const fresh = diag && matchesExactly && diagTime >= startedAt - 1500
        const ongoingAtLoad = startedAt - mountedAt.current < 6000
        const preexisting = diag && matchesExactly && diagTime > 0 &&
          diagTime < mountedAt.current && ongoingAtLoad
        
        // Find progress report as well to help determine readiness
        const matches = Object.values(diagProgress).filter(
          p => p && (p.zone_id === a.zoneId || p.zone_id === ZONE_TO_KG[a.zoneId])
        )
        const latestProg = matches.sort((x, y) => (y.updated_at || 0) - (x.updated_at || 0))[0]
        const progReport = latestProg?.report
        const progReportTime = progReport?.timestamp ? new Date(progReport.timestamp).getTime() : 0
        const progFresh = progReport && progReportTime >= startedAt - 1500

        if (!cur || cur.signature !== a.signature) {
          const isReady = !!(fresh || preexisting || progFresh)
          next[a.zoneId] = { signature: a.signature, startedAt, isReady }
          changed = true
        } else {
          let isReady = cur.isReady
          if (!isReady) {
            const age = Date.now() - cur.startedAt
            if (fresh || preexisting || progFresh || age > 30000) isReady = true
          }
          next[a.zoneId] = { ...cur, isReady }
          if (isReady !== cur.isReady) changed = true
        }
      }
      return changed ? next : prev
    })
  }, [activeList, diagnostics, diagProgress])

  const visible = activeList.filter(a => {
    if (dismissed[a.signature]) return false
    const tracked = anomalyStates[a.zoneId]
    if (!tracked || tracked.signature !== a.signature) return false
    if (preexistingSignatures.includes(a.signature)) return false
    return true
  })
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
      {/* Toast count badge when multiple zones are active */}
      {visible.length > 1 && (
        <div style={{
          textAlign: 'right', fontFamily: 'var(--font-mono)', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: 1, paddingRight: 4, marginBottom: 2,
        }}>
          {visible.length} ACTIVE ANOMALIES
        </div>
      )}

      {visible.map(entry => {
        const diag = findDiag(diagnostics, entry.zoneId)
        const tracked = anomalyStates[entry.zoneId]
        const signatureKnown = tracked && tracked.signature === entry.signature
        
        const reportSensors = diag?.triggered_sensors || []
        const matchesExactly = reportSensors.length === entry.breachedSensors.length &&
          entry.breachedSensors.every(s => reportSensors.includes(s))
        const diagTime = diag?.timestamp ? new Date(diag.timestamp).getTime() : 0
        const fresh = signatureKnown && matchesExactly && diagTime >= tracked.startedAt - 1500
        const preexisting = signatureKnown && matchesExactly && diagTime > 0 &&
          diagTime < mountedAt.current && (tracked.startedAt - mountedAt.current < 6000)

        // Find progress report
        const matches = Object.values(diagProgress).filter(
          p => p && (p.zone_id === entry.zoneId || p.zone_id === ZONE_TO_KG[entry.zoneId])
        )
        const latestProg = matches.sort((x, y) => (y.updated_at || 0) - (x.updated_at || 0))[0]
        const progReport = latestProg?.report
        const progReportTime = progReport?.timestamp ? new Date(progReport.timestamp).getTime() : 0
        const progFresh = signatureKnown && progReport && progReportTime >= tracked.startedAt - 1500

        const activeDiag = (fresh || preexisting) ? diag : (progFresh ? progReport : null)
        const isAnalyzing = !activeDiag

        const age = tracked ? Date.now() - tracked.startedAt : 0

        return (
          <AnomalyToast
            key={entry.zoneId}
            entry={entry}
            diag={activeDiag}
            isAnalyzing={isAnalyzing}
            progress={latestProg}
            age={age}
            onOpen={() => openLive(entry.zoneId, activeDiag)}
            onClose={() => setDismissed(prev => ({ ...prev, [entry.signature]: true }))}
          />
        )
      })}
    </div>
  )
}
