import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../utils/api.js'

const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

const TYPE_META = {
  hot_work:       { label: 'HOT WORK',      color: 'var(--accent-red)'    },
  confined_space: { label: 'CONFINED SPACE', color: 'var(--accent-amber)'  },
  electrical:     { label: 'ELECTRICAL',     color: 'var(--accent-cobalt)' },
  excavation:     { label: 'EXCAVATION',     color: '#9b8fc4'              },
}

const STATUS_COLOR = {
  active:  'var(--accent-green)',
  closed:  'var(--text-dim)',
  expired: 'var(--accent-amber)',
}

function timeRemaining(endTime) {
  // end_time from backend is a Unix timestamp (seconds); multiply by 1000 for JS Date
  const end = typeof endTime === 'number' ? new Date(endTime * 1000) : new Date(endTime)
  const diffMs = end - new Date()
  if (diffMs <= 0) return 'EXPIRED'
  const h = Math.floor(diffMs / 3600000)
  const m = Math.floor((diffMs % 3600000) / 60000)
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const fieldStyle = {
  width: '100%',
  padding: '6px 9px',
  background: 'var(--bg-deep)',
  border: '1px solid var(--border-solid)',
  borderRadius: 2,
  color: 'var(--text-primary)',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  outline: 'none',
  boxSizing: 'border-box',
}

const labelStyle = {
  display: 'block',
  fontFamily: 'var(--font-mono)',
  fontSize: 10,
  color: 'var(--text-dim)',
  letterSpacing: 0.8,
  marginBottom: 4,
}

const BLANK_FORM = {
  type: 'hot_work',
  zone: 'zone_a',
  description: '',
  workers: '',
  duration_hours: 4,
  sensor_limits: { gas: '', temperature: '', vibration: '', pressure_low: '' },
}

const SENSOR_LIMIT_FIELDS = [
  { key: 'gas',          label: 'Max H₂S Gas',     unit: 'ppm',   min: 0,  max: 50,  step: 0.5, placeholder: 'e.g. 6' },
  { key: 'temperature',  label: 'Max Temperature',  unit: '°C',    min: 20, max: 200, step: 1,   placeholder: 'e.g. 55' },
  { key: 'vibration',    label: 'Max Vibration',    unit: 'g_rms', min: 0,  max: 20,  step: 0.5, placeholder: 'e.g. 4' },
  { key: 'pressure_low', label: 'Min Pressure',     unit: 'bar',   min: 0,  max: 15,  step: 0.5, placeholder: 'e.g. 3' },
]

export default function PermitPanel() {
  const [permits, setPermits]     = useState([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState(null)
  const [showForm, setShowForm]   = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [closing, setClosing]     = useState(null)
  const [filter, setFilter]       = useState('active')
  const [form, setForm]           = useState(BLANK_FORM)

  const fetchPermits = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/permits`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setPermits(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPermits()
    const id = setInterval(fetchPermits, 30000)
    return () => clearInterval(id)
  }, [fetchPermits])

  async function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const sensorLimits = {}
      for (const [k, v] of Object.entries(form.sensor_limits)) {
        if (v !== '' && v !== null && !isNaN(Number(v))) sensorLimits[k] = Number(v)
      }
      const body = {
        type:           form.type,
        zone:           form.zone,
        description:    form.description,
        workers:        form.workers.split(',').map(w => w.trim()).filter(Boolean),
        duration_hours: Number(form.duration_hours),
        sensor_limits:  sensorLimits,
      }
      const res = await fetch(`${API_BASE}/permits`, {
        method:  'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body:    JSON.stringify(body),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setShowForm(false)
      setForm(BLANK_FORM)
      await fetchPermits()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleClose(permitId) {
    setClosing(permitId)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/permits/${permitId}/close`, {
        method:  'PATCH',
        headers: authHeaders(),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await fetchPermits()
    } catch (e) {
      setError(e.message)
    } finally {
      setClosing(null)
    }
  }

  const filtered = permits.filter(p => filter === 'all' || p.status === filter)

  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>

      {/* Filter tabs */}
      <div style={{ display: 'flex', gap: 5, marginBottom: 10 }}>
        {['active', 'closed', 'all'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              flex: 1, padding: '5px 0',
              border: `1px solid ${filter === f ? 'var(--border-bright)' : 'var(--border-solid)'}`,
              borderRadius: 2, cursor: 'pointer',
              fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 0.8, textTransform: 'uppercase',
              background: filter === f ? 'var(--bg-elev)' : 'transparent',
              color:      filter === f ? 'var(--text-primary)' : 'var(--text-dim)',
            }}
          >{f === 'all' ? 'ALL' : f.toUpperCase()}</button>
        ))}
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          padding: '6px 10px', marginBottom: 10,
          background: 'rgba(224,96,84,0.12)', border: '1px solid var(--accent-red)',
          borderRadius: 2, color: 'var(--accent-red)', fontSize: 10,
        }}>{error}</div>
      )}

      {/* New permit toggle */}
      <button
        onClick={() => setShowForm(v => !v)}
        style={{
          width: '100%', padding: '7px 0', marginBottom: 12,
          border: `1px solid ${showForm ? 'var(--accent-cobalt)' : 'var(--border-bright)'}`,
          borderRadius: 2, cursor: 'pointer',
          background: showForm ? 'rgba(91,141,239,0.12)' : 'transparent',
          color:      showForm ? 'var(--accent-cobalt)' : 'var(--text-primary)',
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, letterSpacing: 0.8,
        }}
      >{showForm ? '✕  CANCEL' : '+  NEW PERMIT'}</button>

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleSubmit} style={{
          background: 'var(--bg-card)', border: '1px solid var(--border-solid)',
          borderRadius: 4, padding: '14px 13px', marginBottom: 14,
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: 1, marginBottom: 12 }}>
            NEW PERMIT-TO-WORK
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>TYPE</label>
            <select
              value={form.type}
              onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
              style={fieldStyle}
            >
              <option value="hot_work">Hot Work</option>
              <option value="confined_space">Confined Space Entry</option>
              <option value="electrical">Electrical</option>
              <option value="excavation">Excavation</option>
            </select>
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>ZONE</label>
            <select
              value={form.zone}
              onChange={e => setForm(f => ({ ...f, zone: e.target.value }))}
              style={fieldStyle}
            >
              <option value="zone_a">Zone A</option>
              <option value="zone_b">Zone B</option>
            </select>
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>DESCRIPTION</label>
            <input
              type="text" required
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              placeholder="Brief work description..."
              style={fieldStyle}
            />
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>WORKERS (comma-separated)</label>
            <input
              type="text"
              value={form.workers}
              onChange={e => setForm(f => ({ ...f, workers: e.target.value }))}
              placeholder="e.g. Vatsal, Arnim, Ayan"
              style={fieldStyle}
            />
          </div>

          <div style={{ marginBottom: 10 }}>
            <label style={labelStyle}>DURATION (hours)</label>
            <input
              type="number" min={0.5} max={24} step={0.5}
              value={form.duration_hours}
              onChange={e => setForm(f => ({ ...f, duration_hours: e.target.value }))}
              style={fieldStyle}
            />
          </div>

          {/* Sensor limits for this permit */}
          <div style={{
            marginBottom: 14,
            padding: '10px 10px 6px',
            background: 'var(--bg-deep)',
            border: '1px solid var(--border-solid)',
            borderRadius: 2,
          }}>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent-amber)',
              letterSpacing: 1, marginBottom: 8,
            }}>
              SENSOR LIMITS FOR THIS PERMIT
            </div>
            <div style={{ fontSize: 9, color: 'var(--text-dim)', marginBottom: 8, lineHeight: 1.5 }}>
              Checked only while this permit is active. Leave blank to use zone defaults.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 10px' }}>
              {SENSOR_LIMIT_FIELDS.map(({ key, label, unit, min, max, step, placeholder }) => (
                <div key={key}>
                  <label style={{ ...labelStyle, fontSize: 9 }}>
                    {label} <span style={{ color: 'var(--text-dim)' }}>({unit})</span>
                  </label>
                  <input
                    type="number" min={min} max={max} step={step}
                    value={form.sensor_limits[key]}
                    onChange={e => setForm(f => ({
                      ...f,
                      sensor_limits: { ...f.sensor_limits, [key]: e.target.value }
                    }))}
                    placeholder={placeholder}
                    style={{ ...fieldStyle, fontSize: 11 }}
                  />
                </div>
              ))}
            </div>
          </div>

          <button
            type="submit" disabled={submitting}
            style={{
              width: '100%', padding: '8px 0',
              border: '1px solid var(--accent-green)', borderRadius: 2,
              cursor: submitting ? 'wait' : 'pointer',
              background: 'rgba(70,177,127,0.12)', color: 'var(--accent-green)',
              fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, letterSpacing: 1,
              opacity: submitting ? 0.6 : 1,
            }}
          >{submitting ? 'ISSUING…' : 'ISSUE PERMIT'}</button>
        </form>
      )}

      {/* Loading / empty */}
      {loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 11, padding: 24 }}>LOADING…</div>
      )}
      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: 11, padding: 24 }}>NO PERMITS FOUND</div>
      )}

      {/* Permit cards */}
      {filtered.map(p => {
        const meta      = TYPE_META[p.type] || { label: p.type.toUpperCase(), color: 'var(--text-muted)' }
        const sc        = STATUS_COLOR[p.status] || 'var(--text-dim)'
        const remaining = p.status === 'active' ? timeRemaining(p.end_time) : null
        const isExpired = remaining === 'EXPIRED'

        return (
          <div
            key={p.permit_id}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border-solid)',
              borderLeft: `3px solid ${meta.color}`,
              borderRadius: 2, padding: '11px 12px', marginBottom: 8,
            }}
          >
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 7 }}>
              <span style={{
                fontSize: 9, letterSpacing: 1, fontWeight: 700,
                color: meta.color,
                border: `1px solid ${meta.color}40`,
                padding: '1px 5px', borderRadius: 2,
                background: `${meta.color}14`,
              }}>{meta.label}</span>

              <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                {remaining && (
                  <span style={{
                    fontSize: 10, fontVariantNumeric: 'tabular-nums', fontWeight: 600,
                    color: isExpired ? 'var(--accent-red)' : 'var(--accent-amber)',
                  }}>{remaining}</span>
                )}
                {p.status === 'active' ? (
                  <button
                    onClick={() => handleClose(p.permit_id)}
                    disabled={closing === p.permit_id}
                    style={{
                      padding: '2px 8px',
                      border: '1px solid var(--accent-red)', borderRadius: 2,
                      cursor: closing === p.permit_id ? 'wait' : 'pointer',
                      background: 'transparent', color: 'var(--accent-red)',
                      fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700, letterSpacing: 0.8,
                      opacity: closing === p.permit_id ? 0.6 : 1,
                    }}
                  >{closing === p.permit_id ? '…' : 'CLOSE'}</button>
                ) : (
                  <span style={{
                    fontSize: 9, letterSpacing: 1, color: sc,
                    border: `1px solid ${sc}40`, padding: '1px 5px', borderRadius: 2,
                  }}>{p.status.toUpperCase()}</span>
                )}
              </div>
            </div>

            {/* ID + Zone */}
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 5 }}>
              <span style={{ color: 'var(--text-dim)' }}>ID </span>
              <span style={{ color: 'var(--accent-cobalt)' }}>{p.permit_id}</span>
              <span style={{ color: 'var(--text-dim)', marginLeft: 10 }}>ZONE </span>
              <span>{p.zone.replace(/_/g, ' ').toUpperCase()}</span>
            </div>

            {/* Description */}
            {p.description && (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 5, lineHeight: 1.5 }}>
                {p.description}
              </div>
            )}

            {/* Workers */}
            {p.workers?.length > 0 && (
              <div style={{ fontSize: 10, marginBottom: p.requires_gas_clear ? 5 : 0 }}>
                <span style={{ color: 'var(--text-dim)' }}>WORKERS </span>
                <span style={{ color: 'var(--text-primary)' }}>{p.workers.join(', ')}</span>
              </div>
            )}

            {/* Permit-scoped sensor limits */}
            {p.sensor_limits && Object.keys(p.sensor_limits).length > 0 && (
              <div style={{
                marginTop: 6, padding: '6px 8px',
                background: 'rgba(217,166,78,0.07)',
                border: '1px solid rgba(217,166,78,0.25)',
                borderRadius: 2,
              }}>
                <div style={{ fontSize: 8, color: 'var(--accent-amber)', letterSpacing: 1, marginBottom: 5 }}>
                  PERMIT SENSOR LIMITS (active while open)
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 10px' }}>
                  {p.sensor_limits.gas          != null && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      <span style={{ color: 'var(--text-dim)' }}>H₂S </span>≤ {p.sensor_limits.gas} ppm
                    </span>
                  )}
                  {p.sensor_limits.temperature  != null && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      <span style={{ color: 'var(--text-dim)' }}>TEMP </span>≤ {p.sensor_limits.temperature} °C
                    </span>
                  )}
                  {p.sensor_limits.vibration    != null && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      <span style={{ color: 'var(--text-dim)' }}>VIB </span>≤ {p.sensor_limits.vibration} g
                    </span>
                  )}
                  {p.sensor_limits.pressure_low != null && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      <span style={{ color: 'var(--text-dim)' }}>PRES </span>≥ {p.sensor_limits.pressure_low} bar
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
