import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'
import { ProofLightbox, ppeChipStyle, personPpeItems, ppeHasAlert } from './PPEPanel.jsx'
import StatusBadge from './ui/StatusBadge.jsx'
import CircularGauge from './ui/CircularGauge.jsx'
import PermitPanel from './PermitPanel.jsx'

const STATUS_COLOR = {
  normal:   'var(--accent-green)',
  warning:  'var(--accent-amber)',
  critical: 'var(--accent-red)',
}

const SENSOR_LABELS = {
  temperature: 'TEMP',
  gas_h2s:     'H₂S',
  vibration:   'VIB',
  noise:       'NOISE',
  pressure:    'PRES',
}

// Vertical tick on the progress bar marking a threshold boundary.
function ThresholdTick({ pct, color }) {
  return (
    <div style={{
      position: 'absolute',
      left: `${pct}%`,
      top: 0,
      bottom: 0,
      width: 1,
      background: color,
      opacity: 0.55,
      pointerEvents: 'none',
    }} />
  )
}

// Compact horizontal bar for trend-style metrics (NOISE, PRES, VIB).
function TrendBar({ label, value, meta }) {
  const known = value != null && !Number.isNaN(Number(value))
  const { min = 0, max = 100, warning, critical, warning_low, critical_low, unit = '' } = meta || {}

  const num = known ? Number(value) : 0
  const pct = Math.max(0, Math.min(100, ((num - min) / ((max - min) || 1)) * 100))

  const isHighCrit = critical     != null && num >= critical
  const isHighWarn = warning      != null && num >= warning
  const isLowCrit  = critical_low != null && num <= critical_low
  const isLowWarn  = warning_low  != null && num <= warning_low

  const color = !known
    ? 'var(--text-dim)'
    : (isHighCrit || isLowCrit) ? 'var(--accent-red)'
    : (isHighWarn || isLowWarn) ? 'var(--accent-amber)'
    : 'var(--accent-green)'

  const toPct = v => v != null ? Math.max(0, Math.min(100, ((v - min) / ((max - min) || 1)) * 100)) : null
  const warnPct  = toPct(warning)
  const critPct  = toPct(critical)
  const warnLPct = toPct(warning_low)
  const critLPct = toPct(critical_low)

  const valStr = known ? `${value}${unit ? ' ' + unit : ''}` : '—'

  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)',
          width: 36, flexShrink: 0, letterSpacing: 0.4, lineHeight: 1,
        }}>{label}</span>
        <div style={{
          flex: 1, height: 4, background: 'var(--bg-deep)',
          border: '1px solid var(--border-solid)', position: 'relative', overflow: 'hidden',
        }}>
          <div style={{ height: '100%', width: `${pct}%`, background: color, transition: 'width 0.4s ease' }} />
          {warnLPct != null && <ThresholdTick pct={warnLPct} color="var(--accent-amber)" />}
          {critLPct != null && <ThresholdTick pct={critLPct} color="var(--accent-red)" />}
          {warnPct  != null && <ThresholdTick pct={warnPct}  color="var(--accent-amber)" />}
          {critPct  != null && <ThresholdTick pct={critPct}  color="var(--accent-red)" />}
        </div>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, color,
          textAlign: 'right', flexShrink: 0, fontVariantNumeric: 'tabular-nums',
          minWidth: 48, lineHeight: 1, fontWeight: 600,
        }}>{valStr}</span>
      </div>
    </div>
  )
}

function SensorBar({ label, value, meta }) {
  const known = value != null && !Number.isNaN(value)
  const { min = 0, max = 100, warning, critical, warning_low, critical_low, unit = '', threshold_source } = meta || {}

  const pct = known ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0

  const isHighCrit = critical     != null && value >= critical
  const isHighWarn = warning      != null && value >= warning
  const isLowCrit  = critical_low != null && value <= critical_low
  const isLowWarn  = warning_low  != null && value <= warning_low

  const color = !known
    ? 'var(--text-dim)'
    : (isHighCrit || isLowCrit) ? 'var(--accent-red)'
    : (isHighWarn || isLowWarn) ? 'var(--accent-amber)'
    : 'var(--accent-green)'

  const level = threshold_source?.level
  const srcTag = level === 'device_manual' ? ' [M]' : level === 'zone_environmental' ? ' [E]' : ''
  const srcColor = level === 'device_manual' ? 'var(--accent-cobalt)' : 'var(--text-dim)'

  const toPct = v => v != null ? Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100)) : null
  const warnPct  = toPct(warning)
  const critPct  = toPct(critical)
  const warnLPct = toPct(warning_low)
  const critLPct = toPct(critical_low)

  const tooltipParts = []
  if (warning_low  != null) tooltipParts.push(`WARN LOW ≤${warning_low}`)
  if (critical_low != null) tooltipParts.push(`CRIT LOW ≤${critical_low}`)
  if (warning      != null) tooltipParts.push(`WARN ≥${warning}`)
  if (critical     != null) tooltipParts.push(`CRIT ≥${critical}`)

  return (
    <div style={{ marginBottom: 9 }} title={tooltipParts.join('  ') || undefined}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', marginBottom: 4,
        fontFamily: 'var(--font-mono)', fontSize: 11,
      }}>
        <span style={{ color: 'var(--text-muted)' }}>
          {label}
          {srcTag && (
            <span style={{ color: srcColor, marginLeft: 4 }}>{srcTag}</span>
          )}
        </span>
        <span style={{ color, fontVariantNumeric: 'tabular-nums' }}>
          {known ? `${value} ${unit}` : 'NO DATA'}
        </span>
      </div>
      <div style={{
        height: 5,
        background: 'var(--bg-deep)',
        border: '1px solid var(--border-solid)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: color,
          transition: 'width 0.4s ease',
        }} />
        {warnLPct != null && <ThresholdTick pct={warnLPct} color="var(--accent-amber)" />}
        {critLPct != null && <ThresholdTick pct={critLPct} color="var(--accent-red)" />}
        {warnPct  != null && <ThresholdTick pct={warnPct}  color="var(--accent-amber)" />}
        {critPct  != null && <ThresholdTick pct={critPct}  color="var(--accent-red)" />}
      </div>
    </div>
  )
}

const searchInputStyle = {
  width: '100%',
  padding: '7px 10px',
  background: 'var(--bg-deep)',
  border: '1px solid var(--border-solid)',
  borderRadius: 2,
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.15s',
}

function ZonesTab() {
  const [search, setSearch]   = useState('')
  const zones                 = useRigStore(s => s.zones)
  const selectZone            = useRigStore(s => s.selectZone)
  const selectedZone          = useRigStore(s => s.selectedZone)

  const filteredZones = Object.entries(zones).filter(([id, zone]) => {
    if (!search) return true
    const term  = search.toLowerCase()
    const label = (zone.label || id.replace(/_/g, ' ')).toLowerCase()
    return label.includes(term) || (zone.status || '').toLowerCase().includes(term)
  })

  return (
    <div>
      <div style={{ marginBottom: 10, position: 'relative' }}>
        <input
          type="text"
          placeholder="Filter zones…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={searchInputStyle}
          onFocus={(e) => e.target.style.borderColor = 'var(--border-bright)'}
          onBlur={(e)  => e.target.style.borderColor = 'var(--border-solid)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            aria-label="Clear filter"
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0,
            }}
          >\xd7</button>
        )}
      </div>

      {filteredZones.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'var(--text-dim)',
          fontFamily: 'var(--font-mono)', fontSize: 11, padding: 24,
        }}>NO ZONES FOUND</div>
      ) : (
        filteredZones.map(([id, zone]) => {
          const sc         = STATUS_COLOR[zone.status] || 'var(--text-dim)'
          const isSelected = selectedZone === id
          return (
            <div
              key={id}
              onClick={() => selectZone(id)}
              tabIndex={0}
              role="button"
              aria-pressed={isSelected}
              onKeyDown={(e) => e.key === 'Enter' && selectZone(id)}
              style={{
                background:  isSelected ? 'var(--bg-elev)' : 'var(--bg-card)',
                border:     `1px solid ${isSelected ? 'var(--border-bright)' : 'var(--border-solid)'}`,
                borderLeft: `3px solid ${sc}`,
                borderRadius: 2,
                padding: '12px 13px',
                marginBottom: 8,
                cursor: 'pointer',
                transition: 'background 0.12s, border-color 0.12s',
              }}
            >
              {/* Zone header — 8dp below (normalised spacing scale) */}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 8,
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 600,
                  color: 'var(--text-primary)', letterSpacing: 0.5,
                }}>
                  {(zone.label || id.replace(/_/g, ' ')).toUpperCase()}
                </span>
                <StatusBadge status={zone.status} />
              </div>

              {/* Sensor strip: alarm-style arcs (TEMP/H2S) left | trend bars (NOISE/PRES/VIB) right */}
              {(() => {
                const types      = zone.sensor_types || ['temperature', 'gas_h2s', 'vibration', 'noise', 'pressure']
                const meta       = zone.sensor_meta || {}
                const alarmTypes = types.filter(t => t === 'temperature' || t === 'gas_h2s')
                const trendTypes = types.filter(t => t === 'vibration' || t === 'noise' || t === 'pressure')
                return (
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
                    {/* Alarm gauges: compact arcs with threshold ticks */}
                    {alarmTypes.length > 0 && (
                      <div style={{ display: 'flex', gap: 12, flexShrink: 0 }}>
                        {alarmTypes.map(t => (
                          <CircularGauge key={t} size={58}
                            label={SENSOR_LABELS[t] || t.toUpperCase()}
                            value={zone[t]} meta={meta[t]} />
                        ))}
                      </div>
                    )}
                    {/* Divider */}
                    {alarmTypes.length > 0 && trendTypes.length > 0 && (
                      <div style={{ width: 1, alignSelf: 'stretch', background: 'var(--border-solid)', flexShrink: 0 }} />
                    )}
                    {/* Trend bars: inline bar + value */}
                    {trendTypes.length > 0 && (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 7, minWidth: 0 }}>
                        {trendTypes.map(t => (
                          <TrendBar key={t}
                            label={SENSOR_LABELS[t] || t.toUpperCase()}
                            value={zone[t]} meta={meta[t]} />
                        ))}
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* Occupancy + PPE row — badge chips matching StatusBadge visual weight */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginTop: 0, paddingTop: 6,
                borderTop: '1px solid var(--border)',
              }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4,
                  background: 'var(--bg-deep)', border: '1px solid var(--border-solid)',
                  borderRadius: 2, padding: '2px 7px',
                  fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)', letterSpacing: 0.4,
                }}>
                  PERS{' '}
                  <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>
                    {zone.person_count}
                  </span>
                </span>
                {zone.ppe_violations?.length > 0 ? (
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    border: '1px solid var(--accent-red)', borderRadius: 2, padding: '2px 7px',
                    fontFamily: 'var(--font-mono)', fontSize: 10,
                    color: 'var(--accent-red)', fontWeight: 600, letterSpacing: 0.5,
                    background: 'rgba(224,96,84,0.08)',
                  }}>
                    ● PPE {zone.ppe_violations.length} ALERT
                  </span>
                ) : (
                  <span style={{
                    display: 'inline-flex', alignItems: 'center',
                    border: '1px solid var(--border-solid)', borderRadius: 2, padding: '2px 7px',
                    fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)', letterSpacing: 0.4,
                  }}>
                    PPE OK
                  </span>
                )}
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}

function PersonsTab() {
  const [search, setSearch]   = useState('')
  const [proofItem, setProofItem] = useState(null)
  const persons               = useRigStore(s => s.persons)
  const selectPerson          = useRigStore(s => s.selectPerson)
  const selectedPerson        = useRigStore(s => s.selectedPerson)

  const filteredPersons = persons.filter(p => {
    if (!search) return true
    const term = search.toLowerCase()
    return (
      p.id.toString().includes(term) ||
      (p.name    && p.name.toLowerCase().includes(term)) ||
      (p.zone    && p.zone.toLowerCase().includes(term)) ||
      (p.posture && p.posture.toLowerCase().includes(term))
    )
  })

  return (
    <div>
      <div style={{ marginBottom: 10, position: 'relative' }}>
        <input
          type="text"
          placeholder="Filter by ID, zone, posture…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={searchInputStyle}
          onFocus={(e) => e.target.style.borderColor = 'var(--border-bright)'}
          onBlur={(e)  => e.target.style.borderColor = 'var(--border-solid)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            aria-label="Clear filter"
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0,
            }}
          >\xd7</button>
        )}
      </div>

      {filteredPersons.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'var(--text-dim)',
          fontFamily: 'var(--font-mono)', fontSize: 11, padding: 24,
        }}>NO PERSONNEL FOUND</div>
      ) : (
        filteredPersons.map((p, idx) => {
          const ppeItems    = personPpeItems(p.id, p.ppe)
          const hasAlert    = ppeHasAlert(p.ppe)
          const hasUnknown  = ppeItems.some(i => i.status == null || i.status === 'unknown')
          const isSelected  = selectedPerson === p.id
          const accentColor = isSelected         ? 'var(--accent-cobalt)'
                            : hasAlert           ? 'var(--accent-red)'
                            : 'var(--border-solid)'

          return (
            <div
              key={`${p.id}-${idx}`}
              onClick={() => selectPerson(p.id)}
              tabIndex={0}
              role="button"
              aria-pressed={isSelected}
              onKeyDown={(e) => e.key === 'Enter' && selectPerson(p.id)}
              style={{
                background:  isSelected ? 'var(--bg-elev)' : 'var(--bg-card)',
                border:     `1px solid ${isSelected ? 'var(--border-bright)' : 'var(--border-solid)'}`,
                borderLeft: `3px solid ${accentColor}`,
                borderRadius: 2,
                padding: '12px 13px',
                marginBottom: 8,
                cursor: 'pointer',
                transition: 'background 0.12s, border-color 0.12s',
              }}
            >
              {/* Person header */}
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                marginBottom: 10,
              }}>
                <span style={{
                  fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600,
                  color: 'var(--text-primary)', letterSpacing: 0.5,
                }}>
                  {p.name ? p.name : `PERS #${p.id}`}
                  {p.name && <span style={{ color: 'var(--text-dim)', fontWeight: 400, marginLeft: 5, fontSize: 10 }}>#{p.id}</span>}
                </span>
                {hasAlert ? (
                  <span style={{
                    border: '1px solid var(--accent-red)', color: 'var(--accent-red)',
                    fontFamily: 'var(--font-mono)', fontSize: 10,
                    padding: '2px 6px', borderRadius: 2, letterSpacing: 1, fontWeight: 600,
                  }}>PPE ALERT</span>
                ) : hasUnknown ? (
                  <span style={{
                    border: '1px solid var(--border-solid)', color: 'var(--text-dim)',
                    fontFamily: 'var(--font-mono)', fontSize: 10,
                    padding: '2px 6px', borderRadius: 2, letterSpacing: 1,
                  }}>UNMONITORED</span>
                ) : null}
              </div>

              {/* Telemetry grid */}
              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 8px',
                fontFamily: 'var(--font-mono)', fontSize: 11, marginBottom: 10,
              }}>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>ZONE  </span>
                  <span style={{ color: 'var(--accent-cobalt)' }}>
                    {p.zone.replace(/_/g, ' ').toUpperCase()}
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>POSTURE  </span>
                  <span style={{ color: 'var(--text-primary)' }}>{p.posture}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>CONF  </span>
                  <span style={{ color: 'var(--accent-green)', fontVariantNumeric: 'tabular-nums' }}>
                    {(p.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-dim)' }}>CAMS  </span>
                  <span style={{ color: 'var(--text-primary)' }}>{p.cameras_visible}</span>
                </div>
              </div>

              {/* PPE chips */}
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {ppeItems.map(({ key, label, status, proof }) => {
                  const { tone, mark } = ppeChipStyle(status)
                  const isMissing = status === 'missing'
                  return (
                    <span
                      key={key}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        padding: '3px 7px', borderRadius: 2,
                        fontSize: 10, fontFamily: 'var(--font-mono)',
                        background: 'var(--bg-deep)',
                        border: `1px solid ${tone}`,
                        color: tone, letterSpacing: 0.3,
                      }}
                    >
                      {label} {mark}
                      {isMissing && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setProofItem({ item: proof, since: Date.now() }) }}
                          aria-label={`View detection frame for ${label}`}
                          style={{
                            background: 'transparent',
                            border: `1px solid ${tone}`,
                            color: tone,
                            borderRadius: 2, fontSize: 9,
                            padding: '0 4px', cursor: 'pointer', letterSpacing: 0.5,
                          }}
                        >PROOF</button>
                      )}
                    </span>
                  )
                })}
              </div>
            </div>
          )
        })
      )}

      {proofItem && (
        <ProofLightbox
          item={proofItem.item}
          since={proofItem.since}
          onClose={() => setProofItem(null)}
        />
      )}
    </div>
  )
}

const SEV_TEXT_COLOR = {
  CRITICAL: 'var(--accent-red)',
  HIGH:     'var(--accent-amber)',
  WARNING:  'var(--accent-amber)',
  NORMAL:   'var(--accent-green)',
}

function CompoundRiskTab() {
  const compoundRisk = useRigStore(s => s.compoundRisk)

  if (!compoundRisk) return (
    <div style={{
      textAlign: 'center', color: 'var(--text-dim)',
      fontFamily: 'var(--font-mono)', fontSize: 11, padding: 24,
    }}>COMPOUND RISK ENGINE LOADING…</div>
  )

  const rules    = compoundRisk.rules_fired     || []
  const actions  = compoundRisk.immediate_actions || []
  const narrative = compoundRisk.narrative       || ''
  const severity  = compoundRisk.severity        || 'NORMAL'
  const sevColor  = SEV_TEXT_COLOR[severity]     || 'var(--accent-green)'

  return (
    <div>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        paddingBottom: 10, marginBottom: 12, borderBottom: '1px solid var(--border-solid)',
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)', letterSpacing: 1 }}>
          COMPOUND RISK ENGINE
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
          color: sevColor, border: `1px solid ${sevColor}40`,
          background: `${sevColor}18`, padding: '2px 8px', borderRadius: 2, letterSpacing: 1,
        }}>
          {severity} · {rules.length} RULE{rules.length !== 1 ? 'S' : ''}
        </span>
      </div>

      {/* Rule cards */}
      {rules.length === 0 ? (
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
          borderLeft: '3px solid var(--accent-green)', borderRadius: 2, padding: '12px 13px',
          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-green)',
        }}>
          ALL SYSTEMS NORMAL — No compound risks detected
        </div>
      ) : rules.map((rule, i) => {
        const rSev   = rule.severity || 'WARNING'
        const rColor = rSev === 'CRITICAL' ? 'var(--accent-red)' : 'var(--accent-amber)'
        return (
          <div key={rule.rule_id || i} style={{
            background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
            borderLeft: `3px solid ${rColor}`, borderRadius: 2, padding: '11px 13px', marginBottom: 8,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: 0.5 }}>
                {rule.rule_id}
              </span>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700,
                color: rColor, border: `1px solid ${rColor}40`, background: `${rColor}18`,
                padding: '1px 6px', borderRadius: 2, letterSpacing: 1,
              }}>{rSev}</span>
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 5 }}>
              {rule.title}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', marginBottom: 6, lineHeight: 1.5 }}>
              {rule.description}
            </div>
            {rule.contributing_factors?.length > 0 && (
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', letterSpacing: 0.5 }}>FACTORS  </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-amber)' }}>
                  {rule.contributing_factors.join(' · ')}
                </span>
              </div>
            )}
            {rule.regulatory_refs?.length > 0 && (
              <div style={{ marginBottom: rule.zone ? 4 : 0 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', letterSpacing: 0.5 }}>REGS  </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-cobalt)' }}>
                  {rule.regulatory_refs.join(' · ')}
                </span>
              </div>
            )}
            {rule.zone && (
              <div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>ZONE  </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-primary)' }}>
                  {rule.zone.replace(/_/g, ' ').toUpperCase()}
                </span>
              </div>
            )}
          </div>
        )
      })}

      {/* Immediate actions */}
      {actions.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)',
            letterSpacing: 1.2, marginBottom: 8,
          }}>IMMEDIATE ACTIONS</div>
          {actions.map((action, i) => (
            <div key={i} style={{
              display: 'flex', gap: 8, alignItems: 'flex-start',
              background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
              borderRadius: 2, padding: '8px 12px', marginBottom: 6,
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-primary)', lineHeight: 1.5,
            }}>
              <span style={{ color: 'var(--accent-red)', fontWeight: 700, flexShrink: 0, minWidth: 14 }}>{i + 1}.</span>
              <span>{action}</span>
            </div>
          ))}
        </div>
      )}

      {/* AI narrative */}
      {narrative && !narrative.startsWith('Narrative generation failed') && narrative !== '' && (
        <div style={{
          marginTop: 14, background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
          borderRadius: 2, padding: '10px 12px',
        }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', letterSpacing: 1, marginBottom: 6 }}>
            AI RISK NARRATIVE
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            {narrative}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Sidebar() {
  const tab           = useRigStore(s => s.sidebarTab)
  const setTab        = useRigStore(s => s.setSidebarTab)
  const persons       = useRigStore(s => s.persons)
  const zones         = useRigStore(s => s.zones)
  const connected     = useRigStore(s => s.connected)
  const compoundRisk  = useRigStore(s => s.compoundRisk)
  const showAvatars   = useRigStore(s => s.showAvatars)
  const showSensors   = useRigStore(s => s.showSensors)
  const toggleAvatars = useRigStore(s => s.toggleAvatars)
  const toggleSensors = useRigStore(s => s.toggleSensors)

  const [clock, setClock] = useState(() =>
    new Date().toLocaleTimeString('en-GB', { hour12: false })
  )
  useEffect(() => {
    const id = setInterval(
      () => setClock(new Date().toLocaleTimeString('en-GB', { hour12: false })),
      1000,
    )
    return () => clearInterval(id)
  }, [])

  const criticalCount  = Object.values(zones).filter(z => z.status === 'critical').length
  const alertPersons   = persons.filter(p => ppeHasAlert(p.ppe || {})).length
  const riskRuleCount  = (compoundRisk?.rules_fired || []).length

  const tabs = [
    { id: 'zones',   label: 'ZONES',     badge: criticalCount },
    { id: 'persons', label: 'PERSONNEL', badge: alertPersons  },
    { id: 'risk',    label: 'RISK',      badge: riskRuleCount },
    { id: 'permits', label: 'PERMITS',   badge: 0             },
  ]

  const toggleBtnStyle = (active) => ({
    flex: 1,
    padding: '6px 0',
    border: `1px solid ${active ? 'var(--border-bright)' : 'var(--border-solid)'}`,
    borderRadius: 2,
    cursor: 'pointer',
    fontFamily: 'var(--font-mono)',
    fontSize: 10,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    transition: 'background 0.12s, color 0.12s, border-color 0.12s',
    background: active ? 'var(--bg-elev)' : 'transparent',
    color:      active ? 'var(--text-primary)' : 'var(--text-dim)',
  })

  return (
    <div style={{
      width: 368,
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      background: 'var(--bg-panel)',
      borderRight: '1px solid var(--border-solid)',
    }}>
      {/* Header */}
      <div style={{ padding: '18px 18px 14px', borderBottom: '1px solid var(--border-solid)' }}>
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 9.5, fontWeight: 500,
          color: 'var(--text-dim)', letterSpacing: 3, textTransform: 'uppercase',
          marginBottom: 6,
        }}>RIGVISION-3D</div>

        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 700,
          color: 'var(--text-primary)', letterSpacing: 1, lineHeight: 1.1,
          marginBottom: 10,
        }}>LIVE MONITOR</div>

        {/* Connection status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
          <span style={{
            width: 6, height: 6,
            background: connected ? 'var(--accent-green)' : 'var(--accent-red)',
            display: 'inline-block',
            animation: connected ? 'pulse 2s infinite' : 'none',
          }} />
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 11,
            color: connected ? 'var(--accent-green)' : 'var(--accent-red)',
            letterSpacing: 0.3,
          }}>
            {connected
              ? `CONNECTED \xb7 ${persons.length} TRACKED`
              : 'DISCONNECTED — RECONNECTING…'}
          </span>
        </div>

        {/* Overlay toggles */}
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={toggleAvatars} style={toggleBtnStyle(showAvatars)}>
            AVATARS {showAvatars ? 'ON' : 'OFF'}
          </button>
          <button onClick={toggleSensors} style={toggleBtnStyle(showSensors)}>
            SENSORS {showSensors ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-solid)',
      }}>
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              flex: 1, padding: '9px 0',
              border: 'none', cursor: 'pointer',
              background: 'transparent',
              borderBottom: `2px solid ${tab === t.id ? 'var(--accent-cobalt)' : 'transparent'}`,
              marginBottom: -1,
              fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
              color: tab === t.id ? 'var(--text-primary)' : 'var(--text-dim)',
              letterSpacing: 1,
              transition: 'color 0.12s, border-color 0.12s',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            }}
          >
            {t.label}
            {t.badge > 0 && (
              <span style={{
                background: 'var(--accent-red)',
                color: 'var(--bg-deep)',
                fontSize: 9, fontFamily: 'var(--font-mono)',
                borderRadius: 2, padding: '1px 5px',
                minWidth: 16, textAlign: 'center',
                fontVariantNumeric: 'tabular-nums',
              }}>{t.badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px 16px' }}>
        {tab === 'zones'   && <ZonesTab />}
        {tab === 'persons' && <PersonsTab />}
        {tab === 'risk'    && <CompoundRiskTab />}
        {tab === 'permits' && <PermitPanel />}
      </div>

      {/* Footer */}
      <div style={{
        padding: '8px 18px',
        borderTop: '1px solid var(--border-solid)',
        fontFamily: 'var(--font-mono)', fontSize: 10,
        color: 'var(--text-dim)',
        display: 'flex', justifyContent: 'space-between',
        letterSpacing: 0.5,
      }}>
        <span>REDIS \xb7 10HZ</span>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{clock}</span>
      </div>
    </div>
  )
}
