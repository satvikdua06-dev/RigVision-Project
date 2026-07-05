import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useRigStore } from '../stores/useRigStore.js'
import { AgentPlanning } from './AgentPlanning.jsx'
import PipelineBeam from './ui/PipelineBeam.jsx'
import CircularGauge from './ui/CircularGauge.jsx'

// Backend progress stages → a monotonic order so the UI can tell what's done.
const STAGE_ORDER = {
  queued: 0, generating_query: 1, getting_subgraph: 2, subgraph_ready: 3,
  getting_chunks: 4, chunks_ready: 5, writing_answer: 6, done: 7, error: 99,
}

// The live pipeline checklist. reachedAt = active at/after this order; doneAt = complete.
const STEPS = [
  { key: 'query',    label: 'Generating Query',   detail: 'Parsing the alert into a graph query',              reachedAt: 1, doneAt: 2 },
  { key: 'subgraph', label: 'Getting Subgraph',   detail: 'Querying the Neo4j knowledge graph',                 reachedAt: 2, doneAt: 4 },
  { key: 'chunks',   label: 'Getting Chunks',     detail: 'Embedding + vector search over the device manuals',  reachedAt: 4, doneAt: 6 },
  { key: 'answer',   label: 'Writing the Answer', detail: 'Local LLM generating the root-cause report',         reachedAt: 6, doneAt: 7 },
]

const SEVERITY_COLOR = { LOW: '#46b17f', MEDIUM: '#d9a64e', HIGH: '#e06054', CRITICAL: '#e06054' }

const TIME_RANGES = [
  { value: 'all', label: 'All time' }, { value: '10m', label: 'Last 10 min' },
  { value: '1h', label: 'Last hour' }, { value: '6h', label: 'Last 6 hrs' },
  { value: '24h', label: 'Last 24 hrs' },
]
function cutoffMs(range) {
  const now = Date.now()
  if (range === '10m') return now - 10 * 60 * 1000
  if (range === '1h') return now - 60 * 60 * 1000
  if (range === '6h') return now - 6 * 60 * 60 * 1000
  if (range === '24h') return now - 24 * 60 * 60 * 1000
  return 0
}
function formatSensorKey(key) {
  return key.replace(/_c$/i, ' (°C)').replace(/_mm_s$/i, ' (mm/s)').replace(/_db$/i, ' (dB)')
    .replace(/_ppm$/i, ' (ppm)').replace(/_/g, ' ').toUpperCase()
}
function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

export default function DiagnosticsLive() {
  const { eventId } = useParams()
  const connectToBackend = useRigStore(s => s.connectToBackend)
  const connected = useRigStore(s => s.connected)
  const diagProgress = useRigStore(s => s.diagProgress) || {}
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const clearDiagnostics = useRigStore(s => s.clearDiagnostics)

  // A fresh tab has no live socket yet — open one so data + progress stream in.
  useEffect(() => { connectToBackend() }, [connectToBackend])

  const [selectedId, setSelectedId] = useState(eventId || null)
  const [timeRange, setTimeRange] = useState('all')
  const [clearedBefore, setClearedBefore] = useState(0)

  // Unified, newest-first event list: completed diagnostics (history, persisted) merged
  // with in-flight progress entries (live). Keyed by event_id so the two sources for the
  // same event collapse into one row.
  const events = useMemo(() => {
    const map = {}
    for (const d of diagnostics) {
      if (d && d.event_id) map[d.event_id] = { ...d, _ts: d.timestamp || 0 }
    }
    for (const p of Object.values(diagProgress)) {
      if (!p || !p.event_id) continue
      const prev = map[p.event_id] || {}
      map[p.event_id] = {
        ...prev,
        ...(p.report || {}),                 // final report (carried on the 'done' stage)
        event_id: p.event_id,
        zone_id: p.zone_id || prev.zone_id,
        severity: prev.severity || p.severity,
        _progress: p,
        _ts: Math.max(prev._ts || 0, p.updated_at || 0, p.report?.timestamp || 0),
      }
    }
    return Object.values(map).sort((a, b) => (b._ts || 0) - (a._ts || 0))
  }, [diagnostics, diagProgress])

  const visibleEvents = useMemo(
    () => events.filter(e => (e._ts || Date.now()) >= cutoffMs(timeRange) && (e._ts || 0) > clearedBefore),
    [events, timeRange, clearedBefore]
  )

  // Auto-select: the routed event if present, else the newest visible one.
  useEffect(() => {
    if (selectedId && events.some(e => e.event_id === selectedId)) return
    if (eventId && events.some(e => e.event_id === eventId)) { setSelectedId(eventId); return }
    if (visibleEvents.length) setSelectedId(visibleEvents[0].event_id)
  }, [eventId, selectedId, events, visibleEvents])

  const sel = events.find(e => e.event_id === selectedId) || visibleEvents[0] || null
  const selProgress = sel?._progress || null
  const isError = selProgress?.stage === 'error'
  const realOrder = selProgress ? (STAGE_ORDER[selProgress.stage] ?? 0) : (sel ? 7 : 0)
  const hasReport = !!(sel && (sel.primary_diagnosis || sel.reasoning))
  const accent = SEVERITY_COLOR[sel?.severity] || 'var(--accent-cobalt)'

  // Preserve staged reveal order per event ID to prevent animations from restarting
  // when clicking away and back.
  const [shownOrders, setShownOrders] = useState({})
  const currentShownOrder = sel ? (shownOrders[sel.event_id] ?? (hasReport ? 7 : 0)) : 0

  useEffect(() => {
    if (!sel) return
    if (hasReport && shownOrders[sel.event_id] === undefined) {
      setShownOrders(prev => ({ ...prev, [sel.event_id]: 7 }))
    }
  }, [sel, hasReport, shownOrders])

  const isCompleted = hasReport && currentShownOrder >= 7
  const isLive = !isCompleted && !isError && !!selProgress

  useEffect(() => {
    if (!sel || !isLive || currentShownOrder >= realOrder) return
    const t = setTimeout(() => {
      setShownOrders(prev => {
        const nextOrder = Math.min((prev[sel.event_id] ?? 0) + 1, realOrder)
        return { ...prev, [sel.event_id]: nextOrder }
      })
    }, 4000)
    return () => clearTimeout(t)
  }, [sel, isLive, realOrder, currentShownOrder])

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)', color: 'var(--text-primary)' }}>
      <style>{`
        @keyframes lp { 0%,100%{opacity:1} 50%{opacity:.4} }
        .lp { animation: lp 1.3s infinite ease-in-out; }
        @keyframes spin { to { transform: rotate(360deg) } }
        .spin { animation: spin 0.9s linear infinite; }
        .diag-row:hover { border-color: var(--border-bright) !important; }
        @keyframes orbSpin { from{stroke-dashoffset:0} to{stroke-dashoffset:-188} }
      `}</style>

      {/* Header */}
      <div style={{ height: 60, flexShrink: 0, display: 'flex', alignItems: 'center', padding: '0 28px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontFamily: 'var(--font-ui)', fontWeight: 700, fontSize: 18 }}>
          RIG<span style={{ color: 'var(--accent-cobalt)' }}>VISION</span>
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginLeft: 14, letterSpacing: 1, textTransform: 'uppercase' }}>
          AI Diagnostics Hub
        </span>
        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: connected ? 'var(--accent-green)' : 'var(--accent-red)' }}>
          {connected ? '● LIVE' : '○ CONNECTING…'}
        </span>
      </div>

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* Left: alert log list */}
        <div style={{ width: 340, flexShrink: 0, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', background: 'var(--bg-panel)' }}>
          <div style={{ padding: '10px 12px', background: 'var(--bg-card)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1.5, textTransform: 'uppercase' }}>Alert Logs</span>
            <div style={{ flex: 1 }} />
            <select value={timeRange} onChange={e => setTimeRange(e.target.value)}
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '3px 6px', cursor: 'pointer' }}>
              {TIME_RANGES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
            <button onClick={() => { clearDiagnostics(); setSelectedId(null); }} title="Delete all diagnostics reports from the system"
              style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 4, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 10, padding: '3px 8px', cursor: 'pointer' }}>
              CLEAR
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
            {visibleEvents.length === 0 ? (
              <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '40px 10px' }}>
                No incident reports logged.
              </div>
            ) : visibleEvents.map(e => {
              const live = e._progress && e._progress.stage !== 'done' && e._progress.stage !== 'error'
              const err = e._progress?.stage === 'error'
              const sc = SEVERITY_COLOR[e.severity] || '#46b17f'
              const isSelected = sel?.event_id === e.event_id
              const title = err ? 'Diagnosis Failed' : live ? 'Analyzing…' : (e.primary_diagnosis || 'Unknown Anomaly')
              return (
                <div key={e.event_id} className="diag-row" onClick={() => setSelectedId(e.event_id)}
                  style={{ padding: '12px 14px', borderRadius: 6, marginBottom: 8, cursor: 'pointer',
                    background: isSelected ? 'var(--bg-card)' : 'var(--bg-panel)', border: '1px solid var(--border)',
                    borderLeft: `3px solid ${err ? '#e06054' : sc}` }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span className={live ? 'lp' : ''} style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fontWeight: 600, color: err ? 'var(--accent-red)' : sc, letterSpacing: 1 }}>
                      {err ? 'ERROR' : live ? 'ANALYZING' : (e.severity || 'INFO')}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)' }}>{e._ts ? timeAgo(e._ts) : 'just now'}</span>
                  </div>
                  <div style={{ fontFamily: 'var(--font-ui)', fontSize: 14, fontWeight: 600, color: isSelected ? 'var(--accent-cobalt)' : 'var(--text-primary)', marginBottom: 6, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>ID: {e.event_id ? e.event_id.replace(/^anom_/, '') : 'unknown'}</span>
                    <span>{(e.zone_id || '—').toString().replace(/_/g, ' ').toUpperCase()}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Right: detail (live pipeline OR full report) */}
        <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
          {!sel ? (
            <div style={{ padding: 60, textAlign: 'center', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
              <div className="lp">Waiting for a diagnosis…</div>
            </div>
          ) : isLive ? (
            <LivePipeline sel={sel} shownOrder={currentShownOrder} isError={isError} accent={accent} hasReport={hasReport} />
          ) : (
            <ReportDetail sel={sel} accent={accent} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Live staged pipeline (in-flight event) ───────────────────────────────────
function LivePipeline({ sel, shownOrder, isError, accent, hasReport }) {
  const p = sel._progress || {}

  const stepStatus = (step) => {
    if (isError && shownOrder < step.doneAt) return shownOrder >= step.reachedAt ? 'error' : 'pending'
    if (shownOrder >= step.doneAt) return 'success'
    if (shownOrder >= step.reachedAt) return 'active'
    return 'pending'
  }

  const planSteps = STEPS.map(step => {
    const status = stepStatus(step)
    let content = null
    let defaultExpanded = false

    if (step.key === 'query' && status !== 'pending') {
      content = (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6, padding: '8px 10px', background: 'var(--bg-panel)', borderRadius: 6, border: '1px solid var(--border)' }}>
          {sel.zone_id && (
            <div>Zone: <span style={{ color: 'var(--accent-cobalt)', fontWeight: 600 }}>{sel.zone_id.replace(/_/g, ' ').toUpperCase()}</span></div>
          )}
          {(sel.severity || p.severity) && (
            <div>Severity: <span style={{ color: accent, fontWeight: 600 }}>{sel.severity || p.severity}</span></div>
          )}
          {sel.triggered_sensors?.length > 0 && (
            <div>Triggered: <span style={{ color: 'var(--accent-amber)' }}>{sel.triggered_sensors.join(', ')}</span></div>
          )}
        </div>
      )
    }

    if (step.key === 'subgraph' && shownOrder >= 4 && p.subgraph) {
      content = <SubgraphGraph text={p.subgraph} />
      defaultExpanded = true
    }

    if (step.key === 'chunks' && shownOrder >= 6 && p.chunks) {
      content = <ManualChunks text={p.chunks} />
      defaultExpanded = true
    }

    if (step.key === 'answer' && status === 'active') {
      content = (
        <div className="lp" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', padding: '8px 10px', background: 'var(--bg-panel)', borderRadius: 6, border: '1px solid var(--border)' }}>
          Local LLM generating root-cause report…
        </div>
      )
      defaultExpanded = true
    }

    return { id: step.key, title: step.label, detail: step.detail, status, content, defaultExpanded }
  })

  return (
    <div style={{ padding: 28, maxWidth: 820 }}>
      {/* Animated beam — shows the pipeline topology with traveling dashes */}
      <PipelineBeam shownOrder={shownOrder} isError={isError} accent={accent} />

      {/* Event badge row */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 20 }}>
        {sel.severity && (
          <span style={{ background: 'var(--bg-card)', border: `1px solid ${accent}`, color: accent, fontSize: 10, fontWeight: 600, padding: '2px 10px', borderRadius: 4, fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>
            {sel.severity}
          </span>
        )}
        {sel.zone_id && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
            ZONE: <span style={{ color: 'var(--accent-cobalt)', fontWeight: 600 }}>{sel.zone_id.replace(/_/g, ' ').toUpperCase()}</span>
          </span>
        )}
        {sel.event_id && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)' }}>
            {sel.event_id.replace(/^anom_/, '')}
          </span>
        )}
      </div>

      {isError && (
        <div style={{ marginBottom: 20, background: 'var(--bg-card)', border: '1px solid var(--accent-red)', borderLeft: '3px solid var(--accent-red)', borderRadius: 8, padding: '12px 16px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent-red)', letterSpacing: 1, fontWeight: 600, marginBottom: 6, textTransform: 'uppercase' }}>
            Pipeline Error
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>
            {p.error || 'The diagnosis pipeline failed.'}
          </div>
        </div>
      )}

      <AgentPlanning title="Diagnosis Pipeline" steps={planSteps} />
    </div>
  )
}

// ── Numbered step header for process timeline in ReportDetail ────────────────
function StepBadge({ num, label, accent }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, marginTop: 22 }}>
      <div style={{
        fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
        color: accent || 'var(--accent-cobalt)', letterSpacing: 1,
        padding: '2px 8px', borderRadius: 3,
        border: `1px solid ${accent || 'var(--accent-cobalt)'}44`,
        background: `${accent || 'var(--accent-cobalt)'}0d`,
        flexShrink: 0,
      }}>
        {num}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: 1.5, textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ flex: 1, height: 1, background: 'var(--border-solid)' }} />
    </div>
  )
}

// ── Full report detail (completed event) — ported from the old modal ─────────
function ReportDetail({ sel, accent }) {
  const subgraphText = sel.subgraph || sel._progress?.subgraph
  const chunksText = sel.chunks || sel._progress?.chunks

  return (
    <div style={{ padding: 24, boxSizing: 'border-box' }}>
      <style>{`
        .rpt-step { animation: report-step-in 0.35s ease both; }
        .rpt-step:nth-child(1) { animation-delay: 0.04s; }
        .rpt-step:nth-child(2) { animation-delay: 0.11s; }
        .rpt-step:nth-child(3) { animation-delay: 0.18s; }
        .rpt-step:nth-child(4) { animation-delay: 0.25s; }
      `}</style>

      {/* Meta header */}
      <div style={{ display: 'flex', gap: 20, justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border)', paddingBottom: 16, marginBottom: 4 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            <span style={{ background: 'var(--bg-card)', border: `1px solid ${accent}`, color: accent, fontSize: 10, fontWeight: 600, padding: '2px 10px', borderRadius: 4, fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>{sel.severity || 'CRITICAL'}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>ID: <span style={{ color: 'var(--text-primary)' }}>{sel.event_id || 'unknown'}</span></span>
            <span style={{ color: 'var(--border-bright)' }}>|</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>ZONE: <span style={{ color: 'var(--accent-cobalt)', fontWeight: 600 }}>{(sel.zone_id || 'UNKNOWN').toString().replace(/_/g, ' ').toUpperCase()}</span></span>
          </div>
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: 26, fontWeight: 600, lineHeight: 1.15 }}>{sel.primary_diagnosis || 'Unclassified failure mode'}</div>
        </div>
        <div style={{ textAlign: 'center', flexShrink: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 6, textTransform: 'uppercase' }}>Confidence</div>
          <CircularGauge
            size={68}
            value={sel.confidence_score || 0}
            meta={{ min: 0, max: 100, warning: 40, critical: 20, unit: '%' }}
            label=""
          />
        </div>
      </div>

      {/* Process timeline — numbered sections reveal with stagger */}
      <div>

      {/* Step 01 — Telemetry */}
      <div className="rpt-step">
        <StepBadge num="01" label="Anomalous Sensor Telemetry" accent={accent} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 4 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Telemetry snapshot */}
          <Card title="Telemetry Snapshot">
            {sel.telemetry_snapshot ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {Object.entries(sel.telemetry_snapshot).map(([key, val]) => {
                  const isTriggered = sel.triggered_sensors?.some(s => key.toLowerCase().includes(s.toLowerCase()))
                  const ctx = sel.threshold_context?.[key]
                  const isLow = ctx?.breach_direction === 'low'
                  const showLimits = ctx && (isLow ? (ctx.warning_low != null || ctx.critical_low != null) : (ctx.warning_min != null || ctx.critical_min != null))
                  return (
                    <div key={key} style={{ background: 'var(--bg-panel)', border: `1px solid ${isTriggered ? 'var(--accent-red)' : 'var(--border)'}`, borderRadius: 6, padding: '8px 10px' }}>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>{formatSensorKey(key)}</div>
                      <div style={{ fontFamily: 'var(--font-ui)', fontSize: 18, fontWeight: 600, color: isTriggered ? 'var(--accent-red)' : 'var(--accent-green)', marginTop: 2 }}>
                        {val}{isTriggered && <span style={{ fontSize: 10, marginLeft: 6, color: 'var(--accent-red)' }}>⚠ ALERT</span>}
                      </div>
                      {isTriggered && ctx && (
                        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)', fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', lineHeight: 1.4 }}>
                          {ctx.breach_direction && <div style={{ color: 'var(--accent-red)', fontWeight: 600, letterSpacing: 1 }}>{isLow ? '▼ LOW BREACH' : '▲ HIGH BREACH'}</div>}
                          {showLimits && (
                            <div style={{ color: 'var(--accent-amber)', fontWeight: 600 }}>
                              {isLow
                                ? <>LIMITS: {ctx.warning_low != null ? `Warn ≤${ctx.warning_low}` : '—'} / {ctx.critical_low != null ? `Crit ≤${ctx.critical_low}` : '—'} {ctx.unit || ''}</>
                                : <>LIMITS: {ctx.warning_min != null ? `Warn ≥${ctx.warning_min}` : '—'} / {ctx.critical_min != null ? `Crit ≥${ctx.critical_min}` : '—'} {ctx.unit || ''}</>}
                            </div>
                          )}
                          {ctx.source_manual && <div style={{ color: 'var(--accent-cobalt)', marginTop: 2 }}>📄 {ctx.source_manual} {ctx.source_section ? `(Sec ${ctx.source_section})` : ''}</div>}
                          {ctx.device_name && <div style={{ marginTop: 1 }}>⚙ Equipment: {ctx.device_name}</div>}
                          {ctx.selection_reason && <div style={{ color: 'var(--text-dim)', fontSize: 8.5, fontStyle: 'italic', marginTop: 3 }}>{ctx.selection_reason}</div>}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                No telemetry snapshot. Triggered: {sel.triggered_sensors?.join(', ') || '—'}
              </div>
            )}
          </Card>
 
          {/* Subgraph if still available, else topology hint */}
          {subgraphText ? (
            <Card title="Knowledge Graph Subgraph"><SubgraphGraph text={subgraphText} /></Card>
          ) : (
            <Card title="Neo4j Topology Relations">
              <div style={{ ...preStyle, color: 'var(--text-muted)' }}>
                {sel.triggered_sensors?.map(s => `• sensor "${s}" → suspected device/area failure modes`).join('\n') || 'No topology captured.'}
                {'\n\nMATCH (z:Zone)-[:CONTAINS]->(d:Device)-[:CAN_EXPERIENCE]->(f:FailureMode)...'}
              </div>
            </Card>
          )}
        </div>
 
        {/* Step 02 — Reasoning */}
        <Card title="Negative Reasoning & Root-Cause">
          <div style={{ fontFamily: 'var(--font-ui)', fontSize: 14, lineHeight: 1.6, color: 'var(--text-primary)', background: 'var(--bg-deep)', borderRadius: 6, padding: 12, border: '1px solid var(--border)', minHeight: 120 }}>
            {sel.reasoning || 'No reasoning recorded.'}
          </div>
        </Card>
      </div>
      </div>{/* close rpt-step 01 */}

      {/* Step 02 — Retrieved Manual Chunks (RAG) */}
      {chunksText && (
        <div className="rpt-step">
          <StepBadge num="02" label="Retrieved Manual Chunks (RAG)" accent={accent} />
          <Card title="">
            <ManualChunks text={chunksText} />
          </Card>
        </div>
      )}

      {/* Step 03 — Emergency Response */}
      {sel.recommended_action && (
        <div className="rpt-step">
          <StepBadge num="03" label="Emergency Response Mitigation Protocol" accent="var(--accent-amber)" />
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderLeft: '4px solid var(--accent-amber)', borderRadius: 8, padding: 16 }}>
            <div style={{ fontFamily: 'var(--font-ui)', fontSize: 15, color: 'var(--text-primary)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{sel.recommended_action}</div>
          </div>
        </div>
      )}

      </div>{/* close process timeline */}
    </div>
  )
}

// ── SVG graphical node-edge visualization for Subgraph ──────────────────────
function parseSubgraphText(text) {
  if (!text) return { nodes: [], edges: [] }
  const nodes = []
  const edges = []
  const nodeSet = new Set()

  const addNode = (id, type, label, extra = {}) => {
    const key = id.toLowerCase().trim()
    if (!nodeSet.has(key)) {
      nodeSet.add(key)
      nodes.push({ id, type, label, ...extra })
    }
  }

  const addEdge = (source, target, label) => {
    edges.push({ source, target, label })
  }

  const lines = text.split('\n')
  let currentSection = ''
  let lastEntity = null

  for (let line of lines) {
    line = line.trim()
    if (!line) continue

    if (line.includes('KNOWLEDGE GRAPH TOPOLOGY')) {
      currentSection = 'topology'
      continue
    } else if (line.includes('INTER-EQUIPMENT CONNECTIVITY')) {
      currentSection = 'connectivity'
      continue
    } else if (line.includes('SPATIAL ZONE TOPOLOGY')) {
      currentSection = 'spatial'
      continue
    }

    if (currentSection === 'topology') {
      if (line.startsWith('Device:')) {
        const m = line.match(/^Device:\s*'([^']+)'(?:\s*\(([^)]+)\))?/)
        if (m) {
          lastEntity = m[1]
          addNode(lastEntity, 'device', lastEntity, { subtitle: m[2] || 'Equipment' })
        }
      } else if (line.startsWith('Area Hazard in')) {
        const m = line.match(/^Area Hazard in\s*'([^']+)'/)
        if (m) {
          lastEntity = m[1]
          addNode(lastEntity, 'zone', lastEntity, { subtitle: 'Zone' })
        }
      } else if (line.startsWith('- Possible Failure:') || line.startsWith('- Possible Hazard:')) {
        const m = line.match(/^-\s*Possible\s+(?:Failure|Hazard):\s*(.+)$/)
        if (m && lastEntity) {
          const failureName = m[1]
          const failureId = `fail:${lastEntity}:${failureName}`
          addNode(failureId, 'failure', failureName, { subtitle: 'Failure Mode' })
          addEdge(lastEntity, failureId, 'CAN_EXPERIENCE')
        }
      }
    } else if (currentSection === 'connectivity' || currentSection === 'spatial') {
      const m = line.match(/^-\s*'([^']+)'\s+([A-Z_]+)\s+'([^']+)'/)
      if (m) {
        const src = m[1]
        const rel = m[2]
        const dst = m[3]
        
        const srcType = currentSection === 'spatial' ? 'zone' : 'device'
        const dstType = currentSection === 'spatial' ? 'zone' : 'device'
        
        addNode(src, srcType, src, { subtitle: currentSection === 'spatial' ? 'Zone' : 'Equipment' })
        addNode(dst, dstType, dst, { subtitle: currentSection === 'spatial' ? 'Zone' : 'Equipment' })
        addEdge(src, dst, rel)
      }
    }
  }

  return { nodes, edges }
}

function SubgraphGraph({ text }) {
  const { nodes, edges } = useMemo(() => parseSubgraphText(text), [text])
  const [showRaw, setShowRaw] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const startPan = useRef({ x: 0, y: 0 })

  const handleMouseDown = (e) => {
    if (e.button === 0) { // Left click
      setIsPanning(true)
      startPan.current = { x: e.clientX - pan.x, y: e.clientY - pan.y }
    }
  }

  const handleMouseMove = (e) => {
    if (isPanning) {
      setPan({
        x: e.clientX - startPan.current.x,
        y: e.clientY - startPan.current.y
      })
    }
  }

  const handleMouseUp = () => {
    setIsPanning(false)
  }

  const handleWheel = (e) => {
    const zoomFactor = 1.05
    const nextZoom = e.deltaY < 0 ? zoom * zoomFactor : zoom / zoomFactor
    setZoom(Math.max(0.5, Math.min(3, nextZoom)))
  }

  // Pre-calculate edge groups to identify multiple/bidirectional edges between same node pair
  const edgeGroups = useMemo(() => {
    const groups = {}
    edges.forEach((e) => {
      const key = [e.source, e.target].sort().join('-')
      if (!groups[key]) groups[key] = []
      groups[key].push(e)
    })
    return groups
  }, [edges])

  const positions = useMemo(() => {
    if (nodes.length === 0) return {}
    const width = 600
    const height = 350
    const pos = {}

    // Initialize in a circle
    nodes.forEach((node, i) => {
      const angle = (i / nodes.length) * 2 * Math.PI
      pos[node.id] = {
        x: width / 2 + 150 * Math.cos(angle),
        y: height / 2 + 100 * Math.sin(angle),
      }
    })

    const k = 120 // rest length of springs
    const rep = 150000 // repulsion coefficient
    const att = 0.06 // attraction coefficient
    const iterations = 150
    let temp = 25 // temperature (max displacement per iteration)

    for (let iter = 0; iter < iterations; iter++) {
      const forces = {}
      nodes.forEach(n => { forces[n.id] = { x: 0, y: 0 } })

      // Repulsion (Coulomb)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const n1 = nodes[i]
          const n2 = nodes[j]
          const p1 = pos[n1.id]
          const p2 = pos[n2.id]
          const dx = p1.x - p2.x
          const dy = p1.y - p2.y
          const distSq = dx * dx + dy * dy || 1
          const dist = Math.sqrt(distSq)
          
          const f = rep / distSq
          forces[n1.id].x += (dx / dist) * f
          forces[n1.id].y += (dy / dist) * f
          forces[n2.id].x -= (dx / dist) * f
          forces[n2.id].y -= (dy / dist) * f
        }
      }

      // Attraction (Hooke)
      edges.forEach(edge => {
        const p1 = pos[edge.source]
        const p2 = pos[edge.target]
        if (!p1 || !p2) return
        const dx = p1.x - p2.x
        const dy = p1.y - p2.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        
        const f = att * (dist - k)
        forces[edge.source].x -= (dx / dist) * f
        forces[edge.source].y -= (dy / dist) * f
        forces[edge.target].x += (dx / dist) * f
        forces[edge.target].y += (dy / dist) * f
      })

      // Update positions with damped temperature cooling
      nodes.forEach(n => {
        const p = pos[n.id]
        const fx = forces[n.id].x
        const fy = forces[n.id].y
        const f_dist = Math.sqrt(fx * fx + fy * fy) || 1
        
        const disp = Math.min(f_dist, temp)
        p.x += (fx / f_dist) * disp
        p.y += (fy / f_dist) * disp

        // Keep within safe SVG boundaries with margin
        p.x = Math.max(50, Math.min(width - 50, p.x))
        p.y = Math.max(50, Math.min(height - 50, p.y))
      })

      // Cool temperature
      temp *= 0.95
    }

    return pos
  }, [nodes, edges])

  if (nodes.length === 0) {
    return (
      <div style={{ color: 'var(--text-dim)', fontStyle: 'italic', fontSize: 12, padding: 12 }}>
        No nodes found to visualize.
      </div>
    )
  }

  const colors = {
    device: { stroke: '#4fa8ff', fill: '#0a2540', text: '#e6f4ff', icon: '⚙️' },
    zone: { stroke: '#4fe0a5', fill: '#0a3a25', text: '#e6fff4', icon: '🚪' },
    failure: { stroke: '#ff6b6b', fill: '#3d0c0c', text: '#ffebeb', icon: '⚠️' },
  }

  const textStyle = {
    fontFamily: 'var(--font-ui)',
    userSelect: 'none',
    paintOrder: 'stroke fill',
    stroke: 'var(--bg-deep)',
    strokeWidth: '4px',
    strokeLinejoin: 'round',
  }

  const monoStyle = {
    fontFamily: 'var(--font-mono)',
    userSelect: 'none',
    paintOrder: 'stroke fill',
    stroke: 'var(--bg-deep)',
    strokeWidth: '3px',
    strokeLinejoin: 'round',
  }

  const smallBtnStyle = {
    background: 'var(--bg-panel)',
    border: '1px solid var(--border)',
    color: 'var(--text-primary)',
    borderRadius: 4,
    padding: '2px 8px',
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
    cursor: 'pointer',
    transition: 'all 0.15s',
  }

  return (
    <div style={{ background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 8, padding: 12, position: 'relative', overflow: 'hidden' }}>
      {/* Controls Overlay */}
      <div style={{ position: 'absolute', right: 12, top: 12, display: 'flex', gap: 6, zIndex: 10 }}>
        <button onClick={() => setShowRaw(!showRaw)} style={smallBtnStyle}>
          {showRaw ? 'SHOW VISUAL' : 'SHOW RAW TEXT'}
        </button>
        {!showRaw && (
          <>
            <button onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }) }} style={smallBtnStyle} title="Reset View">RESET</button>
            <button onClick={() => setZoom(z => Math.max(0.5, z - 0.15))} style={smallBtnStyle}>-</button>
            <button onClick={() => setZoom(z => Math.min(3, z + 0.15))} style={smallBtnStyle}>+</button>
          </>
        )}
      </div>

      {showRaw ? (
        <pre style={{ ...preStyle, maxHeight: 300, margin: 0, marginTop: 24 }}>{text}</pre>
      ) : (
        <div
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
          onWheel={handleWheel}
          style={{ cursor: isPanning ? 'grabbing' : 'grab', overflow: 'hidden', height: 350 }}
        >
          <svg width="100%" height="350" viewBox="0 0 600 350" style={{ display: 'block' }}>
            <defs>
              <marker id="arrow-device" viewBox="0 0 10 10" refX="24" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#4fa8ff" />
              </marker>
              <marker id="arrow-failure" viewBox="0 0 10 10" refX="24" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#ff6b6b" />
              </marker>
              <marker id="arrow-zone" viewBox="0 0 10 10" refX="24" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#4fe0a5" />
              </marker>
              <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="3" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
            </defs>

            {/* Transform Group for Pan & Zoom */}
            <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`} transform-origin="300 175">
              {/* Edges */}
              {edges.map((e, index) => {
                const p1 = positions[e.source]
                const p2 = positions[e.target]
                if (!p1 || !p2) return null

                const isFailure = e.label === 'CAN_EXPERIENCE'
                const isZone = e.label === 'CONNECTS_TO'
                const strokeColor = isFailure ? '#ff6b6b' : isZone ? '#4fe0a5' : '#4fa8ff'
                const markerId = isFailure ? 'url(#arrow-failure)' : isZone ? 'url(#arrow-zone)' : 'url(#arrow-device)'
                const isDashed = isZone

                // Calculate curve offset using the lexicographically sorted node ID pair
                const key = [e.source, e.target].sort().join('-')
                const group = edgeGroups[key] || []
                const edgeIndex = group.indexOf(e)
                const count = group.length

                // Keep direction normal vector consistent across A->B and B->A
                const swap = e.source.localeCompare(e.target) > 0
                const xa = swap ? p2.x : p1.x
                const ya = swap ? p2.y : p1.y
                const xb = swap ? p1.x : p2.x
                const yb = swap ? p1.y : p2.y

                const dx = xb - xa
                const dy = yb - ya
                const len = Math.sqrt(dx * dx + dy * dy) || 1
                const nx = -dy / len
                const ny = dx / len

                let offset = 0
                if (count > 1) {
                  offset = (edgeIndex - (count - 1) / 2) * 35
                }

                // Control point for quadratic bezier
                const mx = (xa + xb) / 2
                const my = (ya + yb) / 2
                const cx_val = mx + offset * nx
                const cy_val = my + offset * ny

                // Path data: curve only when count > 1 to resolve overlapping
                const pathD = offset === 0
                  ? `M ${p1.x} ${p1.y} L ${p2.x} ${p2.y}`
                  : `M ${p1.x} ${p1.y} Q ${cx_val} ${cy_val} ${p2.x} ${p2.y}`

                // Midpoint on the actual curve (where text label goes)
                const tx = mx + (offset / 2) * nx
                const ty = my + (offset / 2) * ny

                return (
                  <g key={`edge-${index}`}>
                    <path
                      d={pathD}
                      fill="none"
                      stroke={strokeColor}
                      strokeWidth={1.5}
                      strokeDasharray={isDashed ? '4,4' : undefined}
                      markerEnd={markerId}
                      opacity={0.8}
                    />
                    <text
                      x={tx}
                      y={ty - 4}
                      fill={strokeColor}
                      fontSize="8.5"
                      textAnchor="middle"
                      style={monoStyle}
                    >
                      {e.label}
                    </text>
                  </g>
                )
              })}

              {/* Nodes */}
              {nodes.map(n => {
                const pos = positions[n.id]
                if (!pos) return null

                const config = colors[n.type] || colors.device
                return (
                  <g key={n.id} style={{ cursor: 'pointer' }}>
                    {/* Orbital ring — traveling dashes on failure/risk nodes (radial orbital concept) */}
                    {n.type === 'failure' && (
                      <circle
                        cx={pos.x} cy={pos.y} r="30"
                        fill="none" stroke="#ff6b6b" strokeWidth="0.8"
                        strokeDasharray="5 4" opacity="0.35"
                        style={{ animation: 'orbSpin 4s linear infinite', transformOrigin: `${pos.x}px ${pos.y}px` }}
                      />
                    )}
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r="20"
                      fill="transparent"
                      stroke={config.stroke}
                      strokeWidth="1"
                      opacity="0.3"
                    />
                    <circle
                      cx={pos.x}
                      cy={pos.y}
                      r="16"
                      fill={config.fill}
                      stroke={config.stroke}
                      strokeWidth="2"
                      style={{ filter: 'url(#glow)' }}
                    />
                    <text
                      x={pos.x}
                      y={pos.y + 4}
                      textAnchor="middle"
                      fontSize="12"
                    >
                      {config.icon}
                    </text>
                    <text
                      x={pos.x}
                      y={pos.y + 30}
                      fill="var(--text-primary)"
                      fontSize="9"
                      fontWeight="600"
                      textAnchor="middle"
                      style={textStyle}
                    >
                      {n.label}
                    </text>
                    <text
                      x={pos.x}
                      y={pos.y + 40}
                      fill="var(--text-muted)"
                      fontSize="7"
                      textAnchor="middle"
                      style={monoStyle}
                    >
                      {n.subtitle}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>
        </div>
      )}
    </div>
  )
}

function ManualChunks({ text }) {
  if (!text) return null

  // Split by manual sections
  const chunks = text.split(/(?=---\s+[^-\n]+\s+---)/g).map(c => c.trim()).filter(Boolean)

  if (chunks.length === 0) {
    return <pre style={preStyle}>{text}</pre>
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 16 }}>
      {chunks.map((chunk, index) => {
        const lines = chunk.split('\n')
        let title = `Reference Manual Chunk ${index + 1}`
        const metadata = []
        const contentLines = []

        lines.forEach(line => {
          const trimmed = line.trim()
          if (!trimmed) return

          if (trimmed.startsWith('---') && trimmed.endsWith('---')) {
            title = trimmed.replace(/---/g, '').trim()
          } else if (trimmed.match(/^(Device|Model|Manufacturer|Equipment Class|Document|Scope):\s*(.+)$/i)) {
            const m = trimmed.match(/^(Device|Model|Manufacturer|Equipment Class|Document|Scope):\s*(.+)$/i)
            metadata.push({ label: m[1], value: m[2] })
          } else {
            contentLines.push(trimmed)
          }
        })

        return (
          <div
            key={index}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: 16,
              boxShadow: '0 2px 8px rgba(0,0,0,0.2)'
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16 }}>📄</span>
                <span style={{ fontFamily: 'var(--font-ui)', fontWeight: 600, fontSize: 14, color: 'var(--accent-cobalt)', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  {title}
                </span>
              </div>
              <a
                href={`/documents/manuals?section=${encodeURIComponent(title)}`}
                target="_blank"
                rel="noreferrer"
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '9.5px',
                  color: 'var(--accent-amber)',
                  textDecoration: 'none',
                  border: '1px solid var(--accent-amber)',
                  borderRadius: '3px',
                  padding: '2px 6px',
                  background: 'transparent',
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  display: 'inline-block'
                }}
                onMouseOver={(e) => { e.currentTarget.style.background = 'rgba(217, 166, 78, 0.1)'; e.currentTarget.style.color = 'var(--text-primary)' }}
                onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--accent-amber)' }}
              >
                VIEW FULL DOC ↗
              </a>
            </div>

            {/* Metadata Badges */}
            {metadata.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                {metadata.map((m, i) => (
                  <div
                    key={i}
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      background: 'var(--bg-panel)',
                      border: '1px solid var(--border)',
                      padding: '3px 8px',
                      borderRadius: 4,
                      color: 'var(--text-muted)'
                    }}
                  >
                    <span style={{ color: 'var(--text-dim)' }}>{m.label}:</span> {m.value}
                  </div>
                ))}
              </div>
            )}

            {/* Chunk Body content */}
            <div style={{ fontFamily: 'var(--font-ui)', fontSize: 13, lineHeight: 1.6, color: 'var(--text-primary)' }}>
              {contentLines.map((line, i) => {
                const isSection = line.startsWith('Section')
                const isBullet = line.startsWith('- ')
                const isNumbered = /^\d+\.\s+/.test(line)

                let style = { marginBottom: 8 }
                if (isSection) {
                  style = {
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    fontSize: 11,
                    color: 'var(--accent-amber)',
                    textTransform: 'uppercase',
                    marginTop: 12,
                    marginBottom: 6,
                    borderBottom: '1px dashed var(--border)',
                    paddingBottom: 4
                  }
                } else if (isBullet || isNumbered) {
                  style = {
                    marginLeft: 12,
                    marginBottom: 6,
                    paddingLeft: 4
                  }
                }

                let formattedText = line
                if (isNumbered) {
                  const parts = line.split(':')
                  if (parts.length > 1) {
                    formattedText = (
                      <span>
                        <strong style={{ color: 'var(--text-primary)' }}>{parts[0]}:</strong>
                        {parts.slice(1).join(':')}
                      </span>
                    )
                  }
                }

                return (
                  <div key={i} style={style}>
                    {formattedText}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const sectionTitle = {
  fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', letterSpacing: 1.5,
  textTransform: 'uppercase', marginBottom: 16,
}
const preStyle = {
  fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.5, color: 'var(--text-muted)',
  background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 6,
  padding: 12, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 360, overflowY: 'auto',
}

function Card({ title, accent, children }) {
  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderLeft: accent ? `3px solid ${accent}` : '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', letterSpacing: 1.5, textTransform: 'uppercase', borderBottom: '1px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  )
}
