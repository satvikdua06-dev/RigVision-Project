import { useEffect, useMemo, useRef, useState } from 'react'
import { authHeaders } from '../utils/api.js'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

function hashValues(map) {
  const canonical = Object.keys(map || {}).sort()
    .map((k) => `${k}:${Number(map[k]).toFixed(2)}`).join('|')
  let h = 5381
  for (let i = 0; i < canonical.length; i++) h = ((h << 5) + h + canonical.charCodeAt(i)) | 0
  return h
}

const DASHBOARD_URL = window.location.port === '5174'
  ? `http://${window.location.hostname}:5173/`
  : '#/'

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

// ── Protocol detection ─────────────────────────────────────────────────────────
// Derived from which zone the sensor belongs to. Zone A → Modbus, Zone B → MQTT.
function sensorProtocol(sensorId) {
  if (!sensorId) return 'manual'
  if (sensorId.endsWith('_a')) return 'modbus'
  if (sensorId.endsWith('_b')) return 'mqtt'
  return 'manual'
}

const PROTO_STYLE = {
  modbus: { label: 'MODBUS', color: '#5b8def', bg: 'rgba(91,141,239,0.12)' },
  mqtt:   { label: 'MQTT',   color: '#46b17f', bg: 'rgba(70,177,127,0.12)' },
  manual: { label: 'MANUAL', color: '#d9a64e', bg: 'rgba(217,166,78,0.12)' },
}

function ProtoBadge({ sensorId }) {
  const proto = sensorProtocol(sensorId)
  const s = PROTO_STYLE[proto]
  return (
    <span style={{
      fontFamily: 'var(--font-mono)', fontSize: 8, letterSpacing: 0.8,
      color: s.color, background: s.bg, border: `1px solid ${s.color}40`,
      borderRadius: 3, padding: '1px 5px', marginLeft: 6,
    }}>
      {s.label}
    </span>
  )
}

// ── Modbus register encoding ───────────────────────────────────────────────────
const MODBUS_REG_MAP = {
  temp_a:     { addr: 40001, idx: 0, dtype: 'int16',   scale: 0.1,  offset: 0 },
  vib_a:      { addr: 40002, idx: 1, dtype: 'int16',   scale: 0.01, offset: 0 },
  gas_a:      { addr: 40003, idx: 2, dtype: 'int16',   scale: 0.1,  offset: 0 },
  noise_a:    { addr: 40004, idx: 3, dtype: 'int16',   scale: 0.1,  offset: 0 },
  pressure_a: { addr: 40005, idx: 4, dtype: 'float32', scale: 1.0,  offset: 0 },
}

const MQTT_TOPIC_MAP = {
  temp_b:     'rig/zone_b/temp_b',
  vib_b:      'rig/zone_b/vib_b',
  gas_b:      'rig/zone_b/gas_b',
  noise_b:    'rig/zone_b/noise_b',
  pressure_b: 'rig/zone_b/pressure_b',
}

function encodeModbus(sensorId, value) {
  const reg = MODBUS_REG_MAP[sensorId]
  if (!reg) return null
  const raw = Math.round((value - reg.offset) / reg.scale)
  const hi = (raw >> 8) & 0xFF
  const lo = raw & 0xFF
  const hexRaw = raw.toString(16).toUpperCase().padStart(4, '0')
  return { addr: reg.addr, idx: reg.idx, raw, hexRaw, hi, lo }
}

function modbusFC03Frame(startIdx, count) {
  // MBAP: trans=0001 proto=0000 len=0006 unit=01  FC=03  addr  count
  const bytes = [0x00, 0x01, 0x00, 0x00, 0x00, 0x06, 0x01, 0x03,
    (startIdx >> 8) & 0xFF, startIdx & 0xFF,
    (count >> 8) & 0xFF, count & 0xFF]
  return bytes.map(b => b.toString(16).toUpperCase().padStart(2, '0')).join(' ')
}

// ── SCADA Trace Animation ──────────────────────────────────────────────────────
const STEP_DELAY = 350  // ms between steps

function ScadaTrace({ sensor, value, unit, activeStep, proto }) {
  if (!sensor || value == null) return null
  const enc = encodeModbus(sensor, value)
  const topic = MQTT_TOPIC_MAP[sensor]

  // Step definitions vary by protocol
  const steps = proto === 'modbus' ? [
    {
      label: 'User Input',
      icon: '●',
      color: '#5b8def',
      content: () => (
        <span>
          <span style={{ color: '#fff', fontWeight: 600 }}>{sensor}</span>
          {' = '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
        </span>
      ),
    },
    {
      label: 'POST /api/sensors',
      icon: '→',
      color: '#9b8fc4',
      content: () => (
        <span style={{ opacity: 0.85 }}>
          {'{'}"readings": {'{'}"{sensor}": {value.toFixed(2)}{'}'}, "source": "manual"{'}'}
        </span>
      ),
    },
    {
      label: 'Redis Setpoint Written',
      icon: '●',
      color: '#d9a64e',
      content: () => (
        <span>
          <span style={{ color: '#d9a64e' }}>HSET</span> scada:setpoints{' '}
          <span style={{ color: '#fff' }}>{sensor}</span>{' '}
          <span style={{ color: '#46b17f' }}>{value.toFixed(2)}</span>
        </span>
      ),
    },
    {
      label: 'Modbus Register Encoded',
      icon: '▣',
      color: '#5b8def',
      content: () => enc ? (
        <span>
          <span style={{ color: '#9b8fc4' }}>HR {enc.addr}</span>
          {' ← '}
          <span style={{ color: '#fff', fontWeight: 600 }}>{enc.raw}</span>
          {' (0x'}<span style={{ color: '#5b8def' }}>{enc.hexRaw}</span>{')'}
          {'  bytes: '}
          <span style={{ color: '#46b17f', letterSpacing: 1 }}>
            {enc.hi.toString(16).padStart(2,'0').toUpperCase()}{' '}
            {enc.lo.toString(16).padStart(2,'0').toUpperCase()}
          </span>
          {'  scale='}{ (1/MODBUS_REG_MAP[sensor]?.scale) }{'x'}
        </span>
      ) : null,
    },
    {
      label: 'SCADA Gateway FC03 Poll',
      icon: '⟳',
      color: '#46b17f',
      content: () => (
        <span>
          <span style={{ color: '#9b8fc4' }}>FC03</span> Read HR{' '}
          <span style={{ color: '#d9a64e' }}>
            {modbusFC03Frame(MODBUS_REG_MAP[sensor]?.idx ?? 0, 1)}
          </span>
        </span>
      ),
    },
    {
      label: 'SCADA Normalizer',
      icon: '◈',
      color: '#c9b84e',
      content: () => enc ? (
        <span>
          <span style={{ color: '#9b8fc4' }}>{enc.raw}</span>
          {' × '}
          <span style={{ color: '#5b8def' }}>{MODBUS_REG_MAP[sensor]?.scale}</span>
          {' = '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
          {'  [quality: '}
          <span style={{ color: '#46b17f' }}>good</span>
          {']'}
        </span>
      ) : null,
    },
    {
      label: 'Redis sensors:latest',
      icon: '●',
      color: '#d98a4e',
      content: () => (
        <span>
          <span style={{ color: '#d9a64e' }}>SET</span> rigvision:sensors:latest{' '}
          {'{'}"<span style={{ color: '#fff' }}>{sensor}</span>": {'{'}
          "value": <span style={{ color: '#46b17f' }}>{value.toFixed(2)}</span>,
          "source": <span style={{ color: '#5b8def' }}>"modbus"</span>
          {'}'}{'}'}
        </span>
      ),
    },
    {
      label: 'Frontend Updated',
      icon: '✓',
      color: '#46b17f',
      content: () => (
        <span>
          Zone A{' '}
          <span style={{ color: '#9b8fc4' }}>
            {sensor.replace('_a', '').replace('temp', 'temperature').replace('vib', 'vibration')
              .replace('gas', 'gas_h2s').replace('noise', 'noise').replace('pressure', 'pressure')}
          </span>
          {' = '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
          {'  via '}
          <span style={{ color: '#5b8def' }}>WebSocket</span>
        </span>
      ),
    },
  ] : proto === 'mqtt' ? [
    {
      label: 'User Input',
      icon: '●',
      color: '#46b17f',
      content: () => (
        <span>
          <span style={{ color: '#fff', fontWeight: 600 }}>{sensor}</span>
          {' = '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
        </span>
      ),
    },
    {
      label: 'POST /api/sensors',
      icon: '→',
      color: '#9b8fc4',
      content: () => (
        <span style={{ opacity: 0.85 }}>
          {'{'}"readings": {'{'}"{sensor}": {value.toFixed(2)}{'}'}, "source": "manual"{'}'}
        </span>
      ),
    },
    {
      label: 'MQTT Publish',
      icon: '↑',
      color: '#46b17f',
      content: () => (
        <span>
          <span style={{ color: '#46b17f' }}>PUBLISH</span>{' '}
          <span style={{ color: '#d9a64e' }}>{topic || `rig/zone_b/${sensor}`}</span>
          {'  payload: {'}"value": <span style={{ color: '#46b17f' }}>{value.toFixed(3)}</span>{'}'}
          {'  QoS=1 retain=true'}
        </span>
      ),
    },
    {
      label: 'SCADA MQTTWorker on_message',
      icon: '⟳',
      color: '#9b8fc4',
      content: () => (
        <span>
          <span style={{ color: '#9b8fc4' }}>on_message</span> callback triggered
          {' → queue.put(RawReading('}
          sensor_id=<span style={{ color: '#fff' }}>"{sensor}"</span>,
          value=<span style={{ color: '#46b17f' }}>{value.toFixed(3)}</span>
          {'))'}
        </span>
      ),
    },
    {
      label: 'SCADA Normalizer',
      icon: '◈',
      color: '#c9b84e',
      content: () => (
        <span>
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
          {'  ×1.0 + 0 = '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
          {'  [quality: '}
          <span style={{ color: '#46b17f' }}>good</span>
          {']  protocol='}
          <span style={{ color: '#46b17f' }}>mqtt</span>
        </span>
      ),
    },
    {
      label: 'Redis sensors:latest',
      icon: '●',
      color: '#d98a4e',
      content: () => (
        <span>
          "source": <span style={{ color: '#46b17f' }}>"mqtt"</span>
          {'  value: '}
          <span style={{ color: '#46b17f' }}>{value.toFixed(2)}</span>
        </span>
      ),
    },
    {
      label: 'Frontend Updated',
      icon: '✓',
      color: '#46b17f',
      content: () => (
        <span>
          Zone B  via <span style={{ color: '#46b17f' }}>WebSocket</span>
          {'  '}
          <span style={{ color: '#46b17f', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
        </span>
      ),
    },
  ] : [
    {
      label: 'User Input',
      icon: '●',
      color: '#d9a64e',
      content: () => (
        <span>
          <span style={{ color: '#fff' }}>{sensor}</span>
          {' = '}
          <span style={{ color: '#d9a64e', fontWeight: 700 }}>{value.toFixed(2)} {unit}</span>
        </span>
      ),
    },
    {
      label: 'POST /api/sensors',
      icon: '→',
      color: '#9b8fc4',
      content: () => (
        <span>source: <span style={{ color: '#d9a64e' }}>"manual"</span></span>
      ),
    },
    {
      label: 'Redis sensors:latest',
      icon: '●',
      color: '#d98a4e',
      content: () => (
        <span>
          "source": <span style={{ color: '#d9a64e' }}>"manual"</span>
        </span>
      ),
    },
    {
      label: 'Frontend Updated',
      icon: '✓',
      color: '#46b17f',
      content: () => <span style={{ color: '#46b17f' }}>WebSocket broadcast complete</span>,
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {steps.map((step, i) => {
        const done    = i < activeStep
        const active  = i === activeStep
        const pending = i > activeStep
        return (
          <div key={i} style={{ display: 'flex', gap: 0, opacity: pending ? 0.28 : 1, transition: 'opacity 0.3s' }}>
            {/* Connector line + icon */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 24, flexShrink: 0 }}>
              <div style={{
                width: 20, height: 20, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 10, fontWeight: 700,
                background: done ? step.color : active ? step.color + 'cc' : 'var(--bg-deep)',
                color: (done || active) ? '#000' : step.color,
                border: `1.5px solid ${step.color}`,
                flexShrink: 0,
                transition: 'background 0.3s',
                boxShadow: active ? `0 0 8px ${step.color}66` : 'none',
              }}>
                {done ? '✓' : step.icon}
              </div>
              {i < steps.length - 1 && (
                <div style={{
                  width: 1.5, flex: 1, minHeight: 8,
                  background: done ? step.color + '80' : 'var(--border)',
                  transition: 'background 0.3s',
                }} />
              )}
            </div>

            {/* Step content */}
            <div style={{ paddingLeft: 10, paddingBottom: i < steps.length - 1 ? 10 : 0, paddingTop: 2, flex: 1, minWidth: 0 }}>
              <div style={{
                fontFamily: 'var(--font-ui)', fontSize: 10, fontWeight: 600,
                color: (done || active) ? step.color : 'var(--text-muted)',
                letterSpacing: 0.5, marginBottom: 3,
              }}>
                {step.label}
              </div>
              {(done || active) && (
                <div style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9.5,
                  color: 'var(--text-muted)', lineHeight: 1.5,
                  wordBreak: 'break-all',
                  animation: active ? 'fadeIn 0.3s ease' : undefined,
                }}>
                  {step.content()}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Sensor Slider ──────────────────────────────────────────────────────────────
function SensorSlider({ sensor, value, onChange, onFocus }) {
  const { min, max, step } = sliderBounds(sensor)
  const color = valueColor(sensor, value)
  const pct = (x) => ((x - min) / (max - min)) * 100
  const warnPct    = sensor.warning     != null ? pct(sensor.warning)     : null
  const critPct    = sensor.critical    != null ? pct(sensor.critical)    : null
  const warnLowPct = sensor.warning_low != null ? pct(sensor.warning_low) : null
  const critLowPct = sensor.critical_low != null ? pct(sensor.critical_low) : null

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)', display: 'flex', alignItems: 'center' }}>
          {sensor.id}
          <span style={{ color: 'var(--text-muted)', fontSize: 10, marginLeft: 6 }}>{sensor.type}</span>
          <ProtoBadge sensorId={sensor.id} />
          {sensor.threshold_source?.level === 'device_manual' && (
            <span style={{ color: 'var(--accent-cobalt)', fontSize: 9, marginLeft: 6 }}>
              ⚙ {sensor.threshold_source.device}
            </span>
          )}
          {sensor.threshold_source?.level === 'zone_environmental' && (
            <span style={{ color: 'var(--text-muted)', fontSize: 9, marginLeft: 6 }}>⛨ HSE</span>
          )}
        </span>
        <span style={{ fontFamily: 'var(--font-ui)', fontSize: 18, fontWeight: 600, color, minWidth: 70, textAlign: 'right' }}>
          {Number(value).toFixed(step < 1 ? 1 : 0)}{' '}
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sensor.unit}</span>
        </span>
      </div>

      <div style={{ position: 'relative' }}>
        {warnPct    != null && <div title={`warning ${sensor.warning}`}     style={{ position: 'absolute', left: `${warnPct}%`,    top: -3, width: 2, height: 14, background: 'var(--accent-amber)', zIndex: 2 }} />}
        {critPct    != null && <div title={`critical ${sensor.critical}`}   style={{ position: 'absolute', left: `${critPct}%`,    top: -3, width: 2, height: 14, background: 'var(--accent-red)',   zIndex: 2 }} />}
        {warnLowPct != null && <div title={`low warning ${sensor.warning_low}`}  style={{ position: 'absolute', left: `${warnLowPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-amber)', zIndex: 2 }} />}
        {critLowPct != null && <div title={`low critical ${sensor.critical_low}`} style={{ position: 'absolute', left: `${critLowPct}%`, top: -3, width: 2, height: 14, background: 'var(--accent-red)',   zIndex: 2 }} />}
        <input
          type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => { onChange(parseFloat(e.target.value)); onFocus(sensor) }}
          onMouseDown={() => onFocus(sensor)}
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

// ── Main Component ─────────────────────────────────────────────────────────────
export default function SensorConsole() {
  const [zones, setZones]         = useState({})
  const [values, setValues]       = useState({})
  const [committed, setCommitted] = useState({})
  const [status, setStatus]       = useState('loading')
  const [lastAction, setLastAction] = useState('')
  const [diagRunning, setDiagRunning] = useState(false)
  const [diagResult, setDiagResult]   = useState('')

  // SCADA trace state
  const [traceActive, setTraceActive] = useState(false)
  const [traceSensor, setTraceSensor] = useState(null)   // full sensor object
  const [traceValue, setTraceValue]   = useState(null)
  const [traceStep, setTraceStep]     = useState(-1)
  const traceTimerRef = useRef(null)

  const dirty = useMemo(() => hashValues(values) !== hashValues(committed), [values, committed])

  // ── Load manifest + current values ──────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [mRes, vRes] = await Promise.all([
          fetch(`${API_BASE}/sensors/manifest`),
          fetch(`${API_BASE}/sensors`),
        ])
        const manifest = await mRes.json()
        const current  = await vRes.json()
        if (cancelled) return
        const initial = {}, committedInit = {}
        for (const [, zone] of Object.entries(manifest.zones || {})) {
          for (const s of zone.sensors) {
            const existing = current[s.id]?.value
            const [lo, hi] = s.normal_range || [0, 100]
            initial[s.id] = existing != null ? existing : (lo + hi) / 2
            if (existing != null) committedInit[s.id] = existing
          }
        }
        setZones(manifest.zones || {})
        setValues(initial)
        setCommitted(committedInit)
        setStatus('ready')
      } catch (err) {
        console.error('[sensors] load failed', err)
        setStatus('error')
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  // ── Run SCADA trace animation ────────────────────────────────────────────────
  function startTrace(sensor, value) {
    if (traceTimerRef.current) {
      clearInterval(traceTimerRef.current)
    }
    setTraceSensor(sensor)
    setTraceValue(value)
    setTraceStep(0)
    setTraceActive(true)

    const totalSteps = sensorProtocol(sensor?.id) === 'manual' ? 4
      : sensorProtocol(sensor?.id) === 'mqtt' ? 7 : 8

    let step = 0
    traceTimerRef.current = setInterval(() => {
      step++
      setTraceStep(step)
      if (step >= totalSteps - 1) {
        clearInterval(traceTimerRef.current)
        traceTimerRef.current = null
      }
    }, STEP_DELAY)
  }

  // ── Diagnostics ──────────────────────────────────────────────────────────────
  const runDiagnostics = async () => {
    setDiagRunning(true)
    setDiagResult('')
    try {
      const res = await fetch(`${API_BASE}/diagnostics/run`, { method: 'POST', headers: authHeaders() })
      if (res.status === 429) { setDiagResult('Rate limited — wait and retry'); return }
      const data = await res.json()
      setDiagResult(data.status === 'all_clear'
        ? 'All zones nominal'
        : `${data.alerts_published} zone(s) flagged: ${data.flagged.join(', ')}`)
    } catch {
      setDiagResult('Diagnostics request failed')
    } finally {
      setDiagRunning(false)
    }
  }

  // ── Send to Redis ─────────────────────────────────────────────────────────────
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
      setLastAction(`Sent ${Object.keys(snapshot).length} sensors`)
      // Animate trace for the last focused sensor, or first sensor
      if (traceSensor) startTrace(traceSensor, values[traceSensor.id])
    } catch {
      setLastAction('Send failed')
    }
  }

  const setValue = (sensorId, value) => {
    setValues((v) => ({ ...v, [sensorId]: value }))
  }

  const onSensorFocus = (sensor) => {
    // Start trace immediately when slider is touched
    if (values[sensor.id] != null) {
      startTrace(sensor, values[sensor.id])
    }
  }

  // Update trace value live as slider moves
  useEffect(() => {
    if (traceSensor && values[traceSensor.id] != null) {
      setTraceValue(values[traceSensor.id])
    }
  }, [values, traceSensor])

  return (
    <div style={{ width: '100vw', height: '100vh', overflowY: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)', color: 'var(--text-primary)' }}>
      {/* ── Header ── */}
      <div style={{
        flexShrink: 0, height: 56, display: 'flex', alignItems: 'center',
        padding: '0 24px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)',
        zIndex: 10,
      }}>
        <span style={{ fontFamily: 'var(--font-ui)', fontWeight: 700, fontSize: 18, color: 'var(--text-primary)', letterSpacing: 0.5 }}>
          RIG<span style={{ color: 'var(--accent-cobalt)' }}>VISION</span>
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', marginLeft: 14, letterSpacing: 1 }}>
          Sensor Console
        </span>
        <span style={{ marginLeft: 14, fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1, color: 'var(--accent-amber)', border: '1px solid var(--border)', borderRadius: 4, padding: '2px 8px' }}>
          MANUAL INPUT
        </span>

        {/* Protocol legend */}
        <div style={{ marginLeft: 24, display: 'flex', gap: 10, alignItems: 'center' }}>
          {Object.entries(PROTO_STYLE).map(([key, s]) => (
            <span key={key} style={{
              fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 0.8,
              color: s.color, background: s.bg,
              border: `1px solid ${s.color}40`, borderRadius: 3, padding: '2px 7px',
            }}>{s.label}</span>
          ))}
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          {diagResult && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: diagResult.includes('flagged') ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
              {diagResult}
            </span>
          )}
          {lastAction && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{lastAction}</span>
          )}
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 1, color: dirty ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
            {dirty ? '● UNSAVED' : '✓ SYNCED'}
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
              borderRadius: 6, padding: '7px 18px', transition: 'all 0.15s',
            }}
          >SEND TO REDIS</button>
          <button
            onClick={runDiagnostics}
            disabled={status !== 'ready' || diagRunning}
            style={{
              fontFamily: 'var(--font-ui)', fontSize: 13, fontWeight: 600, letterSpacing: 0.3,
              cursor: (status === 'ready' && !diagRunning) ? 'pointer' : 'not-allowed',
              background: 'var(--bg-card)',
              color: diagRunning ? 'var(--accent-amber)' : 'var(--accent-cobalt)',
              border: `1px solid ${diagRunning ? 'var(--accent-amber)' : 'var(--border-bright)'}`,
              borderRadius: 6, padding: '7px 18px', transition: 'all 0.15s',
            }}
          >{diagRunning ? 'RUNNING...' : 'RUN DIAGNOSTICS'}</button>
          <a href={DASHBOARD_URL} style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
            textDecoration: 'none', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px',
          }}>← 3D DASHBOARD</a>
        </div>
      </div>

      {/* ── Body: sliders (left) + SCADA trace (right) ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Sliders panel */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {status === 'loading' && (
            <div style={{ padding: 40, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>Loading manifest...</div>
          )}
          {status === 'error' && (
            <div style={{ padding: 40, fontFamily: 'var(--font-mono)', color: 'var(--accent-red)' }}>
              Failed to reach backend at {API_BASE}
            </div>
          )}
          {status === 'ready' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 18 }}>
              {Object.entries(zones).map(([zid, zone]) => (
                <div key={zid} style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderRadius: 10, padding: '16px 18px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontFamily: 'var(--font-ui)', fontSize: 17, fontWeight: 600, letterSpacing: 0.3 }}>
                      {zone.name}
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1 }}>
                      {zid} · FLOOR {zone.floor} · {zone.sensors.length}
                    </span>
                  </div>
                  {zone.sensors.map((s) => (
                    <SensorSlider
                      key={s.id}
                      sensor={s}
                      value={values[s.id] ?? 0}
                      onChange={(v) => setValue(s.id, v)}
                      onFocus={onSensorFocus}
                    />
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ── SCADA Trace panel ── */}
        <div style={{
          width: 340, flexShrink: 0,
          borderLeft: '1px solid var(--border)',
          background: 'var(--bg-panel)',
          display: 'flex', flexDirection: 'column',
          overflowY: 'auto',
        }}>
          {/* Trace header */}
          <div style={{
            padding: '14px 16px 10px',
            borderBottom: '1px solid var(--border)',
            position: 'sticky', top: 0, background: 'var(--bg-panel)', zIndex: 2,
          }}>
            <div style={{ fontFamily: 'var(--font-ui)', fontSize: 12, fontWeight: 600, letterSpacing: 0.5, color: 'var(--text-primary)' }}>
              SCADA PIPELINE TRACE
            </div>
            {traceActive && traceSensor && (
              <div style={{ marginTop: 4, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
                <span style={{ color: 'var(--text-primary)' }}>{traceSensor.id}</span>
                {' = '}
                <span style={{ color: valueColor(traceSensor, traceValue) }}>
                  {traceValue != null ? traceValue.toFixed(2) : '—'} {traceSensor.unit}
                </span>
                {'  '}
                <span style={PROTO_STYLE[sensorProtocol(traceSensor.id)] ? {
                  ...PROTO_STYLE[sensorProtocol(traceSensor.id)],
                  fontFamily: 'var(--font-mono)', fontSize: 8, letterSpacing: 0.8,
                  padding: '1px 5px', borderRadius: 3,
                  border: `1px solid ${PROTO_STYLE[sensorProtocol(traceSensor.id)].color}40`,
                } : {}}>
                  {PROTO_STYLE[sensorProtocol(traceSensor.id)]?.label}
                </span>
              </div>
            )}
          </div>

          {/* Trace body */}
          <div style={{ flex: 1, padding: '16px 16px 24px', overflowY: 'auto' }}>
            {!traceActive ? (
              <div style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.8, paddingTop: 8 }}>
                <div style={{ marginBottom: 16 }}>Move any slider to see the live SCADA pipeline trace.</div>
                <div style={{ borderLeft: '2px solid var(--border)', paddingLeft: 12, lineHeight: 2 }}>
                  <div>Zone A sensors → <span style={{ color: PROTO_STYLE.modbus.color }}>Modbus TCP</span></div>
                  <div>Zone B sensors → <span style={{ color: PROTO_STYLE.mqtt.color }}>MQTT</span></div>
                  <div>Others → <span style={{ color: PROTO_STYLE.manual.color }}>Manual / Redis direct</span></div>
                </div>
                <div style={{ marginTop: 16, fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.7 }}>
                  <div>Each step shows the real protocol encoding:</div>
                  <div style={{ marginTop: 6 }}>Modbus: register address, raw int16, hex bytes, FC03 frame</div>
                  <div>MQTT: topic, JSON payload, QoS, on_message callback</div>
                </div>
              </div>
            ) : (
              <ScadaTrace
                sensor={traceSensor?.id}
                value={traceValue}
                unit={traceSensor?.unit}
                activeStep={traceStep}
                proto={sensorProtocol(traceSensor?.id)}
              />
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
      `}</style>
    </div>
  )
}
