import { useState } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const SEVERITY_COLOR = {
  LOW:      '#00e676',
  MEDIUM:   '#ffb300',
  HIGH:     '#ff7043',
  CRITICAL: '#ff3b3b',
}

const STATUS_COLOR = {
  normal:   '#00e676',
  warning:  '#ffb300',
  critical: '#ff3b3b',
}

function SensorBar({ label, value, max, unit, warn, crit }) {
  const pct = Math.min(100, (value / max) * 100)
  const color = value >= crit ? '#ff3b3b' : value >= warn ? '#ffb300' : '#00e676'
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:3,
        fontFamily:"'Share Tech Mono',monospace", fontSize:10.5 }}>
        <span style={{ color:'#5a8aaa' }}>{label}</span>
        <span style={{ color }}>{value} {unit}</span>
      </div>
      <div style={{ height:4, background:'rgba(255,255,255,0.07)', borderRadius:2, overflow:'hidden' }}>
        <div style={{ height:'100%', width:`${pct}%`, background: color,
          borderRadius:2, boxShadow:`0 0 6px ${color}88`,
          transition:'width 0.6s ease' }} />
      </div>
    </div>
  )
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
          style={{
            width: '100%',
            padding: '8px 12px',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(0,180,255,0.2)',
            borderRadius: 6,
            color: '#e0f4ff',
            fontFamily: "'Share Tech Mono', monospace",
            fontSize: 12,
            outline: 'none',
            boxSizing: 'border-box',
            transition: 'border-color 0.2s',
          }}
          onFocus={(e) => e.target.style.borderColor = 'rgba(0,180,255,0.6)'}
          onBlur={(e) => e.target.style.borderColor = 'rgba(0,180,255,0.2)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            style={{
              position: 'absolute',
              right: 8,
              top: '50%',
              transform: 'translateY(-50%)',
              background: 'transparent',
              border: 'none',
              color: '#5a8aaa',
              cursor: 'pointer',
              fontSize: 14,
              fontFamily: "'Share Tech Mono', monospace",
            }}
          >
            ×
          </button>
        )}
      </div>

      {filteredZones.length === 0 ? (
        <div style={{
          textAlign: 'center', color: '#5a8aaa', fontFamily: "'Share Tech Mono', monospace",
          fontSize: 12, padding: 20
        }}>No zones found</div>
      ) : (
        filteredZones.map(([id, zone]) => {
          const sc = STATUS_COLOR[zone.status]
          const isSelected = selectedZone === id
          return (
            <div key={id} onClick={() => selectZone(id)}
              style={{
                background: isSelected ? 'rgba(0,180,255,0.08)' : 'rgba(255,255,255,0.02)',
                border: `1px solid ${isSelected ? sc+'88' : 'rgba(255,255,255,0.06)'}`,
                borderRadius: 10, padding: '12px 14px', marginBottom: 10, cursor:'pointer',
                transition: 'all 0.2s',
              }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:10 }}>
                <span style={{ fontFamily:"'Barlow Condensed'", fontSize:15, fontWeight:700,
                  letterSpacing:1, color:'#e0f4ff' }}>{zone.label || id.replace(/_/g, ' ').toUpperCase()}</span>
                <span style={{
                  background: sc + '22', border:`1px solid ${sc}`, color: sc,
                  fontFamily:"'Share Tech Mono'", fontSize:9, padding:'2px 8px',
                  borderRadius:4, letterSpacing:2, textTransform:'uppercase',
                }}>{zone.status}</span>
              </div>
              <SensorBar label="Temperature" value={zone.temperature} max={100} unit="°C" warn={45} crit={70} />
              <SensorBar label="H₂S"         value={zone.gas_h2s}    max={25}  unit="ppm" warn={10} crit={20} />
              <SensorBar label="Vibration"   value={zone.vibration}  max={6}   unit="g"   warn={3}  crit={5}  />
              <SensorBar label="Noise"       value={zone.noise}      max={120} unit="dB"  warn={85} crit={100}/>
              <div style={{ display:'flex', justifyContent:'space-between', marginTop:8,
                fontFamily:"'Share Tech Mono'", fontSize:10.5 }}>
                <span style={{ color:'#5a8aaa' }}>👤 {zone.person_count} person{zone.person_count!==1?'s':''}</span>
                {zone.ppe_violations.length > 0 && (
                  <span style={{ color:'#ff7043' }}>⚠ {zone.ppe_violations.length} PPE</span>
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
          style={{
            width: '100%',
            padding: '8px 12px',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(0,180,255,0.2)',
            borderRadius: 6,
            color: '#e0f4ff',
            fontFamily: "'Share Tech Mono', monospace",
            fontSize: 12,
            outline: 'none',
            boxSizing: 'border-box',
            transition: 'border-color 0.2s',
          }}
          onFocus={(e) => e.target.style.borderColor = 'rgba(0,180,255,0.6)'}
          onBlur={(e) => e.target.style.borderColor = 'rgba(0,180,255,0.2)'}
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            style={{
              position: 'absolute',
              right: 8,
              top: '50%',
              transform: 'translateY(-50%)',
              background: 'transparent',
              border: 'none',
              color: '#5a8aaa',
              cursor: 'pointer',
              fontSize: 14,
              fontFamily: "'Share Tech Mono', monospace",
            }}
          >
            ×
          </button>
        )}
      </div>

      {filteredPersons.length === 0 ? (
        <div style={{
          textAlign: 'center', color: '#5a8aaa', fontFamily: "'Share Tech Mono', monospace",
          fontSize: 12, padding: 20
        }}>No personnel found</div>
      ) : (
        filteredPersons.map(p => {
          const ppe = p.ppe || {}
          const hasAlert  = ppe.hardhat === false || ppe.vest === false || ppe.goggles === false
          const hasUnknown = ppe.hardhat == null || ppe.vest == null || ppe.goggles == null
          const isSelected = selectedPerson === p.id
          return (
            <div key={p.id} onClick={() => selectPerson(p.id)}
              style={{
                background: isSelected ? 'rgba(0,180,255,0.08)' : 'rgba(255,255,255,0.02)',
                border:`1px solid ${isSelected ? '#00b4ff55' : hasAlert ? '#ff3b3b33' : 'rgba(255,255,255,0.06)'}`,
                borderRadius:10, padding:'12px 14px', marginBottom:10, cursor:'pointer',
                transition:'all 0.2s',
              }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                <span style={{ fontFamily:"'Barlow Condensed'", fontSize:16, fontWeight:700,
                  letterSpacing:1, color:'#e0f4ff' }}>PERSON #{p.id}</span>
                {hasAlert ? (
                  <span style={{ background:'#ff3b3b22', border:'1px solid #ff3b3b',
                    color:'#ff3b3b', fontFamily:"'Share Tech Mono'", fontSize:9,
                    padding:'2px 8px', borderRadius:4, letterSpacing:2 }}>ALERT</span>
                ) : hasUnknown ? (
                  <span style={{ background:'rgba(90,138,170,0.1)', border:'1px solid #5a8aaa44',
                    color:'#5a8aaa', fontFamily:"'Share Tech Mono'", fontSize:9,
                    padding:'2px 8px', borderRadius:4, letterSpacing:2 }}>UNMONITORED</span>
                ) : null}
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:4,
                fontFamily:"'Share Tech Mono'", fontSize:10.5, marginBottom:8 }}>
                <div><span style={{color:'#5a8aaa'}}>Zone </span>
                  <span style={{color:'#00b4ff'}}>{p.zone.replace(/_/g, ' ').toUpperCase()}</span></div>
                <div><span style={{color:'#5a8aaa'}}>Posture </span>
                  <span style={{color:'#00ffd5'}}>{p.posture}</span></div>
                <div><span style={{color:'#5a8aaa'}}>Conf </span>
                  <span style={{color:'#00e676'}}>{(p.confidence*100).toFixed(0)}%</span></div>
                <div><span style={{color:'#5a8aaa'}}>Cams </span>
                  <span>{p.cameras_visible}</span></div>
              </div>
              {/* PPE indicators */}
              <div style={{ display:'flex', gap:8, fontFamily:"'Share Tech Mono'", fontSize:10.5 }}>
                {[
                  { label:'🪖 Hat', val: ppe.hardhat },
                  { label:'🦺 Vest', val: ppe.vest },
                  { label:'🥽 Goggles', val: ppe.goggles },
                ].map(({ label, val }) => {
                  const isUnknown = val == null
                  const ok = val === true
                  return (
                    <span key={label} style={{
                      padding:'2px 8px', borderRadius:4, fontSize:10,
                      background: isUnknown ? 'rgba(90,138,170,0.08)' : ok ? '#00e67611' : '#ff3b3b22',
                      border:`1px solid ${isUnknown ? '#5a8aaa44' : ok ? '#00e67688' : '#ff3b3b88'}`,
                      color: isUnknown ? '#5a8aaa' : ok ? '#00e676' : '#ff3b3b',
                    }}>
                      {label} {isUnknown ? '?' : ok ? '✓' : '✗'}
                    </span>
                  )
                })}
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}

function ViolationsTab() {
  const violations = useRigStore(s => s.violations)

  function timeAgo(ts) {
    const s = Math.floor((Date.now() - ts) / 1000)
    if (s < 60) return `${s}s ago`
    return `${Math.floor(s/60)}m ago`
  }

  return (
    <div>
      {violations.length === 0 && (
        <div style={{ textAlign:'center', color:'#5a8aaa', fontFamily:"'Share Tech Mono'",
          fontSize:12, padding:30 }}>No violations detected</div>
      )}
      {violations.map(v => {
        const sc = SEVERITY_COLOR[v.severity]
        return (
          <div key={v.id} style={{
            background:'rgba(255,255,255,0.02)',
            border:`1px solid ${sc}33`,
            borderLeft:`3px solid ${sc}`,
            borderRadius:8, padding:'10px 14px', marginBottom:10,
          }}>
            <div style={{ display:'flex', justifyContent:'space-between', marginBottom:5 }}>
              <span style={{ fontFamily:"'Share Tech Mono'", fontSize:10, color: sc,
                letterSpacing:1 }}>{v.severity}</span>
              <span style={{ fontFamily:"'Share Tech Mono'", fontSize:10, color:'#5a8aaa' }}>
                {timeAgo(v.timestamp)}
              </span>
            </div>
            <div style={{ fontFamily:"'Rajdhani'", fontSize:13, fontWeight:500,
              color:'#e0f4ff', marginBottom:4 }}>{v.message}</div>
            <div style={{ fontFamily:"'Share Tech Mono'", fontSize:9.5, color:'#5a8aaa' }}>
              {v.rule_id} · {v.zone.replace(/_/g, ' ').toUpperCase()}
              {v.person_ids.length > 0 && ` · Person ${v.person_ids.map(i=>'#'+i).join(', ')}`}
            </div>
          </div>
        )
      })}
    </div>
  )
}


export default function Sidebar() {
  const tab       = useRigStore(s => s.sidebarTab)
  const setTab    = useRigStore(s => s.setSidebarTab)
  const persons   = useRigStore(s => s.persons)
  const zones     = useRigStore(s => s.zones)
  const violations = useRigStore(s => s.violations)
  const connected     = useRigStore(s => s.connected)
  const showAvatars   = useRigStore(s => s.showAvatars)
  const showSensors   = useRigStore(s => s.showSensors)
  const toggleAvatars = useRigStore(s => s.toggleAvatars)
  const toggleSensors = useRigStore(s => s.toggleSensors)

  const criticalCount = Object.values(zones).filter(z => z.status === 'critical').length
  const alertPersons  = persons.filter(p => p.ppe?.hardhat === false || p.ppe?.vest === false || p.ppe?.goggles === false).length

  const tabs = [
    { id:'zones',      label:'Zones',      badge: criticalCount, badgeColor:'#ff3b3b' },
    { id:'persons',    label:'Personnel',  badge: alertPersons,  badgeColor:'#ff7043' },
    { id:'violations', label:'Violations', badge: violations.length, badgeColor:'#ffb300' },
  ]

  return (
    <div style={{
      width: 300, height: '100%', display:'flex', flexDirection:'column',
      background:'rgba(5,12,22,0.96)',
      borderRight:'1px solid rgba(0,180,255,0.12)',
      backdropFilter:'blur(20px)',
    }}>
      {/* Header */}
      <div style={{ padding:'20px 20px 0' }}>
        <div style={{
          fontFamily:"'Barlow Condensed'", fontSize:11, fontWeight:600,
          color:'#5a8aaa', letterSpacing:4, textTransform:'uppercase', marginBottom:4
        }}>RigVision · RigVision-3D</div>
        <div style={{
          fontFamily:"'Barlow Condensed'", fontSize:26, fontWeight:700,
          color:'#00b4ff', letterSpacing:2, lineHeight:1,
        }}>LIVE MONITOR</div>
        
        {/* Connection Status */}
        <div style={{ display:'flex', alignItems:'center', gap:6, marginTop:6, marginBottom:12 }}>
          <span style={{ width:7, height:7, borderRadius:'50%', 
            background: connected ? '#00e676' : '#ff3b3b',
            boxShadow: connected ? '0 0 8px #00e676' : '0 0 8px #ff3b3b', 
            display:'inline-block',
            animation: connected ? 'pulse 2s infinite' : 'none' }} />
          <span style={{ fontFamily:"'Share Tech Mono'", fontSize:11, color: connected ? '#00e676' : '#ff3b3b' }}>
            {connected ? `CONNECTED · ${persons.length} TRACKED` : 'DISCONNECTED - RECONNECTING...'}
          </span>
        </div>
        
        {/* Toggles */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <button onClick={toggleAvatars} style={{
            flex: 1, padding: '4px 0', border: `1px solid ${showAvatars ? '#00b4ff' : '#2a4a5a'}`, 
            background: showAvatars ? 'rgba(0,180,255,0.15)' : 'transparent',
            color: showAvatars ? '#e0f4ff' : '#5a8aaa', borderRadius: 4, cursor: 'pointer',
            fontFamily: "'Share Tech Mono'", fontSize: 10, transition: 'all 0.2s'
          }}>
            👤 Avatars {showAvatars ? 'ON' : 'OFF'}
          </button>
          <button onClick={toggleSensors} style={{
            flex: 1, padding: '4px 0', border: `1px solid ${showSensors ? '#00e676' : '#2a4a5a'}`, 
            background: showSensors ? 'rgba(0,230,118,0.15)' : 'transparent',
            color: showSensors ? '#e0f4ff' : '#5a8aaa', borderRadius: 4, cursor: 'pointer',
            fontFamily: "'Share Tech Mono'", fontSize: 10, transition: 'all 0.2s'
          }}>
            📊 Sensors {showSensors ? 'ON' : 'OFF'}
          </button>
        </div>

        <div style={{ height:'1px', background:'linear-gradient(90deg,#00b4ff33,transparent)', marginBottom:16 }} />
      </div>

      {/* Tab bar */}
      <div style={{ display:'flex', padding:'0 14px', gap:4, marginBottom:12 }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            flex:1, padding:'7px 0', border:'none', cursor:'pointer', borderRadius:7,
            background: tab === t.id ? 'rgba(0,180,255,0.15)' : 'transparent',
            borderBottom: tab === t.id ? '2px solid #00b4ff' : '2px solid transparent',
            fontFamily:"'Barlow Condensed'", fontSize:12, fontWeight:600,
            color: tab === t.id ? '#00b4ff' : '#5a8aaa',
            letterSpacing:1, textTransform:'uppercase', transition:'all 0.2s',
            display:'flex', flexDirection:'column', alignItems:'center', gap:2,
          }}>
            {t.label}
            {t.badge > 0 && (
              <span style={{
                background: t.badgeColor, color:'#fff', fontSize:9,
                borderRadius:10, padding:'1px 5px', fontFamily:"'Share Tech Mono'",
                minWidth:16, textAlign:'center',
              }}>{t.badge}</span>
            )}
          </button>
        ))}
      </div>

      {/* Scrollable content */}
      <div style={{ flex:1, overflowY:'auto', padding:'0 14px 14px' }}>
        {tab === 'zones'      && <ZonesTab />}
        {tab === 'persons'    && <PersonsTab />}
        {tab === 'violations' && <ViolationsTab />}
      </div>

      {/* Footer */}
      <div style={{
        padding:'10px 20px', borderTop:'1px solid rgba(0,180,255,0.08)',
        fontFamily:"'Share Tech Mono'", fontSize:9.5, color:'#2a4a5a',
        display:'flex', justifyContent:'space-between',
      }}>
        <span>Redis · 10Hz feed</span>
        <span>{new Date().toLocaleTimeString()}</span>
      </div>
    </div>
  )
}
