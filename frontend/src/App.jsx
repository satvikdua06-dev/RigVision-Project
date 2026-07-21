import { useEffect, useState } from 'react'
import Scene3D from './components/Scene3D.jsx'
import Sidebar from './components/Sidebar.jsx'
import TopBar from './components/TopBar.jsx'
import { useRigStore } from './stores/useRigStore.js'
import CameraFeeds from './components/CameraFeeds.jsx'
import SensorConsole from './components/SensorConsole.jsx'
import NotificationAlert from './components/NotificationAlert.jsx'
import SafetyHeatmap from './components/SafetyHeatmap.jsx'

const SENSOR_ROWS = [
  { icon: '🌡', lbl: 'Temp',  type: 'temperature', unit: '°C'  },
  { icon: '💨', lbl: 'H₂S',  type: 'gas_h2s',     unit: 'ppm' },
  { icon: '📳', lbl: 'Vibr', type: 'vibration',   unit: 'g'   },
  { icon: '🔊', lbl: 'Noise', type: 'noise',       unit: 'dB'  },
  { icon: '⚙',  lbl: 'Pres', type: 'pressure',    unit: 'bar' },
]
const SC = { normal: '#46b17f', warning: '#d9a64e', critical: '#e06054' }

const PROTO_BADGE = {
  modbus: { label: 'MB',     color: '#5b8def', bg: 'rgba(91,141,239,0.13)' },
  mqtt:   { label: 'MQ',     color: '#46b17f', bg: 'rgba(70,177,127,0.13)' },
  manual: { label: 'MAN',    color: '#d9a64e', bg: 'rgba(217,166,78,0.13)' },
  scada:  { label: 'SCADA',  color: '#9b8fc4', bg: 'rgba(155,143,196,0.13)' },
}

function SourceBadge({ source }) {
  if (!source) return null
  const s = PROTO_BADGE[source] || PROTO_BADGE.manual
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 8, letterSpacing: 0.6,
      color: s.color, background: s.bg,
      border: `1px solid ${s.color}40`,
      borderRadius: 3, padding: '0px 4px', marginLeft: 5,
      verticalAlign: 'middle',
    }}>{s.label}</span>
  )
}

function ZoneDetailPanel() {
  const selectedZone   = useRigStore(s => s.selectedZone)
  const zones          = useRigStore(s => s.zones)
  const clearSelection = useRigStore(s => s.clearSelection)

  if (!selectedZone) return null
  const zone = zones[selectedZone]
  if (!zone) return null

  const sc      = SC[zone.status] || 'var(--text-dim)'
  const sensors = SENSOR_ROWS.filter(s =>
    (zone.sensor_types || ['temperature', 'gas_h2s', 'vibration', 'noise']).includes(s.type)
  )

  return (
    <div style={{
      position: 'absolute', top: 14, left: 14, zIndex: 20,
      width: 218, pointerEvents: 'auto',
      background: 'var(--bg-panel)',
      border: '1px solid var(--border-solid)',
      borderLeft: `3px solid ${sc}`,
      borderRadius: 6,
      boxShadow: 'var(--shadow-panel)',
      fontFamily: 'var(--font-mono)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '9px 12px 8px',
        borderBottom: '1px solid var(--border-solid)',
      }}>
        <span style={{
          fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-ui)',
          color: sc, letterSpacing: 0.3,
        }}>
          {(zone.label || selectedZone.replace(/_/g, ' ')).toUpperCase()}
        </span>
        <button
          onClick={clearSelection}
          aria-label="Close zone detail"
          style={{
            background: 'transparent', border: 'none', color: 'var(--text-dim)',
            cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: '0 2px',
          }}
        >×</button>
      </div>

      {/* Status + occupancy */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '5px 12px', borderBottom: '1px solid var(--border-solid)',
        fontSize: 10, letterSpacing: 1,
      }}>
        <span style={{ color: sc, fontWeight: 600 }}>{(zone.status || '').toUpperCase()}</span>
        <span style={{ color: 'var(--text-muted)' }}>
          {zone.person_count ?? 0} PERS
          {zone.ppe_violations?.length > 0 && (
            <span style={{ color: 'var(--accent-red)', marginLeft: 6 }}>
              · PPE {zone.ppe_violations.length}⚠
            </span>
          )}
        </span>
      </div>

      {/* Sensor readings */}
      <div style={{ padding: '8px 12px', fontSize: 11.5, lineHeight: 2 }}>
        {sensors.map(({ icon, lbl, type, unit }) => {
          const val  = zone[type]
          const meta = zone.sensor_meta?.[type]
          let color  = 'var(--text-primary)'
          if (val != null && meta) {
            const hiCrit = meta.critical     != null && val >= meta.critical
            const hiWarn = meta.warning      != null && val >= meta.warning
            const loCrit = meta.critical_low != null && val <= meta.critical_low
            const loWarn = meta.warning_low  != null && val <= meta.warning_low
            if (hiCrit || loCrit) color = 'var(--accent-red)'
            else if (hiWarn || loWarn) color = 'var(--accent-amber)'
            else color = 'var(--accent-green)'
          }
          const source = zone.sensor_sources?.[type]
          return (
            <div key={type} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-muted)' }}>{icon} {lbl}</span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                <span style={{ color, fontWeight: color !== 'var(--text-primary)' ? 600 : 400 }}>
                  {val != null ? `${val} ${unit}` : '—'}
                </span>
                <SourceBadge source={source} />
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function App() {
  const connectToBackend = useRigStore(s => s.connectToBackend)
  const [route, setRoute]           = useState(window.location.hash)
  const [showHeatmap, setShowHeatmap] = useState(false)

  useEffect(() => {
    const onHash = () => setRoute(window.location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    connectToBackend()
  }, [connectToBackend])

  // Routing: the sensor console is served on its own dev port (5174) so it can sit
  // on a second screen alongside the 3D dashboard (5173). Hash route still works too.
  const isConsolePort = window.location.port === '5174'
  if (isConsolePort || route === '#/sensors') return <SensorConsole />

  return (
    <div style={{ width:'100vw', height:'100vh', display:'flex', flexDirection:'column', overflow:'hidden' }}>
      <TopBar showHeatmap={showHeatmap} onToggleHeatmap={() => setShowHeatmap(v => !v)} />
      <div style={{ flex:1, display:'flex', overflow:'hidden' }}>
        <Sidebar />

        {/* 3D Canvas takes remaining space */}
        <div style={{ flex:1, position:'relative' }}>
          <Scene3D />

          {/* Zone detail panel — anchored top-left of canvas, next to sidebar */}
          <ZoneDetailPanel />

          {/* Geospatial Safety Heatmap — anchored top-right of canvas */}
          {showHeatmap && <SafetyHeatmap onClose={() => setShowHeatmap(false)} />}

          {/* Overlay for Camera Feeds */}
          <CameraFeeds />

          {/* Center watermark */}
          <div style={{
            position:'absolute', bottom:16, left:'50%', transform:'translateX(-50%)', pointerEvents:'none',
            fontFamily:'var(--font-mono)', fontSize:10, color:'var(--text-dim)',
            letterSpacing:1,
            whiteSpace:'nowrap',
          }}>
            RigVision · LNMIIT · RIGVISION-3D · PHASE 1
          </div>

          {/* Controls hint */}
          <div style={{
            position:'absolute', bottom:16, right:80,
            fontFamily:'var(--font-mono)', fontSize:9.5,
            color:'var(--text-dim)', pointerEvents:'none',
            textAlign:'right', lineHeight:1.8, letterSpacing:0.5,
          }}>
            ORBIT: drag · ZOOM: scroll · PAN: right-drag<br/>
            CLICK zone/person to inspect
          </div>
        </div>
      </div>

      {/* Real-time Anomaly Notification Toast Overlay.
          The full diagnostics hub now lives in a separate window (/diagnostics),
          opened from the TopBar "View Reports" button or an anomaly toast. */}
      <NotificationAlert />
    </div>
  )
}
