import { useEffect, useMemo, useState } from 'react'
import { authHeaders } from '../utils/api.js'

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

// Slider bounds: extend past `critical` (high) and below `critical_low` (when the
// sensor has a low-side limit) so the operator can push it into either warning or
// critical band — high OR low — to test the pipeline.
function sliderBounds(sensor) {
  const [lo, hi] = sensor.normal_range || [0, 100]
  const top = sensor.critical != null ? sensor.critical * 1.2 : hi * 1.5
  const min = sensor.critical_low != null ? Math.min(lo, sensor.critical_low * 0.5) : lo
  const max = Math.max(top, hi)
  const span = max - min
  const step = span <= 20 ? 0.1 : span <= 200 ? 0.5 : 1
  return { min, max, step }
}

function valueColor(sensor, v) {
  if (v == null) return 'var(--text-muted)'
  if (sensor.critical != null && v >= sensor.critical) return 'var(--accent-red)'
  if (sensor.critical_low != null && v <= sensor.critical_low) return 'var(--accent-red)'
  if (sensor.warning != null && v >= sensor.warning) return 'var(--accent-amber)'
  if (sensor.warning_low != null && v <= sensor.warning_low) return 'var(--accent-amber)'
  return 'var(--accent-green)'
}

function SensorSlider({ sensor, value, onChange }) {
  const { min, max, step } = sliderBounds(sensor)
  const color = valueColor(sensor, value)
  const pct = (x) => ((x - min) / (max - min)) * 100
  const warnPct = sensor.warning != null ? pct(sensor.warning) : null
  const critPct = sensor.critical != null ? pct(sensor.critical) : null
  const warnLowPct = sensor.warning_low != null ? pct(sensor.warning_low) : null
  const critLowPct = sensor.critical_low != null ? pct(sensor.critical_low) : null

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span
          title={sensor.threshold_source ? sensor.threshold_source.reason : undefined}
          style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)' }}
        >
          {sensor.id}
          <span style={{ color: 'var(--text-muted)', fontSize: 10, marginLeft: 8 }}>{sensor.type}</span>
          {sensor.threshold_source?.level === 'device_manual' && (
            <span style={{ color: 'var(--accent-cobalt)', fontSize: 9, marginLeft: 6 }}>⚙ {sensor.threshold_source.device}</span>
          )}
          {sensor.threshold_source?.level === 'zone_environmental' && (
            <span style={{ color: 'var(--text-muted)', fontSize: 9, marginLeft: 6 }}>⛨ HSE area limit</span>
          )}
        </span>
        <span style={{ fontFamily: "var(--font-ui)", fontSize: 18, fontWeight: 600, color, minWidth: 70, textAlign: 'right' }}>
          {Number(value).toFixed(step < 1 ? 1 : 0)} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sensor.unit}</span>
        </span>
      </div>

      {/* track with warning/critical markers */}
      <div style={{ position: 'relative' }}>
        {warnPct != null && (
          <div title={`warning ${sensor.warning}`} style={{ position: 'absolute', left: `${warnPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-amber)', zIndex: 2 }} />
        )}
        {critPct != null && (
          <div title={`critical ${sensor.critical}`} style={{ position: 'absolute', left: `${critPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-red)', zIndex: 2 }} />
        )}
        {warnLowPct != null && (
          <div title={`low warning ${sensor.warning_low}`} style={{ position: 'absolute', left: `${warnLowPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-amber)', zIndex: 2 }} />
        )}
        {critLowPct != null && (
          <div title={`low critical ${sensor.critical_low}`} style={{ position: 'absolute', left: `${critLowPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-red)', zIndex: 2 }} />
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
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 8.5, color: 'var(--text-dim)' }}>
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
      const res = await fetch(`${API_BASE}/diagnostics/run`, { method: 'POST', headers: authHeaders() })
      if (res.status === 429) {
        setDiagResult('Rate limited — wait a moment and retry')
        return
      }
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
        headers: authHeaders({ 'Content-Type': 'application/json' }),
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
    <div style={{ width: '100vw', height: '100vh', overflowY: 'auto', background: 'var(--bg-deep)', color: 'var(--text-primary)' }}>
      {/* Header */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 10, height: 56, display: 'flex', alignItems: 'center',
        padding: '0 24px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)',
      }}>
        <span style={{ fontFamily: 'var(--font-ui)', fontWeight: 700, fontSize: 18, color: 'var(--text-primary)', letterSpacing: 0.5 }}>
          RIG<span style={{ color: 'var(--accent-cobalt)' }}>VISION</span>
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginLeft: 14, letterSpacing: 1, textTransform: 'uppercase' }}>
          Sensor Console
        </span>
        <span style={{
          marginLeft: 14, fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
          color: 'var(--accent-amber)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 8px',
        }}>
          MANUAL INPUT
        </span>
        {/* Dirty indicator + Send/Diagnostics buttons */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          {diagResult && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: diagResult.startsWith('⚠') ? 'var(--accent-amber)' : diagResult.startsWith('✓') ? 'var(--accent-green)' : 'var(--accent-red)' }}>{diagResult}</span>
          )}
          {lastAction && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{lastAction}</span>
          )}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1, color: dirty ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
            {dirty ? '● UNSAVED CHANGES' : '✓ SYNCED'}
          </span>
          <button
            onClick={sendToRedis}
            disabled={status !== 'ready'}
            style={{
              fontFamily: 'var(--font-ui)', fontSize: 13, fontWeight: 600, letterSpacing: 0.3,
              cursor: status === 'ready' ? 'pointer' : 'not-allowed',
              background: dirty ? 'var(--accent-green)' : 'var(--bg-card)',
              color: dirty ? 'var(--bg-deep)' : 'var(--accent-green)',
              border: `1px solid ${dirty ? 'var(--accent-green)' : 'var(--border)'}`,
              borderRadius: 6, padding: '7px 18px',
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
              fontFamily: 'var(--font-ui)', fontSize: 13, fontWeight: 600, letterSpacing: 0.3,
              cursor: (status === 'ready' && !diagRunning) ? 'pointer' : 'not-allowed',
              background: 'var(--bg-card)',
              color: diagRunning ? 'var(--accent-amber)' : 'var(--accent-cobalt)',
              border: `1px solid ${diagRunning ? 'var(--accent-amber)' : 'var(--border-bright)'}`,
              borderRadius: 6, padding: '7px 18px',
              transition: 'all 0.15s',
            }}
          >
            {diagRunning ? 'RUNNING…' : 'RUN DIAGNOSTICS'}
          </button>
          <a href={DASHBOARD_URL} style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
            textDecoration: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px',
          }}>← 3D DASHBOARD</a>
        </div>
      </div>

      {status === 'loading' && <div style={{ padding: 40, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>Loading manifest…</div>}
      {status === 'error' && <div style={{ padding: 40, fontFamily: 'var(--font-mono)', color: 'var(--accent-red)' }}>Failed to reach backend at {API_BASE}. Is it running?</div>}

      {status === 'ready' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(360px, 1fr))', gap: 18, padding: 24 }}>
          {Object.entries(zones).map(([zid, zone]) => (
            <div key={zid} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 10, padding: '16px 18px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}>
                <span style={{ fontFamily: 'var(--font-ui)', fontSize: 17, fontWeight: 600, letterSpacing: 0.3, color: 'var(--text-primary)' }}>
                  {zone.name}
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1 }}>
                  {zid} · FLOOR {zone.floor} · {zone.sensors.length} SENSORS
                </span>
              </div>
              {zone.sensors.length === 0 ? (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', padding: '8px 0' }}>No sensors defined</div>
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
