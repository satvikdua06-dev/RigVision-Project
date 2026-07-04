import { useState } from 'react'
import { useRigStore } from '../stores/useRigStore.js'
import { ProofLightbox, ppeChipStyle, personPpeItems, ppeHasAlert } from './PPEPanel.jsx'

// Status → accent variable (Industrial Slate palette). Standalone color values only,
// so they slot straight into `color`/`borderColor` without alpha concatenation.
const STATUS_COLOR = {
  normal:   'var(--accent-green)',
  warning:  'var(--accent-amber)',
  critical: 'var(--accent-red)',
}

// Labels per sensor type. Thresholds + bar bounds come from the zone's sensor_meta
// (sourced from zone_definitions.json), so the sidebar matches the Sensor Console exactly.
const SENSOR_LABELS = {
  temperature: 'Temperature',
  gas_h2s:     'H₂S',
  vibration:   'Vibration',
  noise:       'Noise',
  pressure:    'Pressure',
}

function SensorBar({ label, value, meta }) {
  const known = value != null && !Number.isNaN(value)
  const { min = 0, max = 100, warning, critical, unit = '', threshold_source } = meta || {}
  // Same scale as the Sensor Console: fill across [min, max] (max = critical*1.2).
  const pct = known ? Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100)) : 0
  const color = !known ? 'var(--text-dim)'
    : (critical != null && value >= critical) ? 'var(--accent-red)'
    : (warning != null && value >= warning) ? 'var(--accent-amber)'
    : 'var(--accent-green)'

  const level = threshold_source?.level
  const sourceIcon = level === 'device_manual' ? ' ⚙' : level === 'zone_environmental' ? ' ⛨' : ''
  const tooltip = threshold_source?.reason || (warning != null || critical != null ? `Normal range: [${min}, ${max}]` : '')

  return (
    <div style={{ marginBottom: 8 }} title={tooltip}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:3,
        fontFamily:'var(--font-mono)', fontSize:10.5 }}>
        <span style={{ color:'var(--text-muted)' }}>
          {label}
          <span style={{ color: level === 'device_manual' ? 'var(--accent-cobalt)' : 'var(--text-muted)', fontSize: 9 }}>
            {sourceIcon}
          </span>
          {(warning != null || critical != null) && (
            <span style={{ fontSize: 8.5, color: 'var(--text-dim)', marginLeft: 4 }}>
              ({warning != null ? `w:${warning}` : '—'}/{critical != null ? `c:${critical}` : '—'})
            </span>
          )}
        </span>
        <span style={{ color }}>{known ? `${value} ${unit}` : 'NO DATA'}</span>
      </div>
      <div style={{ height:4, background:'var(--border)', borderRadius:2, overflow:'hidden' }}>
        <div style={{ height:'100%', width:`${pct}%`, background: color,
          borderRadius:2, transition:'width 0.6s ease' }} />
      </div>
    </div>
  )
}

// Shared search input styling (flat steel field, sharp focus border).
const searchInputStyle = {
  width: '100%',
  padding: '8px 12px',
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  outline: 'none',
  boxSizing: 'border-box',
  transition: 'border-color 0.15s',
}

function ZonesTab() {
  const [search, setSearch] = useState('')
  const zones      = useRigStore(s => s.zones)
  const selectZone = useRigStore(s => s.selectZone)
  const selectedZone = useRigStore(s => s.selectedZone)

  const filteredZones = Object.entries(zones).filter(([id, zone]) => {
    if (!search) return true
    const term = search.toLowerCase()
    const label = (zone.label || id.replace(/_/g, ' ')).toLowerCase()
    const status = (zone.status || '').toLowerCase()
    return label.includes(term) || status.includes(term)
  })

  return (
    <div>
      {/* Search Bar */}
      <div style={{ marginBottom: 12, position: 'relative' }}>
        <input
          type="text"
          placeholder="Search zone name, status..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={searchInputStyle}
          onFocus={(e) => e.target.style.borderColor = 'var(--border-bright)'}
          onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 14, fontFamily: 'var(--font-mono)',
            }}
          >
            ×
          </button>
        )}
      </div>

      {filteredZones.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          fontSize: 12, padding: 20
        }}>No zones found</div>
      ) : (
        filteredZones.map(([id, zone]) => {
          const sc = STATUS_COLOR[zone.status]
          const isSelected = selectedZone === id
          return (
            <div key={id} onClick={() => selectZone(id)}
              style={{
                background: isSelected ? 'var(--bg-elev)' : 'var(--glass-card)',
                border: `1px solid ${isSelected ? 'var(--border-bright)' : 'var(--border)'}`,
                borderLeft: `2px solid ${sc}`,
                borderRadius: 'var(--radius-sm)', padding: '15px 16px', marginBottom: 12, cursor:'pointer',
                boxShadow: 'var(--shadow-card)',
                transition: 'border-color 0.15s, background 0.15s',
              }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14 }}>
                <span style={{ fontFamily:'var(--font-ui)', fontSize:14.5, fontWeight:600,
                  letterSpacing:-0.01, color:'var(--text-primary)' }}>{zone.label || id.replace(/_/g, ' ').toUpperCase()}</span>
                <span style={{
                  display:'inline-flex', alignItems:'center', gap:5,
                  color: sc, fontFamily:'var(--font-mono)', fontSize:9.5,
                  letterSpacing:0.5, textTransform:'uppercase', fontWeight:500,
                }}>
                  <span style={{ width:6, height:6, borderRadius:'50%', background:sc, display:'inline-block' }} />
                  {zone.status}
                </span>
              </div>
              {(() => {
                const types = zone.sensor_types || ['temperature', 'gas_h2s', 'vibration', 'noise', 'pressure']
                const meta = zone.sensor_meta || {}
                return types.map(t => (
                  <SensorBar key={t} label={SENSOR_LABELS[t] || t} value={zone[t]} meta={meta[t]} />
                ))
              })()}
              <div style={{ display:'flex', justifyContent:'space-between', marginTop:8,
                fontFamily:'var(--font-mono)', fontSize:10.5 }}>
                <span style={{ color:'var(--text-muted)' }}>👤 {zone.person_count} person{zone.person_count!==1?'s':''}</span>
                {zone.ppe_violations.length > 0 && (
                  <span style={{ color:'var(--accent-red)' }}>⚠ {zone.ppe_violations.length} PPE</span>
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
  const [search, setSearch] = useState('')
  const [proofItem, setProofItem] = useState(null)
  const persons       = useRigStore(s => s.persons)
  const selectPerson  = useRigStore(s => s.selectPerson)
  const selectedPerson = useRigStore(s => s.selectedPerson)

  const filteredPersons = persons.filter(p => {
    if (!search) return true
    const term = search.toLowerCase()
    return (
      p.id.toString().includes(term) ||
      (p.zone && p.zone.toLowerCase().includes(term)) ||
      (p.posture && p.posture.toLowerCase().includes(term))
    )
  })

  return (
    <div>
      {/* Search Bar */}
      <div style={{ marginBottom: 12, position: 'relative' }}>
        <input
          type="text"
          placeholder="Search ID, zone, posture..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={searchInputStyle}
          onFocus={(e) => e.target.style.borderColor = 'var(--border-bright)'}
          onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            style={{
              position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 14, fontFamily: 'var(--font-mono)',
            }}
          >
            ×
          </button>
        )}
      </div>

      {filteredPersons.length === 0 ? (
        <div style={{
          textAlign: 'center', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          fontSize: 12, padding: 20
        }}>No personnel found</div>
      ) : (
        filteredPersons.map((p, idx) => {
          const ppeItems = personPpeItems(p.id, p.ppe)
          const hasAlert  = ppeHasAlert(p.ppe)
          const hasUnknown = ppeItems.some(i => i.status == null || i.status === 'unknown')
          const isSelected = selectedPerson === p.id
          const accent = isSelected ? 'var(--accent-cobalt)' : hasAlert ? 'var(--accent-red)' : 'var(--border-bright)'
          return (
            <div key={`${p.id}-${idx}`} onClick={() => selectPerson(p.id)}
              style={{
                background: isSelected ? 'var(--bg-elev)' : 'var(--glass-card)',
                border:`1px solid ${isSelected ? 'var(--border-bright)' : 'var(--border)'}`,
                borderLeft:`2px solid ${accent}`,
                borderRadius:'var(--radius-sm)', padding:'15px 16px', marginBottom:12, cursor:'pointer',
                boxShadow:'var(--shadow-card)',
                transition:'border-color 0.15s, background 0.15s',
              }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
                <span style={{ fontFamily:'var(--font-ui)', fontSize:14.5, fontWeight:600,
                    letterSpacing:-0.01, color:'var(--text-primary)' }}>PERSON #{p.id}</span>
                {hasAlert ? (
                  <span style={{ background:'var(--bg-card)', border:'1px solid var(--accent-red)',
                    color:'var(--accent-red)', fontFamily:'var(--font-mono)', fontSize:9,
                    padding:'2px 8px', borderRadius:4, letterSpacing:1 }}>ALERT</span>
                ) : hasUnknown ? (
                  <span style={{ background:'var(--bg-card)', border:'1px solid var(--border-bright)',
                    color:'var(--text-muted)', fontFamily:'var(--font-mono)', fontSize:9,
                    padding:'2px 8px', borderRadius:4, letterSpacing:1 }}>UNMONITORED</span>
                ) : null}
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:4,
                fontFamily:'var(--font-mono)', fontSize:10.5, marginBottom:8 }}>
                <div><span style={{color:'var(--text-muted)'}}>Zone </span>
                  <span style={{color:'var(--accent-cobalt)'}}>{p.zone.replace(/_/g, ' ').toUpperCase()}</span></div>
                <div><span style={{color:'var(--text-muted)'}}>Posture </span>
                  <span style={{color:'var(--text-primary)'}}>{p.posture}</span></div>
                <div><span style={{color:'var(--text-muted)'}}>Conf </span>
                  <span style={{color:'var(--accent-green)'}}>{(p.confidence*100).toFixed(0)}%</span></div>
                <div><span style={{color:'var(--text-muted)'}}>Cams </span>
                  <span style={{color:'var(--text-primary)'}}>{p.cameras_visible}</span></div>
              </div>
              {/* PPE indicators — live per-person Body Gear + Hat detection */}
              <div style={{ display:'flex', gap:8, fontFamily:'var(--font-mono)', fontSize:10.5 }}>
                {ppeItems.map(({ key, label, status, proof }) => {
                  const { tone, mark } = ppeChipStyle(status)
                  const isMissing = status === 'missing'
                  return (
                    <span key={key} style={{
                      display:'inline-flex', alignItems:'center', gap:6,
                      padding:'2px 8px', borderRadius:4, fontSize:10,
                      background: 'var(--bg-card)', border:`1px solid ${tone}`, color: tone,
                    }}>
                      {label} {mark}
                      {isMissing && (
                        <button
                          onClick={(e) => { e.stopPropagation(); setProofItem({ item: proof, since: Date.now() }) }}
                          title="View proof frame"
                          style={{
                            background:'transparent', border:`1px solid ${tone}`, color: tone,
                            borderRadius:3, fontSize:8, padding:'0 4px', cursor:'pointer', letterSpacing:0.5,
                          }}>
                          PROOF
                        </button>
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

export default function Sidebar() {
  const tab       = useRigStore(s => s.sidebarTab)
  const setTab    = useRigStore(s => s.setSidebarTab)
  const persons   = useRigStore(s => s.persons)
  const zones     = useRigStore(s => s.zones)
  const connected     = useRigStore(s => s.connected)
  const showAvatars   = useRigStore(s => s.showAvatars)
  const showSensors   = useRigStore(s => s.showSensors)
  const toggleAvatars = useRigStore(s => s.toggleAvatars)
  const toggleSensors = useRigStore(s => s.toggleSensors)

  const criticalCount = Object.values(zones).filter(z => z.status === 'critical').length
  // PPE alerts come from live per-person Body Gear/Hat detection (p.ppe.{backpack,hat}).
  const alertPersons = persons.filter(p => p.ppe?.backpack === 'missing' || p.ppe?.hat === 'missing').length

  const tabs = [
    { id:'zones',      label:'Zones',      badge: criticalCount },
    { id:'persons',    label:'Personnel',  badge: alertPersons },
  ]

  return (
    <div style={{
      width: 312, height: '100%', display:'flex', flexDirection:'column',
      background:'var(--glass-panel)',
      backdropFilter:'blur(16px) saturate(120%)',
      WebkitBackdropFilter:'blur(16px) saturate(120%)',
      borderRight:'1px solid var(--border)',
      boxShadow:'var(--inner-hi)',
    }}>
      {/* Header */}
      <div style={{ padding:'22px 20px 0' }}>
        <div style={{
          fontFamily:'var(--font-mono)', fontSize:10, fontWeight:500,
          color:'var(--text-dim)', letterSpacing:2.5, textTransform:'uppercase', marginBottom:7
        }}>RigVision · RigVision-3D</div>
        <div style={{
          fontFamily:'var(--font-ui)', fontSize:21, fontWeight:600,
          color:'var(--text-primary)', letterSpacing:-0.02, lineHeight:1,
        }}>Live Monitor</div>

        {/* Connection Status */}
        <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:8, marginBottom:12 }}>
          <span style={{ width:7, height:7, borderRadius:'50%',
            background: connected ? 'var(--accent-green)' : 'var(--accent-red)',
            display:'inline-block',
            animation: connected ? 'pulse 2s infinite' : 'none' }} />
          <span style={{ fontFamily:'var(--font-mono)', fontSize:11, color: connected ? 'var(--accent-green)' : 'var(--accent-red)' }}>
            {connected ? `CONNECTED · ${persons.length} TRACKED` : 'DISCONNECTED — RECONNECTING…'}
          </span>
        </div>

        {/* Toggles */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button onClick={toggleAvatars} style={{
            flex: 1, padding: '5px 0', border: `1px solid ${showAvatars ? 'var(--border-bright)' : 'var(--border)'}`,
            background: showAvatars ? 'var(--bg-card)' : 'transparent',
            color: showAvatars ? 'var(--text-primary)' : 'var(--text-muted)', borderRadius: 4, cursor: 'pointer',
            fontFamily: 'var(--font-mono)', fontSize: 10, transition: 'all 0.15s'
          }}>
            👤 Avatars {showAvatars ? 'ON' : 'OFF'}
          </button>
          <button onClick={toggleSensors} style={{
            flex: 1, padding: '5px 0', border: `1px solid ${showSensors ? 'var(--border-bright)' : 'var(--border)'}`,
            background: showSensors ? 'var(--bg-card)' : 'transparent',
            color: showSensors ? 'var(--text-primary)' : 'var(--text-muted)', borderRadius: 4, cursor: 'pointer',
            fontFamily: 'var(--font-mono)', fontSize: 10, transition: 'all 0.15s'
          }}>
            📊 Sensors {showSensors ? 'ON' : 'OFF'}
          </button>
        </div>

        <div style={{ height:'1px', background:'var(--border)', marginBottom:16 }} />
      </div>

      {/* Tab bar */}
      <div style={{ display:'flex', padding:'0 14px', gap:4, marginBottom:12 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex:1, padding:'7px 0', border:'none', cursor:'pointer', borderRadius:0,
            background: 'transparent',
            borderBottom: tab === t.id ? '2px solid var(--accent-cobalt)' : '2px solid var(--border)',
            fontFamily:'var(--font-ui)', fontSize:12, fontWeight:600,
            color: tab === t.id ? 'var(--text-primary)' : 'var(--text-muted)',
            letterSpacing:0.3, transition:'all 0.15s',
            display:'flex', flexDirection:'row', alignItems:'center', justifyContent:'center', gap:6,
          }}>
            {t.label}
            {t.badge > 0 && (
              <span style={{
                background: 'var(--accent-red)', color:'var(--bg-deep)', fontSize:9,
                borderRadius:4, padding:'1px 5px', fontFamily:'var(--font-mono)',
                minWidth:16, textAlign:'center',
              }}>{t.badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div style={{ flex:1, overflowY:'auto', padding:'4px 16px 16px' }}>
        {tab === 'zones'   && <ZonesTab />}
        {tab === 'persons' && <PersonsTab />}
      </div>

      {/* Footer */}
      <div style={{
        padding:'10px 20px', borderTop:'1px solid var(--border)',
        fontFamily:'var(--font-mono)', fontSize:9.5, color:'var(--text-dim)',
        display:'flex', justifyContent:'space-between',
      }}>
        <span>Redis · 10Hz feed</span>
        <span>{new Date().toLocaleTimeString()}</span>
      </div>
    </div>
  )
}
