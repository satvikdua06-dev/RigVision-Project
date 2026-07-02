import { useRigStore } from '../stores/useRigStore.js'
import { useState, useEffect } from 'react'

export default function TopBar() {
  const zones      = useRigStore(s => s.zones)
  const persons    = useRigStore(s => s.persons)
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const setShowDiagnosticsModal = useRigStore(s => s.setShowDiagnosticsModal)

  const criticalZones  = Object.values(zones).filter(z => z.status === 'critical').length
  const warningZones   = Object.values(zones).filter(z => z.status === 'warning').length
  const alertPersons   = persons.filter(p => !p.ppe.hardhat || !p.ppe.vest || !p.ppe.goggles).length

  // Status values map onto the Industrial Slate accent palette (no neon).
  const OK = 'var(--text-primary)'
  const stats = [
    { label:'Zones', value: Object.keys(zones).length, color:'var(--text-primary)' },
    { label:'Critical', value: criticalZones, color: criticalZones > 0 ? 'var(--accent-red)' : OK },
    { label:'Warnings', value: warningZones, color: warningZones > 0 ? 'var(--accent-amber)' : OK },
    { label:'Personnel', value: persons.length, color:'var(--accent-cobalt)' },
    { label:'PPE Alerts', value: alertPersons, color: alertPersons > 0 ? 'var(--accent-red)' : OK },
  ]

  // Clean clock implementation that updates every second
  const [timeStr, setTimeStr] = useState("")
  useEffect(() => {
    const update = () => {
      setTimeStr(new Date().toLocaleTimeString('en-IN', { hour12:false }) + " IST")
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div style={{
      height: 54, display:'flex', alignItems:'center',
      background:'var(--glass-panel)',
      backdropFilter:'blur(16px) saturate(120%)',
      WebkitBackdropFilter:'blur(16px) saturate(120%)',
      borderBottom:'1px solid var(--border)',
      padding:'0 22px', gap:0, flexShrink:0,
      userSelect:'none', position:'relative', zIndex:5,
    }}>
      {/* Logo area */}
      <div style={{ marginRight:28, flexShrink:0, display:'flex', alignItems:'baseline', gap:8 }}>
        <span style={{
          fontFamily:'var(--font-ui)', fontWeight:700, fontSize:17,
          color:'var(--text-primary)', letterSpacing:0.5,
        }}>RIG<span style={{color:'var(--accent-cobalt)'}}>VISION</span></span>
        <span style={{ fontFamily:'var(--font-mono)', fontSize:9,
          color:'var(--text-dim)', letterSpacing:1, textTransform:'uppercase' }}>v1.0 · Phase-1</span>
      </div>

      <div style={{ width:1, height:28, background:'var(--border)', marginRight:28 }} />

      {/* Stats row with Diagnostics Button */}
      <div style={{ display:'flex', gap:0, flex:1, alignItems:'center' }}>
        {stats.map((s, i) => (
          <div key={i} style={{ paddingRight:24, borderRight:'1px solid var(--border)',
            marginRight:24 }}>
            <div style={{ fontFamily:'var(--font-mono)', fontSize:9, color:'var(--text-muted)',
              letterSpacing:1.5, textTransform:'uppercase', marginBottom:2 }}>{s.label}</div>
            <div style={{ fontFamily:'var(--font-ui)', fontSize:22, fontWeight:600,
              color: s.color, lineHeight:1 }}>{s.value}</div>
          </div>
        ))}

        {/* Sensor Console Link */}
        <a
          href="#/sensors"
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '4px 16px',
            display: 'flex',
            alignItems: 'center',
            textDecoration: 'none',
            marginRight: 12,
            height: 38,
            boxSizing: 'border-box',
            transition: 'border-color 0.15s',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--border-bright)' }}
          onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)' }}
        >
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 8.5, color: 'var(--text-muted)', letterSpacing: 1.2, lineHeight: 1, marginBottom: 3, fontFamily: 'var(--font-mono)', textTransform:'uppercase' }}>Sensor Input</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', lineHeight: 1, letterSpacing: 0.3 }}>
              Console
            </div>
          </div>
        </a>

        {/* AI Diagnostics Button */}
        <button
          onClick={() => setShowDiagnosticsModal(true)}
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 6,
            padding: '4px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            cursor: 'pointer',
            transition: 'border-color 0.15s, background 0.15s',
            fontFamily: 'var(--font-ui)',
            height: 38,
            outline: 'none',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--bg-panel)';
            e.currentTarget.style.borderColor = 'var(--border-bright)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'var(--bg-card)';
            e.currentTarget.style.borderColor = 'var(--border)';
          }}
        >
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 8.5, color: 'var(--text-muted)', letterSpacing: 1.2, lineHeight: 1, marginBottom: 3, fontFamily:'var(--font-mono)', textTransform:'uppercase' }}>AI Diagnostics</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', lineHeight: 1, letterSpacing: 0.3 }}>
              View Reports
            </div>
          </div>
          {diagnostics.length > 0 && (
            <span style={{
              background: 'var(--accent-cobalt)',
              color: 'var(--bg-deep)',
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              fontWeight: 600,
              borderRadius: 4,
              padding: '2px 6px',
              minWidth: 16,
              textAlign: 'center',
            }}>
              {diagnostics.length}
            </span>
          )}
        </button>
      </div>

      {/* Right: clock */}
      <div style={{ fontFamily:'var(--font-mono)', fontSize:12, color:'var(--text-muted)',
        letterSpacing:1, flexShrink:0 }}>
        {timeStr}
      </div>
    </div>
  )
}
