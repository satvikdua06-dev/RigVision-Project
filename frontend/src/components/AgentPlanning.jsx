import { useState, useEffect } from 'react'
import { ChevronDown, ChevronRight, Check, AlertTriangle } from 'lucide-react'

const STATUS_COLORS = {
  success: { ring: 'var(--accent-green)',  bg: 'rgba(70,177,127,0.12)',  text: 'var(--accent-green)'  },
  active:  { ring: 'var(--accent-cobalt)', bg: 'rgba(91,141,239,0.12)', text: 'var(--accent-cobalt)' },
  error:   { ring: 'var(--accent-red)',    bg: 'rgba(224,96,84,0.12)',  text: 'var(--accent-red)'    },
  pending: { ring: 'var(--border-solid)',  bg: 'transparent',            text: 'var(--text-dim)'     },
}

/**
 * AgentPlanning — collapsible pipeline accordion for the AI Diagnostics hub.
 *
 * Props
 *   title   string          Header label
 *   steps   PlanStep[]      Array of step objects:
 *             id              string   unique key
 *             title           string   display label
 *             detail          string?  sub-label (monospace hint)
 *             status          'pending' | 'active' | 'success' | 'error'
 *             content         ReactNode?  expandable body
 *             defaultExpanded boolean?    auto-open when true (reactive)
 *             duration        string?     e.g. "1.2s"
 *             icon            ReactNode?  icon shown when pending (fallback to dot)
 */
export function AgentPlanning({ title = 'Diagnosis Pipeline', steps = [] }) {
  const [isMainExpanded, setIsMainExpanded] = useState(true)
  const [expandedSteps, setExpandedSteps] = useState(() =>
    steps.reduce((acc, s) => ({ ...acc, [s.id]: s.defaultExpanded || false }), {})
  )

  // When a step gains defaultExpanded:true (data arrives), auto-open it.
  useEffect(() => {
    setExpandedSteps(prev => {
      let changed = false
      const next = { ...prev }
      steps.forEach(s => {
        if (s.defaultExpanded && !prev[s.id]) { next[s.id] = true; changed = true }
      })
      return changed ? next : prev
    })
  }, [steps])

  const toggleStep = (id, e) => {
    e.stopPropagation()
    setExpandedSteps(prev => ({ ...prev, [id]: !prev[id] }))
  }

  const hasActive  = steps.some(s => s.status === 'active')
  const hasError   = steps.some(s => s.status === 'error')
  const allSuccess = steps.length > 0 && steps.every(s => s.status === 'success')

  return (
    <div style={{ width: '100%', fontFamily: 'var(--font-ui)' }}>
      <div style={{
        background: 'var(--bg-card)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', overflow: 'hidden', boxShadow: 'var(--shadow-card)',
      }}>

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div
          onClick={() => setIsMainExpanded(v => !v)}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px', cursor: 'pointer', userSelect: 'none',
            borderBottom: isMainExpanded ? '1px solid var(--border)' : 'none',
            background: isMainExpanded ? 'rgba(255,255,255,0.015)' : 'transparent',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
              letterSpacing: 1.5, textTransform: 'uppercase', color: 'var(--text-muted)',
            }}>
              {title}
            </span>
            {hasActive && (
              <span className="lp" style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-cobalt)', letterSpacing: 1 }}>
                ● LIVE
              </span>
            )}
            {hasError && !hasActive && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-red)', letterSpacing: 1 }}>
                ● ERROR
              </span>
            )}
            {allSuccess && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-green)', letterSpacing: 1 }}>
                ● DONE
              </span>
            )}
          </div>
          <span style={{ color: 'var(--text-dim)', display: 'flex' }}>
            {isMainExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </span>
        </div>

        {/* ── Timeline ───────────────────────────────────────────────────── */}
        {isMainExpanded && (
          <div style={{ padding: '16px 16px 4px' }}>
            {steps.map((step, index) => {
              const isLast    = index === steps.length - 1
              const isExpanded = expandedSteps[step.id]
              const colors    = STATUS_COLORS[step.status] || STATUS_COLORS.pending

              return (
                <div
                  key={step.id}
                  style={{
                    position: 'relative', display: 'flex', gap: 12,
                    opacity: step.status === 'pending' ? 0.42 : 1,
                    transition: 'opacity 0.35s',
                    animation: 'step-fade-in 0.3s ease both',
                    animationDelay: `${index * 0.07}s`,
                  }}
                >
                  {/* Connector line — gradient fill lights up green as steps complete */}
                  {!isLast && (
                    <div style={{
                      position: 'absolute', left: 10, top: 26, bottom: -10, width: 2,
                      background: step.status === 'success'
                        ? 'linear-gradient(to bottom, rgba(70,177,127,0.55), rgba(70,177,127,0.2))'
                        : 'var(--border-solid)',
                      zIndex: 0, transition: 'background 0.7s ease',
                    }} />
                  )}

                  {/* Status bullet */}
                  <div style={{ flexShrink: 0, zIndex: 1, width: 22, height: 22, marginTop: 2 }}>
                    <div style={{
                      width: 22, height: 22, borderRadius: '50%',
                      border: `2px solid ${colors.ring}`,
                      background: colors.bg,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      boxShadow: `0 0 0 3px var(--bg-card)`,
                      transition: 'border-color 0.35s, background 0.35s',
                    }}>
                      {step.status === 'success' && (
                        <Check size={11} color="var(--accent-green)" strokeWidth={3} />
                      )}
                      {step.status === 'active' && (
                        <div className="spin" style={{
                          width: 9, height: 9, borderRadius: '50%',
                          border: '2px solid var(--accent-cobalt)', borderTopColor: 'transparent',
                        }} />
                      )}
                      {step.status === 'error' && (
                        <AlertTriangle size={10} color="var(--accent-red)" />
                      )}
                      {step.status === 'pending' && (
                        step.icon
                          ? <span style={{ display: 'flex', color: 'var(--text-dim)' }}>{step.icon}</span>
                          : <div style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--text-dim)' }} />
                      )}
                    </div>
                  </div>

                  {/* Step body */}
                  <div style={{ flex: 1, paddingBottom: isLast ? 12 : 20 }}>
                    {/* Title row */}
                    <div
                      onClick={e => step.content && toggleStep(step.id, e)}
                      style={{
                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        padding: '1px 6px', margin: '0 -6px', borderRadius: 4,
                        cursor: step.content ? 'pointer' : 'default',
                      }}
                    >
                      <span className={step.status === 'active' ? 'lp' : ''} style={{
                        fontFamily: 'var(--font-ui)', fontSize: 13.5, fontWeight: 600,
                        color: step.status === 'active'  ? 'var(--text-primary)'
                             : step.status === 'error'   ? 'var(--accent-red)'
                             : step.status === 'pending' ? 'var(--text-dim)'
                             : 'var(--text-muted)',
                      }}>
                        {step.title}{step.status === 'active' ? '…' : ''}
                      </span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {step.duration && (
                          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-dim)' }}>
                            {step.duration}
                          </span>
                        )}
                        {step.content && (
                          <span style={{ color: 'var(--text-dim)', display: 'flex' }}>
                            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Sub-detail hint */}
                    {step.detail && (
                      <div style={{
                        fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)',
                        marginTop: 2, lineHeight: 1.4,
                      }}>
                        {step.detail}
                      </div>
                    )}

                    {/* Expandable content */}
                    {step.content && isExpanded && (
                      <div style={{ marginTop: 10 }}>
                        {step.content}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default AgentPlanning
