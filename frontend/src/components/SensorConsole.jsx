import { useEffect, useMemo, useState } from 'react'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

// Stable content hash (djb2) over a { sensor_id: value } map. Used to detect whether
// the slider values differ from what was last committed to Redis.
function hashValues(map) {
  const canonical = Object.keys(map || {})
    .sort()
    .map((k) => `${k}:${Number(map[k]).toFixed(2)}`)
    .join('|')
  let h = 5381
  for (let i = 0; i < canonical.length; i++) h = ((h << 5) + h + canonical.charCodeAt(i)) | 0
  return h
}

// When the console runs on its own port (5174), the back-link points to the
// dashboard server (5173). In single-server mode it falls back to the hash route.
const DASHBOARD_URL = window.location.port === '5174'
  ? `http://${window.location.hostname}:5173/`
  : '#/'

// Slider bounds: start at the normal-range floor, extend past `critical` so the
// operator can push a sensor into warning/critical to test the pipeline.
function sliderBounds(sensor) {
  const [lo, hi] = sensor.normal_range || [0, 100]
  const top = sensor.critical != null ? sensor.critical * 1.2 : hi * 1.5
  const min = lo
  const max = Math.max(top, hi)
  const span = max - min
  const step = span <= 20 ? 0.1 : span <= 200 ? 0.5 : 1
  return { min, max, step }
}

function valueColor(sensor, v) {
  if (v == null) return '#5a8aaa'
  if (sensor.critical != null && v >= sensor.critical) return '#ff3b3b'
  if (sensor.warning != null && v >= sensor.warning) return '#ffb300'
  return '#00e676'
}

function SensorSlider({ sensor, value, onChange }) {
  const { min, max, step } = sliderBounds(sensor)
  const color = valueColor(sensor, value)
  const pct = ((value - min) / (max - min)) * 100
  const warnPct = sensor.warning != null ? ((sensor.warning - min) / (max - min)) * 100 : null
  const critPct = sensor.critical != null ? ((sensor.critical - min) / (max - min)) * 100 : null

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontFamily: "'Share Tech Mono', monospace", fontSize: 12, color: '#e0f4ff' }}>
          {sensor.id}
          <span style={{ color: '#5a8aaa', fontSize: 10, marginLeft: 8 }}>{sensor.type}</span>
        </span>
        <span style={{ fontFamily: "'Barlow Condensed'", fontSize: 18, fontWeight: 700, color, minWidth: 70, textAlign: 'right' }}>
          {Number(value).toFixed(step < 1 ? 1 : 0)} <span style={{ fontSize: 11, color: '#5a8aaa' }}>{sensor.unit}</span>
        </span>
      </div>

      {/* track with warning/critical markers */}
      <div style={{ position: 'relative' }}>
        {warnPct != null && (
          <div title={`warning ${sensor.warning}`} style={{ position: 'absolute', left: `${warnPct}%`, top: -3, width: 2, height: 14, background: '#ffb300aa', zIndex: 2 }} />
        )}
        {critPct != null && (
          <div title={`critical ${sensor.critical}`} style={{ position: 'absolute', left: `${critPct}%`, top: -3, width: 2, height: 14, background: '#ff3b3baa', zIndex: 2 }} />
        )}
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          style={{ width: '100%', accentColor: color, cursor: 'pointer' }}
        />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: "'Share Tech Mono'", fontSize: 8.5, color: '#3a5a6a' }}>
        <span>{min}</span>
        <span>{max.toFixed(0)} {sensor.unit}</span>
      </div>
    </div>
  )
}

export default function SensorConsole() {
  const [zones, setZones] = useState({})
  const [values, setValues] = useState({})       // live slider positions { sensor_id: value }
  const [committed, setCommitted] = useState({}) // last snapshot pushed to Redis
  const [status, setStatus] = useState('loading')
  const [lastAction, setLastAction] = useState('')

  // Dirty = live sliders differ from what's committed to Redis (hash comparison).
  const dirty = useMemo(() => hashValues(values) !== hashValues(committed), [values, committed])
  const [diagRunning, setDiagRunning] = useState(false)
  const [diagResult, setDiagResult] = useState('')

  // Run on-demand diagnostics: backend threshold-checks every zone against the current
  // (committed) sensor data and fires the LLM only for flagged zones.
  const runDiagnostics = async () => {
    setDiagRunning(true)
    setDiagResult('')
    try {
      const res = await fetch(`${API_BASE}/diagnostics/run`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'all_clear') {
        setDiagResult('✓ All zones nominal — no issues')
      } else {
        setDiagResult(`⚠ ${data.alerts_published} zone(s) flagged: ${data.flagged.join(', ')} → diagnosing…`)
      }
    } catch (err) {
      console.error('[diagnostics] run failed', err)
      setDiagResult('Diagnostics request failed')
    } finally {
      setDiagRunning(false)
    }
  }

  // Load manifest (which sliders) + current values (initial positions)
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [mRes, vRes] = await Promise.all([
          fetch(`${API_BASE}/sensors/manifest`),
          fetch(`${API_BASE}/sensors`),
        ])
        const manifest = await mRes.json()
        const current = await vRes.json()
        if (cancelled) return

        const initial = {}
        const committedInit = {}
        for (const [, zone] of Object.entries(manifest.zones || {})) {
          for (const s of zone.sensors) {
            const existing = current[s.id]?.value
            const [lo, hi] = s.normal_range || [0, 100]
            initial[s.id] = existing != null ? existing : (lo + hi) / 2  // midpoint default
            if (existing != null) committedInit[s.id] = existing          // already in Redis
          }
        }
        setZones(manifest.zones || {})
        setValues(initial)
        setCommitted(committedInit)   // sliders with no Redis value start "unsaved"
        setStatus('ready')
      } catch (err) {
        console.error('[sensors] load failed', err)
        setStatus('error')
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // No heartbeat: manual set-points persist in Redis until changed (the pipeline treats
  // source="manual" readings as never-stale). A browser heartbeat would be unreliable
  // anyway — background tabs get their timers throttled, which caused values to expire.

  // Slider edits are LOCAL only — nothing is sent until "Send" is clicked.
  const setValue = (sensorId, value) => {
    setValues((v) => ({ ...v, [sensorId]: value }))
  }

  // Send: only push if the hash changed since the last commit.
  const sendToRedis = async () => {
    if (hashValues(values) === hashValues(committed)) {
      setLastAction('No changes to send')
      return
    }
    try {
      const snapshot = { ...values }
      await fetch(`${API_BASE}/sensors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ readings: snapshot, source: 'manual' }),
      })
      setCommitted(snapshot)
      setLastAction(`Sent ${Object.keys(snapshot).length} sensors ✓`)
    } catch (err) {
      console.error('[sensors] send failed', err)
      setLastAction('Send failed ✗')
    }
  }

  return (
    <div style={{ width: '100vw', height: '100vh', overflowY: 'auto', background: 'radial-gradient(circle at 30% 0%, #0a1828 0%, #050a14 60%)', color: '#e0f4ff' }}>
      {/* Header */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10, height: 56, display: 'flex', alignItems: 'center',
        padding: '0 24px', background: 'rgba(5,10,20,0.96)', borderBottom: '1px solid rgba(0,180,255,0.15)',
        backdropFilter: 'blur(20px)',
      }}>
        <span style={{ fontFamily: "'Barlow Condensed'", fontWeight: 700, fontSize: 20, color: '#00b4ff', letterSpacing: 3, textTransform: 'uppercase' }}>
          RIG<span style={{ color: '#00ffd5' }}>VISION</span>
        </span>
        <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa', marginLeft: 14, letterSpacing: 2 }}>
          SENSOR CONSOLE
        </span>
        <span style={{
          marginLeft: 14, fontFamily: "'Share Tech Mono'", fontSize: 9, letterSpacing: 1,
          color: '#ffb300', border: '1px solid #ffb30055', borderRadius: 4, padding: '2px 8px',
        }}>
          MANUAL INPUT
        </span>
        {/* Dirty indicator + Send/Diagnostics buttons */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          {diagResult && (
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 10, color: diagResult.startsWith('⚠') ? '#ffb300' : diagResult.startsWith('✓') ? '#00e676' : '#ff3b3b' }}>{diagResult}</span>
          )}
          {lastAction && (
            <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 10, color: '#5a8aaa' }}>{lastAction}</span>
          )}
          <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 10, letterSpacing: 1, color: dirty ? '#ffb300' : '#00e676' }}>
            {dirty ? '● UNSAVED CHANGES' : '✓ SYNCED'}
          </span>
          <button
            onClick={sendToRedis}
            disabled={status !== 'ready'}
            style={{
              fontFamily: "'Barlow Condensed'", fontSize: 14, fontWeight: 700, letterSpacing: 1,
              cursor: status === 'ready' ? 'pointer' : 'not-allowed',
              background: dirty ? '#00e676' : 'rgba(0,230,118,0.12)',
              color: dirty ? '#04121e' : '#00e676',
              border: `1px solid ${dirty ? '#00e676' : 'rgba(0,230,118,0.4)'}`,
              borderRadius: 6, padding: '7px 18px',
              boxShadow: dirty ? '0 0 14px rgba(0,230,118,0.4)' : 'none',
              transition: 'all 0.15s',
            }}
          >
            SEND TO REDIS
          </button>
          <button
            onClick={runDiagnostics}
            disabled={status !== 'ready' || diagRunning}
            title="Threshold-check all zones; LLM diagnoses flagged ones"
            style={{
              fontFamily: "'Barlow Condensed'", fontSize: 14, fontWeight: 700, letterSpacing: 1,
              cursor: (status === 'ready' && !diagRunning) ? 'pointer' : 'not-allowed',
              background: diagRunning ? 'rgba(255,179,0,0.15)' : 'rgba(0,180,255,0.12)',
              color: diagRunning ? '#ffb300' : '#00b4ff',
              border: `1px solid ${diagRunning ? '#ffb300' : 'rgba(0,180,255,0.5)'}`,
              borderRadius: 6, padding: '7px 18px',
              transition: 'all 0.15s',
            }}
          >
            {diagRunning ? 'RUNNING…' : 'RUN DIAGNOSTICS'}
          </button>
          <a href={DASHBOARD_URL} style={{
            fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#00ffd5',
            textDecoration: 'none', border: '1px solid rgba(0,255,213,0.3)', borderRadius: 6, padding: '6px 14px',
          }}>← 3D DASHBOARD</a>
        </div>
      </div>

      {status === 'loading' && <div style={{ padding: 40, fontFamily: "'Share Tech Mono'", color: '#5a8aaa' }}>Loading manifest…</div>}
      {status === 'error' && <div style={{ padding: 40, fontFamily: "'Share Tech Mono'", color: '#ff3b3b' }}>Failed to reach backend at {API_BASE}. Is it running?</div>}

      {status === 'ready' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 18, padding: 24 }}>
          {Object.entries(zones).map(([zid, zone]) => (
            <div key={zid} style={{
              background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(0,180,255,0.12)',
              borderRadius: 12, padding: '16px 18px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, paddingBottom: 10, borderBottom: '1px solid rgba(0,180,255,0.1)' }}>
                <span style={{ fontFamily: "'Barlow Condensed'", fontSize: 18, fontWeight: 700, letterSpacing: 1, color: '#e0f4ff' }}>
                  {zone.name}
                </span>
                <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 9, color: '#5a8aaa', letterSpacing: 1 }}>
                  {zid} · FLOOR {zone.floor} · {zone.sensors.length} SENSORS
                </span>
              </div>
              {zone.sensors.length === 0 ? (
                <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa', padding: '8px 0' }}>No sensors defined</div>
              ) : (
                zone.sensors.map((s) => (
                  <SensorSlider key={s.id} sensor={s} value={values[s.id] ?? 0} onChange={(v) => setValue(s.id, v)} />
                ))
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
