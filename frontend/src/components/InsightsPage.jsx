/**
 * InsightsPage — full-page view for:
 *   • Pattern Intelligence (RAG-powered incident/near-miss pattern mining)
 *   • Quality & Compliance Audit (real-time OISD/DGMS compliance scoring)
 *
 * Route: /insights (protected)
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../utils/api.js'
import DailyReportPanel from './DailyReportPanel.jsx'
import CodeLegendPanel from './CodeLegendPanel.jsx'

const host     = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

const SEV_STYLE = {
  CRITICAL: { color: 'var(--accent-red)',    bg: 'rgba(224,96,84,0.12)',  border: 'var(--accent-red)'   },
  HIGH:     { color: 'var(--accent-amber)',  bg: 'rgba(217,166,78,0.12)', border: 'var(--accent-amber)' },
  MEDIUM:   { color: 'var(--accent-cobalt)', bg: 'rgba(91,141,239,0.10)', border: 'var(--accent-cobalt)'},
}

function ScoreGauge({ score }) {
  if (score == null) return null
  const color = score >= 80 ? 'var(--accent-green)' : score >= 50 ? 'var(--accent-amber)' : 'var(--accent-red)'
  const r = 40, cx = 56, cy = 56
  const circ = 2 * Math.PI * r
  const dash = (score / 100) * circ
  return (
    <svg width={112} height={112} style={{ display: 'block' }}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--bg-deep)" strokeWidth={8} />
      <circle cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth={8}
        strokeDasharray={`${dash} ${circ}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: 'stroke-dasharray 0.6s ease' }}
      />
      <text x={cx} y={cy - 6} textAnchor="middle" fontSize={22} fontWeight="700"
        fill={color} fontFamily="monospace">{score}</text>
      <text x={cx} y={cy + 10} textAnchor="middle" fontSize={9}
        fill="rgba(150,165,185,0.7)" fontFamily="monospace">/ 100</text>
      <text x={cx} y={cy + 22} textAnchor="middle" fontSize={8}
        fill="rgba(150,165,185,0.5)" fontFamily="monospace" letterSpacing={1}>COMPLIANT</text>
    </svg>
  )
}

function SectionHeader({ title, subtitle, badge, badgeColor }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: 0.5, fontFamily: 'var(--font-mono)' }}>
          {title}
        </span>
        {badge != null && (
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: 1,
            color: badgeColor || 'var(--accent-cobalt)',
            border: `1px solid ${badgeColor || 'var(--accent-cobalt)'}40`,
            background: `${badgeColor || 'var(--accent-cobalt)'}14`,
            padding: '1px 6px', borderRadius: 2,
          }}>{badge}</span>
        )}
      </div>
      {subtitle && (
        <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', marginTop: 3, letterSpacing: 0.3 }}>
          {subtitle}
        </div>
      )}
    </div>
  )
}

/** Renders `**bold**` and `` `code` `` spans inside a line of markdown. */
function InlineMarkdown({ text }) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i} style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{part.slice(2, -2)}</strong>
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={i} style={{
          background: 'var(--bg-deep)', border: '1px solid var(--border-solid)',
          borderRadius: 2, padding: '0 4px', fontSize: '0.95em',
        }}>{part.slice(1, -1)}</code>
      )
    }
    return part
  })
}

function MarkdownText({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.7, color: 'var(--text-muted)' }}>
      {lines.map((line, i) => {
        // Strip blockquote markers the model sometimes emits around list items
        const trimmed = line.trim().replace(/^>\s?/, '')
        if (!trimmed) return <div key={i} style={{ height: 8 }} />

        // Headings: #, ##, ###, #### — size steps down as depth increases
        const h = trimmed.match(/^(#{1,6})\s+(.*)$/)
        if (h) {
          const depth = h[1].length
          const content = h[2].replace(/\*\*/g, '').trim()
          const top = depth <= 2
          return (
            <div key={i} style={{
              fontSize: top ? 12 : 11,
              fontWeight: 700,
              color: top ? 'var(--text-primary)' : 'var(--accent-cobalt)',
              letterSpacing: 0.8,
              marginTop: top ? 16 : 12, marginBottom: 5,
              borderBottom: top ? '1px solid var(--border-solid)' : 'none',
              paddingBottom: top ? 3 : 0,
            }}>{content.toUpperCase()}</div>
          )
        }

        // A line that is entirely bold acts as a sub-heading
        if (/^\*\*[^*]+\*\*:?$/.test(trimmed)) {
          return (
            <div key={i} style={{ fontWeight: 700, color: 'var(--text-primary)', marginTop: 8, marginBottom: 2 }}>
              {trimmed.replace(/\*\*/g, '')}
            </div>
          )
        }

        // Bullets and numbered items
        if (/^\d+[.)]\s/.test(trimmed) || /^[-*+]\s/.test(trimmed)) {
          const content = trimmed.replace(/^(\d+[.)]|[-*+])\s*/, '')
          const marker  = (trimmed.match(/^(\d+)[.)]/) || [])[1]
          return (
            <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3 }}>
              <span style={{ color: 'var(--accent-cobalt)', flexShrink: 0, minWidth: marker ? 14 : 8 }}>
                {marker ? `${marker}.` : '›'}
              </span>
              <span><InlineMarkdown text={content} /></span>
            </div>
          )
        }

        // Horizontal rule
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
          return <div key={i} style={{ borderTop: '1px solid var(--border-solid)', margin: '10px 0' }} />
        }

        return <div key={i}><InlineMarkdown text={trimmed} /></div>
      })}
    </div>
  )
}

/** Shared action button for the insight tabs. */
function ActionBtn({ children, onClick, disabled, primary }) {
  const color = primary ? 'var(--accent-cobalt)' : 'var(--text-muted)'
  return (
    <button onClick={onClick} disabled={disabled} style={{
      padding: '6px 14px',
      border: `1px solid ${disabled ? 'var(--border-solid)' : primary ? color : 'var(--border-bright)'}`,
      borderRadius: 3,
      background: primary && !disabled ? 'rgba(91,141,239,0.12)' : 'transparent',
      color: disabled ? 'var(--text-dim)' : color,
      fontFamily: 'var(--font-mono)', fontSize: 10, cursor: disabled ? 'not-allowed' : 'pointer',
      letterSpacing: 0.8, opacity: disabled ? 0.5 : 1, whiteSpace: 'nowrap',
    }}>{children}</button>
  )
}

/** Shown when a report has never been generated yet. */
function EmptyInsight({ title, blurb, onGenerate, generating }) {
  return (
    <div style={{
      padding: '48px 30px', textAlign: 'center',
      border: '1px dashed var(--border-solid)', borderRadius: 6,
    }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', letterSpacing: 0.8, marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', lineHeight: 1.7, marginBottom: 18, maxWidth: 460, marginLeft: 'auto', marginRight: 'auto' }}>
        {blurb}
      </div>
      <ActionBtn primary onClick={onGenerate} disabled={generating}>
        {generating ? 'GENERATING — THIS TAKES ~30s…' : 'GENERATE NOW'}
      </ActionBtn>
    </div>
  )
}

function ComplianceTab({ data, loading, error, onRefresh, onGenerate, generating }) {
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>LOADING AUDIT DATA…</div>
  if (error)   return <div style={{ padding: 20, color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{error}</div>
  if (!data || data.status === 'pending') return (
    <EmptyInsight
      title="NO COMPLIANCE AUDIT ON RECORD"
      blurb="The audit checks live rig state against OISD, DGMS and Factory Act clauses, scores compliance out of 100, and drafts a corrective action workflow. It runs automatically every 5 minutes — or generate one now."
      onGenerate={onGenerate}
      generating={generating}
    />
  )

  const violations = data.violations || []
  const critical = violations.filter(v => v.severity === 'CRITICAL')
  const high     = violations.filter(v => v.severity === 'HIGH')
  const medium   = violations.filter(v => v.severity === 'MEDIUM')

  return (
    <div>
      {/* Score + summary row */}
      <div style={{
        display: 'flex', gap: 24, alignItems: 'center',
        background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
        borderRadius: 6, padding: '16px 20px', marginBottom: 20,
      }}>
        <ScoreGauge score={data.compliance_score} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', letterSpacing: 1, marginBottom: 12 }}>
            COMPLIANCE SCORE — LAST AUDIT {data.generated_at ? new Date(data.generated_at * 1000).toLocaleTimeString() : '—'}
          </div>
          <div style={{ display: 'flex', gap: 12 }}>
            {[
              { label: 'CRITICAL', count: critical.length, color: 'var(--accent-red)'    },
              { label: 'HIGH',     count: high.length,     color: 'var(--accent-amber)'  },
              { label: 'MEDIUM',   count: medium.length,   color: 'var(--accent-cobalt)' },
            ].map(item => (
              <div key={item.label} style={{
                background: 'var(--bg-deep)', border: '1px solid var(--border-solid)',
                borderRadius: 4, padding: '8px 14px', textAlign: 'center', minWidth: 64,
              }}>
                <div style={{ fontSize: 20, fontWeight: 700, color: item.color, fontFamily: 'var(--font-mono)', lineHeight: 1 }}>
                  {item.count}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', letterSpacing: 1, marginTop: 3 }}>
                  {item.label}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <ActionBtn primary onClick={onGenerate} disabled={generating}>
            {generating ? 'RUNNING AUDIT…' : 'RUN NEW AUDIT'}
          </ActionBtn>
          <ActionBtn onClick={onRefresh}>REFRESH</ActionBtn>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* Violations list */}
        <div>
          <SectionHeader title="ACTIVE VIOLATIONS" subtitle={`${violations.length} deviation${violations.length !== 1 ? 's' : ''} from OISD/DGMS/Factory Act standards`} />
          {violations.length === 0 ? (
            <div style={{
              padding: 20, textAlign: 'center', color: 'var(--accent-green)',
              fontFamily: 'var(--font-mono)', fontSize: 11, border: '1px solid var(--accent-green)',
              borderRadius: 4, background: 'rgba(70,177,127,0.08)',
            }}>ALL PARAMETERS WITHIN COMPLIANCE THRESHOLDS</div>
          ) : (
            violations.map(v => {
              const s = SEV_STYLE[v.severity] || SEV_STYLE.MEDIUM
              return (
                <div key={v.code} style={{
                  background: s.bg, border: `1px solid ${s.border}40`,
                  borderLeft: `3px solid ${s.border}`,
                  borderRadius: 3, padding: '10px 12px', marginBottom: 8,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 5 }}>
                    <div>
                      <span style={{ fontSize: 9, fontWeight: 700, color: s.color, letterSpacing: 1, fontFamily: 'var(--font-mono)' }}>
                        [{v.code}] {v.standard} {v.clause}
                      </span>
                    </div>
                    <span style={{
                      fontSize: 9, fontWeight: 700, color: s.color,
                      border: `1px solid ${s.border}40`, padding: '1px 5px', borderRadius: 2,
                      fontFamily: 'var(--font-mono)', letterSpacing: 1,
                    }}>{v.severity}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 5, lineHeight: 1.5, fontFamily: 'var(--font-mono)' }}>
                    {v.description}
                  </div>
                  {(v.current_value || v.threshold) && (
                    <div style={{ display: 'flex', gap: 16, fontSize: 9, fontFamily: 'var(--font-mono)', marginBottom: 5 }}>
                      {v.current_value && <span><span style={{ color: 'var(--text-dim)' }}>NOW </span><span style={{ color: s.color }}>{v.current_value}</span></span>}
                      {v.threshold     && <span><span style={{ color: 'var(--text-dim)' }}>LIMIT </span><span style={{ color: 'var(--text-primary)' }}>{v.threshold}</span></span>}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontStyle: 'italic', lineHeight: 1.5 }}>
                    → {v.corrective_action}
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Corrective workflow */}
        <div>
          <SectionHeader title="CORRECTIVE ACTION WORKFLOW" subtitle="AI-generated priority sequence — local LLM + OISD/DGMS context" />
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderRadius: 4, padding: '14px 16px',
          }}>
            {data.status === 'generating'
              ? <div style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  GENERATING WORKFLOW NARRATIVE…
                </div>
              : <MarkdownText text={data.corrective_workflow} />}
          </div>
        </div>
      </div>
    </div>
  )
}

function PatternTab({ data, nearMisses, loading, error, onRefresh, onGenerate, generating }) {
  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>LOADING PATTERN INTELLIGENCE…</div>
  if (error)   return <div style={{ padding: 20, color: 'var(--accent-red)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{error}</div>
  if (!data || data.status === 'pending') return (
    <EmptyInsight
      title="NO PATTERN REPORT ON RECORD"
      blurb="Pattern intelligence mines confirmed incidents and the near-miss log against OISD/DGMS clauses to surface recurring combinations that single-sensor thresholds miss. It runs automatically every 10 minutes — or generate one now."
      onGenerate={onGenerate}
      generating={generating}
    />
  )

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20 }}>
      {/* Main analysis */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18 }}>
          <SectionHeader
            title="PATTERN INTELLIGENCE REPORT"
            subtitle={`${data.incidents_analyzed} incidents + ${data.near_misses_analyzed} near-misses · Generated ${data.generated_at ? new Date(data.generated_at * 1000).toLocaleString() : '—'}`}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <ActionBtn primary onClick={onGenerate} disabled={generating}>
              {generating ? 'ANALYSING…' : 'RE-ANALYSE'}
            </ActionBtn>
            <ActionBtn onClick={onRefresh}>REFRESH</ActionBtn>
          </div>
        </div>
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
          borderRadius: 4, padding: '16px 18px',
        }}>
          <MarkdownText text={data.analysis} />
        </div>
      </div>

      {/* Near-miss sidebar */}
      <div>
        <SectionHeader title="NEAR-MISS LOG" subtitle={`${nearMisses.length} reports on file`} />
        {nearMisses.map(nm => (
          <div key={nm.id} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderLeft: '3px solid var(--accent-amber)',
            borderRadius: 3, padding: '9px 11px', marginBottom: 8,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent-amber)', fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>
                {nm.id}
              </span>
              <span style={{ fontSize: 9, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>{nm.date}</span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: 5, lineHeight: 1.5 }}>
              {nm.description.slice(0, 120)}{nm.description.length > 120 ? '…' : ''}
            </div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              {(nm.regulatory_refs || []).map(ref => (
                <span key={ref} style={{
                  fontSize: 8, color: 'var(--accent-cobalt)',
                  border: '1px solid var(--accent-cobalt)30',
                  padding: '1px 4px', borderRadius: 2, fontFamily: 'var(--font-mono)',
                }}>{ref}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function InsightsPage() {
  const [tab, setTab] = useState('reports')

  const [auditData,     setAuditData]     = useState(null)
  const [auditLoading,  setAuditLoading]  = useState(false)
  const [auditError,    setAuditError]    = useState(null)

  const [patternData,   setPatternData]   = useState(null)
  const [patternLoading, setPatternLoading] = useState(false)
  const [patternError,  setPatternError]  = useState(null)

  const [nearMisses,    setNearMisses]    = useState([])

  const [auditGenerating,   setAuditGenerating]   = useState(false)
  const [patternGenerating, setPatternGenerating] = useState(false)

  const fetchAudit = useCallback(async () => {
    setAuditLoading(true); setAuditError(null)
    try {
      const res = await fetch(`${API_BASE}/compliance-audit`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAuditData(await res.json())
    } catch (e) { setAuditError(e.message) }
    finally { setAuditLoading(false) }
  }, [])

  const fetchPattern = useCallback(async () => {
    setPatternLoading(true); setPatternError(null)
    try {
      const [patRes, nmRes] = await Promise.all([
        fetch(`${API_BASE}/pattern-intelligence`, { headers: authHeaders() }),
        fetch(`${API_BASE}/near-misses`,          { headers: authHeaders() }),
      ])
      if (!patRes.ok) throw new Error(`HTTP ${patRes.status}`)
      setPatternData(await patRes.json())
      if (nmRes.ok) setNearMisses(await nmRes.json())
    } catch (e) { setPatternError(e.message) }
    finally { setPatternLoading(false) }
  }, [])

  // Force a fresh audit/pattern pass. These block on a local LLM call, so the
  // request can take ~30s — the button stays disabled until it returns.
  const generateAudit = useCallback(async () => {
    setAuditGenerating(true); setAuditError(null)
    try {
      const res = await fetch(`${API_BASE}/compliance-audit/generate`, {
        method: 'POST', headers: authHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAuditData(await res.json())
    } catch (e) { setAuditError(`Generation failed: ${e.message}`) }
    finally { setAuditGenerating(false) }
  }, [])

  const generatePattern = useCallback(async () => {
    setPatternGenerating(true); setPatternError(null)
    try {
      const res = await fetch(`${API_BASE}/pattern-intelligence/generate`, {
        method: 'POST', headers: authHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setPatternData(await res.json())
    } catch (e) { setPatternError(`Generation failed: ${e.message}`) }
    finally { setPatternGenerating(false) }
  }, [])

  useEffect(() => {
    fetchAudit()
    fetchPattern()
  }, [fetchAudit, fetchPattern])

  const TABS = [
    { id: 'reports',    label: 'DAILY REPORTS',          badge: null },
    { id: 'compliance', label: 'COMPLIANCE AUDIT',       badge: auditData?.critical_count > 0 ? `${auditData.critical_count} CRITICAL` : null, badgeColor: 'var(--accent-red)' },
    { id: 'patterns',   label: 'INCIDENT PATTERN INTEL', badge: null },
    { id: 'legend',     label: 'CODE LEGEND',            badge: null },
  ]

  return (
    <div style={{
      height: '100vh',
      background: 'var(--bg-deep)',
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Page header */}
      <div style={{
        padding: '16px 28px 0',
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border-solid)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14 }}>
          <a href="/" style={{
            color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11,
            textDecoration: 'none', letterSpacing: 0.5,
          }}>← DASHBOARD</a>
          <div style={{ width: 1, height: 16, background: 'var(--border-solid)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: 0.5 }}>
            SAFETY INSIGHTS HUB
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', letterSpacing: 2 }}>
            OISD · DGMS · FACTORY ACT
          </span>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', gap: 0 }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: '9px 20px',
                border: 'none', borderBottom: `2px solid ${tab === t.id ? 'var(--accent-cobalt)' : 'transparent'}`,
                marginBottom: -1,
                cursor: 'pointer', background: 'transparent',
                fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
                color: tab === t.id ? 'var(--text-primary)' : 'var(--text-dim)',
                letterSpacing: 0.8,
                display: 'flex', alignItems: 'center', gap: 8,
              }}
            >
              {t.label}
              {t.badge && (
                <span style={{
                  fontSize: 8, fontWeight: 700,
                  color: t.badgeColor,
                  border: `1px solid ${t.badgeColor}40`,
                  background: `${t.badgeColor}14`,
                  padding: '1px 5px', borderRadius: 2,
                }}>{t.badge}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Content — minHeight:0 is required for a flex child to actually respect
          overflow:auto rather than growing past its parent and getting clipped
          by the app's global `overflow:hidden` on html/body/#root. */}
      <div style={{ flex: 1, minHeight: 0, padding: '24px 28px', overflowY: 'auto', overflowX: 'auto' }}>
        {tab === 'reports' && <DailyReportPanel />}
        {tab === 'compliance' && (
          <ComplianceTab
            data={auditData} loading={auditLoading} error={auditError}
            onRefresh={fetchAudit}
            onGenerate={generateAudit} generating={auditGenerating}
          />
        )}
        {tab === 'patterns' && (
          <PatternTab
            data={patternData} nearMisses={nearMisses}
            loading={patternLoading} error={patternError}
            onRefresh={fetchPattern}
            onGenerate={generatePattern} generating={patternGenerating}
          />
        )}
        {tab === 'legend' && (
          <CodeLegendPanel />
        )}
      </div>
    </div>
  )
}
