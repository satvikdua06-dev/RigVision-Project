import { useRigStore } from '../stores/useRigStore.js'
import { useState, useEffect } from 'react'

export default function TopBar() {
  const zones      = useRigStore(s => s.zones)
  const violations = useRigStore(s => s.violations)
  const persons    = useRigStore(s => s.persons)
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const setShowDiagnosticsModal = useRigStore(s => s.setShowDiagnosticsModal)

  const criticalZones  = Object.values(zones).filter(z => z.status === 'critical').length
  const warningZones   = Object.values(zones).filter(z => z.status === 'warning').length
  const alertPersons   = persons.filter(p => !p.ppe.hardhat || !p.ppe.vest || !p.ppe.goggles).length
  const criticalViol   = violations.filter(v => v.severity === 'CRITICAL').length

  const stats = [
    { label:'Zones', value: Object.keys(zones).length, color:'#00b4ff' },
    { label:'Critical', value: criticalZones, color: criticalZones > 0 ? '#ff3b3b' : '#00e676' },
    { label:'Warnings', value: warningZones, color: warningZones > 0 ? '#ffb300' : '#00e676' },
    { label:'Personnel', value: persons.length, color:'#00ffd5' },
    { label:'PPE Alerts', value: alertPersons, color: alertPersons > 0 ? '#ff7043' : '#00e676' },
    { label:'Violations', value: violations.length, color: criticalViol > 0 ? '#ff3b3b' : '#ffb300' },
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
      height: 52, display:'flex', alignItems:'center',
      background:'rgba(5,10,20,0.96)',
      borderBottom:'1px solid rgba(0,180,255,0.12)',
      backdropFilter:'blur(20px)',
      padding:'0 20px', gap:0, flexShrink:0,
      userSelect:'none'
    }}>
      {/* Logo area */}
      <div style={{ marginRight:28, flexShrink:0 }}>
        <span style={{
          fontFamily:"'Barlow Condensed'", fontWeight:700, fontSize:18,
          color:'#00b4ff', letterSpacing:3, textTransform:'uppercase',
        }}>RIG<span style={{color:'#00ffd5'}}>VISION</span></span>
        <span style={{ fontFamily:"'Share Tech Mono'", fontSize:9,
          color:'#5a8aaa', marginLeft:8, letterSpacing:2 }}>v1.0 PHASE-1</span>
      </div>

      <div style={{ width:1, height:28, background:'rgba(0,180,255,0.15)', marginRight:28 }} />

      {/* Stats row with Diagnostics Button */}
      <div style={{ display:'flex', gap:0, flex:1, alignItems:'center' }}>
        {stats.map((s, i) => (
          <div key={i} style={{ paddingRight:24, borderRight: '1px solid rgba(0,180,255,0.1)',
            marginRight:24 }}>
            <div style={{ fontFamily:"'Share Tech Mono'", fontSize:9, color:'#5a8aaa',
              letterSpacing:2, textTransform:'uppercase', marginBottom:1 }}>{s.label}</div>
            <div style={{ fontFamily:"'Barlow Condensed'", fontSize:22, fontWeight:700,
              color: s.color, lineHeight:1,
              textShadow: s.value > 0 && s.color !== '#00b4ff' && s.color !== '#00ffd5'
                ? `0 0 12px ${s.color}88` : 'none'
            }}>{s.value}</div>
          </div>
        ))}

        {/* AI Diagnostics Button */}
        <button 
          onClick={() => setShowDiagnosticsModal(true)}
          style={{
            background: 'rgba(0, 255, 213, 0.04)',
            border: '1px solid rgba(0, 255, 213, 0.2)',
            borderRadius: 6,
            padding: '4px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            cursor: 'pointer',
            transition: 'all 0.2s ease-in-out',
            fontFamily: "'Share Tech Mono', monospace",
            height: 38,
            boxShadow: diagnostics.length > 0 ? '0 0 10px rgba(0, 255, 213, 0.1)' : 'none',
            outline: 'none',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(0, 255, 213, 0.12)';
            e.currentTarget.style.borderColor = 'rgba(0, 255, 213, 0.5)';
            e.currentTarget.style.boxShadow = '0 0 15px rgba(0, 255, 213, 0.25)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(0, 255, 213, 0.04)';
            e.currentTarget.style.borderColor = 'rgba(0, 255, 213, 0.2)';
            e.currentTarget.style.boxShadow = diagnostics.length > 0 ? '0 0 10px rgba(0, 255, 213, 0.1)' : 'none';
          }}
        >
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 8.5, color: '#5a8aaa', letterSpacing: 1.5, lineHeight: 1, marginBottom: 2 }}>AI DIAGNOSTICS</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#00ffd5', fontFamily: "'Barlow Condensed'", lineHeight: 1, letterSpacing: 1 }}>
              VIEW REPORTS
            </div>
          </div>
          {diagnostics.length > 0 && (
            <span style={{
              background: '#00ffd5',
              color: '#050a14',
              fontFamily: "'Share Tech Mono'",
              fontSize: 10,
              fontWeight: 'bold',
              borderRadius: 10,
              padding: '2px 6px',
              minWidth: 16,
              textAlign: 'center',
              boxShadow: '0 0 8px #00ffd5',
            }}>
              {diagnostics.length}
            </span>
          )}
        </button>
      </div>

      {/* Right: clock */}
      <div style={{ fontFamily:"'Share Tech Mono'", fontSize:13, color:'#00b4ff',
        letterSpacing:2, flexShrink:0 }}>
        {timeStr}
      </div>
    </div>
  )
}
