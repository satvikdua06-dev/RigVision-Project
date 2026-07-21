/**
 * DailyReportPanel — daily shift report generator + AI review.
 *
 * Flow:
 *   1. GENERATE DRAFT  → sweeps last 24h of anomalies/incidents/violations
 *   2. Supervisor fills in what was done about each item
 *   3. SUBMIT          → saved, then the AI review engine analyses it against
 *                        report history for repeat failures and weak fixes
 *
 * Repeat detection is computed server-side from stored report history, so the
 * "seen N times" counts are facts, not model output.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../utils/api.js'

const host     = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

const SEV_COLOR = {
  CRITICAL: 'var(--accent-red)',
  HIGH:     'var(--accent-amber)',
  MEDIUM:   'var(--accent-cobalt)',
  INFO:     'var(--text-dim)',
}
const SOURCE_LABEL = {
  anomaly:    'SENSOR ANOMALY',
  incident:   'COMPOUND INCIDENT',
  compliance: 'COMPLIANCE VIOLATION',
  permit:     'PERMIT CLOSED',
}
const RESOLUTIONS = [
  { id: 'resolved',   label: 'RESOLVED',    color: 'var(--accent-green)' },
  { id: 'mitigated',  label: 'MITIGATED',   color: 'var(--accent-amber)' },
  { id: 'unresolved', label: 'UNRESOLVED',  color: 'var(--accent-red)'   },
]

const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString() : '—'

const inputStyle = {
  width: '100%', background: 'var(--bg-deep)',
  border: '1px solid var(--border-solid)', borderRadius: 3,
  color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
  fontSize: 11, padding: '6px 8px', outline: 'none', resize: 'vertical',
}
const labelStyle = {
  fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)',
  letterSpacing: 1, marginBottom: 3, display: 'block',
}

function Btn({ children, onClick, disabled, primary, danger }) {
  const color = danger ? 'var(--accent-red)' : primary ? 'var(--accent-cobalt)' : 'var(--text-muted)'
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: '7px 16px',
      border: `1px solid ${disabled ? 'var(--border-solid)' : color}`,
      borderRadius: 3,
      background: primary && !disabled ? 'rgba(91,141,239,0.12)' : 'transparent',
      color: disabled ? 'var(--text-dim)' : color,
      fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
      letterSpacing: 0.8, cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.5 : 1,
    }}>{children}</button>
  )
}

/** One line item in the draft form. */
function ItemCard({ item, value, onChange }) {
  const sev = SEV_COLOR[item.severity] || 'var(--text-dim)'
  const repeat = item.prior_count > 0

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border-solid)',
      borderLeft: `3px solid ${sev}`,
      borderRadius: 3, padding: '11px 13px', marginBottom: 10,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 6 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 3 }}>
            <span style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>
              {SOURCE_LABEL[item.source] || item.source?.toUpperCase()}
            </span>
            <span style={{
              fontSize: 8, fontWeight: 700, color: sev, letterSpacing: 1,
              border: `1px solid ${sev}40`, background: `${sev}14`,
              padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
            }}>{item.severity}</span>
            {item.occurrences > 1 && (
              <span style={{
                fontSize: 8, fontWeight: 700, color: 'var(--accent-amber)', letterSpacing: 1,
                border: '1px solid var(--accent-amber)40', background: 'rgba(217,166,78,0.14)',
                padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
              }}>{item.occurrences}× IN WINDOW</span>
            )}
            {repeat && (
              <span style={{
                fontSize: 8, fontWeight: 700, color: 'var(--accent-red)', letterSpacing: 1,
                border: '1px solid var(--accent-red)', background: 'rgba(224,96,84,0.14)',
                padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
              }}>↻ {item.prior_count + 1} REPORTS RUNNING</span>
            )}
          </div>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {item.title}
          </div>
        </div>
        <span style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
          {fmtTime(item.occurred_at)}
        </span>
      </div>

      {item.detail && (
        <div style={{
          fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          lineHeight: 1.5, marginBottom: 8,
        }}>{item.detail}</div>
      )}

      {repeat && item.last_action && (
        <div style={{
          fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          background: 'rgba(224,96,84,0.07)', border: '1px solid rgba(224,96,84,0.25)',
          borderRadius: 3, padding: '6px 8px', marginBottom: 8, lineHeight: 1.5,
        }}>
          <span style={{ color: 'var(--accent-red)', fontWeight: 700, letterSpacing: 0.8 }}>
            LAST TIME ({item.last_seen}):
          </span>{' '}
          {item.last_action || '(no action was recorded)'}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}>
        <div>
          <label style={labelStyle}>WHAT WAS DONE *</label>
          <textarea
            rows={2}
            value={value.action_taken}
            onChange={e => onChange({ ...value, action_taken: e.target.value })}
            placeholder="Actions taken to address this…"
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>ROOT CAUSE</label>
          <textarea
            rows={2}
            value={value.root_cause}
            onChange={e => onChange({ ...value, root_cause: e.target.value })}
            placeholder="Why did this happen?"
            style={inputStyle}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        {RESOLUTIONS.map(rz => {
          const active = value.resolution === rz.id
          return (
            <button
              key={rz.id}
              onClick={() => onChange({ ...value, resolution: rz.id })}
              style={{
                padding: '4px 10px', borderRadius: 2, cursor: 'pointer',
                border: `1px solid ${active ? rz.color : 'var(--border-solid)'}`,
                background: active ? `${rz.color}1a` : 'transparent',
                color: active ? rz.color : 'var(--text-dim)',
                fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700, letterSpacing: 0.8,
              }}
            >{rz.label}</button>
          )
        })}
      </div>
    </div>
  )
}

/** AI review output for a submitted report. */
function ReviewPanel({ review, onRerun, rerunning }) {
  if (!review || review.status === 'pending') {
    return (
      <div style={{
        padding: 24, textAlign: 'center', color: 'var(--text-dim)',
        fontFamily: 'var(--font-mono)', fontSize: 11,
        border: '1px solid var(--border-solid)', borderRadius: 4,
      }}>
        AI REVIEW IN PROGRESS — analysing report against history…
      </div>
    )
  }

  const recurring = review.recurring_issues || []
  const flags     = review.quality_flags || []

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{
          fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: 1,
          color: recurring.length ? 'var(--accent-red)' : 'var(--accent-green)',
          border: `1px solid ${recurring.length ? 'var(--accent-red)' : 'var(--accent-green)'}40`,
          background: recurring.length ? 'rgba(224,96,84,0.12)' : 'rgba(70,177,127,0.12)',
          padding: '3px 9px', borderRadius: 2,
        }}>
          {recurring.length} REPEAT ISSUE{recurring.length !== 1 ? 'S' : ''}
        </span>
        <span style={{
          fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: 1,
          color: flags.length ? 'var(--accent-amber)' : 'var(--text-dim)',
          border: `1px solid ${flags.length ? 'var(--accent-amber)' : 'var(--border-solid)'}40`,
          padding: '3px 9px', borderRadius: 2,
        }}>
          {flags.length} QUALITY FLAG{flags.length !== 1 ? 'S' : ''}
        </span>
        <div style={{ flex: 1 }} />
        <Btn onClick={onRerun} disabled={rerunning}>
          {rerunning ? 'RE-ANALYSING…' : 'RE-RUN REVIEW'}
        </Btn>
      </div>

      {recurring.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: 'var(--accent-red)', letterSpacing: 1,
            fontFamily: 'var(--font-mono)', marginBottom: 8,
          }}>RECURRING FAILURES — DETECTED FROM REPORT HISTORY</div>
          {recurring.map(rec => (
            <div key={rec.signature} style={{
              background: 'rgba(224,96,84,0.08)',
              border: '1px solid rgba(224,96,84,0.3)',
              borderLeft: '3px solid var(--accent-red)',
              borderRadius: 3, padding: '10px 12px', marginBottom: 8,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 5 }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                  {rec.title}
                </span>
                <span style={{
                  fontSize: 9, fontWeight: 700, color: 'var(--accent-red)', whiteSpace: 'nowrap',
                  fontFamily: 'var(--font-mono)', letterSpacing: 1,
                }}>{rec.times_seen}× SINCE {rec.first_seen}</span>
              </div>
              {rec.past_actions?.length > 0 && (
                <div style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.6 }}>
                  <span style={{ color: 'var(--text-dim)', letterSpacing: 0.8 }}>PREVIOUS FIXES: </span>
                  {rec.past_actions.join(' · ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {flags.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div style={{
            fontSize: 10, fontWeight: 700, color: 'var(--accent-amber)', letterSpacing: 1,
            fontFamily: 'var(--font-mono)', marginBottom: 8,
          }}>REPORT QUALITY FLAGS</div>
          {flags.map((f, i) => (
            <div key={i} style={{
              fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
              background: 'rgba(217,166,78,0.08)', border: '1px solid rgba(217,166,78,0.25)',
              borderRadius: 3, padding: '7px 10px', marginBottom: 6, lineHeight: 1.5,
            }}>⚠ {f}</div>
          ))}
        </div>
      )}

      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
        borderRadius: 4, padding: '14px 16px',
      }}>
        <MarkdownBlock text={review.narrative} />
      </div>
    </div>
  )
}

/** Minimal markdown block — mirrors InsightsPage's renderer. */
function MarkdownBlock({ text }) {
  if (!text) return null
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.7, color: 'var(--text-muted)' }}>
      {text.split('\n').map((line, i) => {
        const t = line.trim().replace(/^>\s?/, '')
        if (!t) return <div key={i} style={{ height: 8 }} />
        const h = t.match(/^(#{1,6})\s+(.*)$/)
        if (h) {
          const top = h[1].length <= 2
          return (
            <div key={i} style={{
              fontSize: top ? 12 : 11, fontWeight: 700,
              color: top ? 'var(--text-primary)' : 'var(--accent-cobalt)',
              letterSpacing: 0.8, marginTop: top ? 16 : 12, marginBottom: 5,
              borderBottom: top ? '1px solid var(--border-solid)' : 'none',
              paddingBottom: top ? 3 : 0,
            }}>{h[2].replace(/\*\*/g, '').toUpperCase()}</div>
          )
        }
        if (/^\d+[.)]\s/.test(t) || /^[-*+]\s/.test(t)) {
          const marker = (t.match(/^(\d+)[.)]/) || [])[1]
          return (
            <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3 }}>
              <span style={{ color: 'var(--accent-cobalt)', flexShrink: 0, minWidth: marker ? 14 : 8 }}>
                {marker ? `${marker}.` : '›'}
              </span>
              <span>{t.replace(/^(\d+[.)]|[-*+])\s*/, '').replace(/\*\*/g, '')}</span>
            </div>
          )
        }
        return <div key={i}>{t.replace(/\*\*/g, '')}</div>
      })}
    </div>
  )
}

export default function DailyReportPanel() {
  const [view, setView]         = useState('list')   // list | draft | report
  const [draft, setDraft]       = useState(null)
  const [answers, setAnswers]   = useState({})       // ref_id → {action_taken, root_cause, resolution}
  const [meta, setMeta]         = useState({ supervisor: '', shift: 'day', notes: '' })
  const [reports, setReports]   = useState([])
  const [active, setActive]     = useState(null)     // currently viewed submitted report
  const [busy, setBusy]         = useState(false)
  const [rerunning, setRerun]   = useState(false)
  const [error, setError]       = useState(null)

  const loadReports = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/daily-reports`, { headers: authHeaders() })
      if (res.ok) setReports(await res.json())
    } catch {}
  }, [])

  useEffect(() => { loadReports() }, [loadReports])

  // Poll while a review is still pending so the narrative appears when ready.
  useEffect(() => {
    if (view !== 'report' || !active || active.review?.status === 'ready') return
    const id = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/daily-report/${active.report_id}`, { headers: authHeaders() })
        if (!res.ok) return
        const fresh = await res.json()
        if (fresh.review?.status === 'ready') {
          setActive(fresh)
          loadReports()
        }
      } catch {}
    }, 4000)
    return () => clearInterval(id)
  }, [view, active, loadReports])

  const generateDraft = async () => {
    setBusy(true); setError(null)
    try {
      const res = await fetch(`${API_BASE}/daily-report/draft?hours=24`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const d = await res.json()
      setDraft(d)
      setAnswers(Object.fromEntries(
        (d.items || []).map(i => [i.ref_id, { action_taken: '', root_cause: '', resolution: 'resolved' }])
      ))
      setView('draft')
    } catch (e) { setError(`Could not build draft: ${e.message}`) }
    finally { setBusy(false) }
  }

  const submit = async () => {
    setBusy(true); setError(null)
    try {
      const items = (draft.items || []).map(i => ({ ...i, ...(answers[i.ref_id] || {}) }))
      const res = await fetch(`${API_BASE}/daily-report`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          report_date:  new Date().toISOString().slice(0, 10),
          shift:        meta.shift,
          supervisor:   meta.supervisor,
          notes:        meta.notes,
          window_hours: draft.window_hours,
          items,
        }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const { report } = await res.json()
      setActive(report)
      setView('report')
      setDraft(null)
      loadReports()
    } catch (e) { setError(`Submit failed: ${e.message}`) }
    finally { setBusy(false) }
  }

  const openReport = async (id) => {
    try {
      const res = await fetch(`${API_BASE}/daily-report/${id}`, { headers: authHeaders() })
      if (res.ok) { setActive(await res.json()); setView('report') }
    } catch {}
  }

  const rerunReview = async () => {
    if (!active) return
    setRerun(true)
    try {
      const res = await fetch(`${API_BASE}/daily-report/${active.report_id}/review`, {
        method: 'POST', headers: authHeaders(),
      })
      if (res.ok) setActive({ ...active, review: await res.json() })
    } catch {}
    finally { setRerun(false) }
  }

  const filledCount = draft
    ? (draft.items || []).filter(i => (answers[i.ref_id]?.action_taken || '').trim()).length
    : 0

  return (
    <div>
      {error && (
        <div style={{
          padding: '8px 12px', marginBottom: 14, borderRadius: 3,
          background: 'rgba(224,96,84,0.12)', border: '1px solid var(--accent-red)',
          color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', fontSize: 10,
        }}>{error}</div>
      )}

      {/* ── LIST VIEW ─────────────────────────────────────────────────── */}
      {view === 'list' && (
        <div>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderRadius: 6, padding: '16px 20px', marginBottom: 20,
          }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
                DAILY SHIFT REPORT
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: 4, letterSpacing: 0.3 }}>
                Sweeps the last 24h of anomalies, incidents and compliance violations into a report you complete.
                Submitted reports are analysed for repeat failures.
              </div>
            </div>
            <Btn primary onClick={generateDraft} disabled={busy}>
              {busy ? 'BUILDING…' : '+ GENERATE DAILY REPORT'}
            </Btn>
          </div>

          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5, marginBottom: 4,
          }}>SUBMITTED REPORTS</div>
          <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: 14 }}>
            {reports.length} report{reports.length !== 1 ? 's' : ''} on file
          </div>

          {reports.length === 0 ? (
            <div style={{
              padding: 30, textAlign: 'center', color: 'var(--text-dim)',
              fontFamily: 'var(--font-mono)', fontSize: 11,
              border: '1px dashed var(--border-solid)', borderRadius: 4,
            }}>
              NO REPORTS YET — GENERATE ONE TO START THE HISTORY
            </div>
          ) : reports.map(rep => {
            const repeats = rep.review?.recurring_issues?.length || 0
            return (
              <div key={rep.report_id} onClick={() => openReport(rep.report_id)} style={{
                background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
                borderRadius: 3, padding: '10px 13px', marginBottom: 8, cursor: 'pointer',
                display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
              }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                    {rep.report_id}
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: 3 }}>
                    {rep.report_date} · {String(rep.shift).toUpperCase()} SHIFT · {rep.supervisor} · {rep.items?.length || 0} items
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {repeats > 0 && (
                    <span style={{
                      fontSize: 9, fontWeight: 700, color: 'var(--accent-red)', letterSpacing: 0.8,
                      border: '1px solid var(--accent-red)40', background: 'rgba(224,96,84,0.12)',
                      padding: '2px 6px', borderRadius: 2, fontFamily: 'var(--font-mono)',
                    }}>↻ {repeats} REPEAT</span>
                  )}
                  <span style={{
                    fontSize: 9, fontWeight: 700, letterSpacing: 0.8, fontFamily: 'var(--font-mono)',
                    color: rep.review?.status === 'ready' ? 'var(--accent-green)' : 'var(--accent-amber)',
                  }}>
                    {rep.review?.status === 'ready' ? 'REVIEWED' : 'REVIEW PENDING'}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── DRAFT FORM ────────────────────────────────────────────────── */}
      {view === 'draft' && draft && (
        <div>
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderRadius: 6, padding: '14px 18px', marginBottom: 18,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
                  NEW DAILY REPORT
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: 3 }}>
                  {draft.item_count} item{draft.item_count !== 1 ? 's' : ''}
                  {draft.raw_event_count > draft.item_count && ` (grouped from ${draft.raw_event_count} events)`}
                  {' since '}{fmtTime(draft.window_start)}
                  {' · '}{filledCount}/{draft.item_count} completed
                </div>
              </div>
              <Btn onClick={() => { setView('list'); setDraft(null) }}>CANCEL</Btn>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 140px', gap: 12, marginBottom: 10 }}>
              <div>
                <label style={labelStyle}>SUPERVISOR *</label>
                <input
                  value={meta.supervisor}
                  onChange={e => setMeta({ ...meta, supervisor: e.target.value })}
                  placeholder="Name of reporting supervisor"
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={labelStyle}>SHIFT</label>
                <select
                  value={meta.shift}
                  onChange={e => setMeta({ ...meta, shift: e.target.value })}
                  style={inputStyle}
                >
                  <option value="day">DAY</option>
                  <option value="night">NIGHT</option>
                </select>
              </div>
            </div>
            <div>
              <label style={labelStyle}>SHIFT NOTES</label>
              <textarea
                rows={2}
                value={meta.notes}
                onChange={e => setMeta({ ...meta, notes: e.target.value })}
                placeholder="Anything else the next shift or a DGMS inspector should know…"
                style={inputStyle}
              />
            </div>
          </div>

          {draft.item_count === 0 ? (
            <div style={{
              padding: 30, textAlign: 'center', color: 'var(--accent-green)',
              fontFamily: 'var(--font-mono)', fontSize: 11,
              border: '1px solid var(--accent-green)', borderRadius: 4,
              background: 'rgba(70,177,127,0.08)', marginBottom: 18,
            }}>
              NO ANOMALIES, INCIDENTS OR VIOLATIONS IN THE LAST 24 HOURS — CLEAN SHIFT
            </div>
          ) : (
            draft.items.map(item => (
              <ItemCard
                key={item.ref_id}
                item={item}
                value={answers[item.ref_id] || { action_taken: '', root_cause: '', resolution: 'resolved' }}
                onChange={v => setAnswers({ ...answers, [item.ref_id]: v })}
              />
            ))
          )}

          <div style={{
            display: 'flex', justifyContent: 'flex-end', gap: 10,
            paddingTop: 14, borderTop: '1px solid var(--border-solid)',
          }}>
            <Btn onClick={() => { setView('list'); setDraft(null) }}>CANCEL</Btn>
            <Btn primary onClick={submit} disabled={busy || !meta.supervisor.trim()}>
              {busy ? 'SUBMITTING…' : 'SUBMIT REPORT → AI REVIEW'}
            </Btn>
          </div>
          {!meta.supervisor.trim() && (
            <div style={{
              textAlign: 'right', fontSize: 9, color: 'var(--text-dim)',
              fontFamily: 'var(--font-mono)', marginTop: 6,
            }}>Supervisor name is required to submit</div>
          )}
        </div>
      )}

      {/* ── SUBMITTED REPORT + REVIEW ─────────────────────────────────── */}
      {view === 'report' && active && (
        <div>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderRadius: 6, padding: '14px 18px', marginBottom: 18,
          }}>
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
                {active.report_id}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
                {active.report_date} · {String(active.shift).toUpperCase()} SHIFT · {active.supervisor}
                {' · '}{active.items?.length || 0} items · submitted {fmtTime(active.submitted_at)}
              </div>
            </div>
            <Btn onClick={() => { setView('list'); setActive(null) }}>← ALL REPORTS</Btn>
          </div>

          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5, marginBottom: 12,
          }}>AI REVIEW ENGINE</div>
          <ReviewPanel review={active.review} onRerun={rerunReview} rerunning={rerunning} />

          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5, margin: '22px 0 12px',
          }}>REPORTED ITEMS</div>
          {(active.items || []).map(i => (
            <div key={i.ref_id} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
              borderLeft: `3px solid ${SEV_COLOR[i.severity] || 'var(--text-dim)'}`,
              borderRadius: 3, padding: '10px 12px', marginBottom: 8,
            }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', marginBottom: 5 }}>
                {i.title}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.6 }}>
                <div><span style={{ color: 'var(--text-dim)' }}>ACTION: </span>{i.action_taken || '(none recorded)'}</div>
                {i.root_cause && <div><span style={{ color: 'var(--text-dim)' }}>CAUSE: </span>{i.root_cause}</div>}
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>STATUS: </span>
                  <span style={{ color: RESOLUTIONS.find(rz => rz.id === i.resolution)?.color || 'var(--text-muted)' }}>
                    {String(i.resolution || 'unknown').toUpperCase()}
                  </span>
                </div>
              </div>
            </div>
          ))}

          {active.notes && (
            <div style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
              borderRadius: 3, padding: '10px 12px', marginTop: 8,
              fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.6,
            }}>
              <span style={{ color: 'var(--text-dim)', letterSpacing: 0.8 }}>SHIFT NOTES: </span>{active.notes}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
