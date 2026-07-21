/**
 * CodeLegendPanel — reference list of every R-code (compound risk rule) and
 * C-code (compliance violation) currently defined in the backend.
 *
 * Pulled from GET /api/code-legend, which reads risk_engine.rules.RULE_REGISTRY
 * and compliance_audit.get_code_registry() directly — this list can't drift
 * from what actually fires, because it's read from the same source.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../utils/api.js'

const host     = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

const SEV_COLOR = {
  CRITICAL: 'var(--accent-red)',
  HIGH:     'var(--accent-amber)',
  MEDIUM:   'var(--accent-cobalt)',
}
function sevColor(sev) {
  const key = Object.keys(SEV_COLOR).find(k => String(sev).toUpperCase().includes(k))
  return SEV_COLOR[key] || 'var(--text-dim)'
}

function CodeCard({ code, severity, title, subtitle, trigger }) {
  const color = sevColor(severity)
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
      borderLeft: `3px solid ${color}`, borderRadius: 3,
      padding: '11px 13px', marginBottom: 8,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: 5 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {code}
          </span>
          <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {title}
          </span>
        </div>
        <span style={{
          fontSize: 8, fontWeight: 700, color, letterSpacing: 1, whiteSpace: 'nowrap',
          border: `1px solid ${color}40`, background: `${color}14`,
          padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
        }}>{severity}</span>
      </div>
      {subtitle && (
        <div style={{ fontSize: 9, color: 'var(--accent-cobalt)', fontFamily: 'var(--font-mono)', marginBottom: 5, letterSpacing: 0.5 }}>
          {subtitle}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.6 }}>
        {trigger}
      </div>
    </div>
  )
}

export default function CodeLegendPanel() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const fetchLegend = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const res = await fetch(`${API_BASE}/code-legend`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchLegend() }, [fetchLegend])

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>LOADING CODE LEGEND…</div>
  if (error)   return <div style={{ padding: 20, color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{error}</div>

  const rules = data?.risk_rules || []
  const codes = data?.compliance_codes || []

  return (
    <div>
      <div style={{
        fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)',
        lineHeight: 1.7, marginBottom: 20, maxWidth: 720,
      }}>
        Two independent code systems. <strong style={{ color: 'var(--text-muted)' }}>R-codes</strong> are compound risk
        rules — they need a combination of conditions (a sensor reading plus a permit, maintenance job,
        or PPE state) and drive the live RISK tab and incident log.{' '}
        <strong style={{ color: 'var(--text-muted)' }}>C-codes</strong> are compliance violations — deterministic
        single-condition checks against OISD/DGMS/Factory Act clauses that drive the audit score.
        The same underlying hazard (e.g. gas over a hot-work limit) can appear as both an R-code and a C-code —
        one is the live alert, the other is the regulatory record.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5, marginBottom: 4,
          }}>R-CODES — COMPOUND RISK RULES</div>
          <div style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: 12 }}>
            {rules.length} rule{rules.length !== 1 ? 's' : ''} · risk_engine/rules.py
          </div>
          {rules.map(r => (
            <CodeCard
              key={r.code}
              code={r.code} severity={r.severity} title={r.title}
              subtitle={r.regulation} trigger={r.trigger}
            />
          ))}
        </div>

        <div>
          <div style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
            letterSpacing: 0.5, marginBottom: 4,
          }}>C-CODES — COMPLIANCE VIOLATIONS</div>
          <div style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginBottom: 12 }}>
            {codes.length} code{codes.length !== 1 ? 's' : ''} · knowledge/agent_layer/compliance_audit.py
          </div>
          {codes.map(c => (
            <CodeCard
              key={c.code}
              code={c.code} severity={c.severity} title={c.title}
              subtitle={c.standard} trigger={c.trigger}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
