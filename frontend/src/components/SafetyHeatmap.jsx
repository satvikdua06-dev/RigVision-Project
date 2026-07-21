/**
 * SafetyHeatmap — 2D top-down SVG floor plan overlay.
 *
 * Integrates: zone risk status · worker locations · active permit zones ·
 * compound risk severity · sensor value hotspots.
 *
 * Data sources: useRigStore (zones, persons, compoundRisk) + periodic
 * GET /api/permits for permit overlays.
 */
import { useState, useEffect, useCallback } from 'react'
import { useRigStore } from '../stores/useRigStore.js'
import { authHeaders } from '../utils/api.js'

const host     = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

// Zone layout constants (SVG units)
const W = 320, H = 380
const ZONE_H = 150, ZONE_W = W - 40
const ZONE_A = { x: 20, y: H - 40 - ZONE_H,      label: 'ZONE A · GROUND FLOOR', id: 'zone_a' }
const ZONE_B = { x: 20, y: H - 40 - ZONE_H * 2 - 20, label: 'ZONE B · FIRST FLOOR',  id: 'zone_b' }
const ZONES_LAYOUT = [ZONE_A, ZONE_B]

const STATUS_FILL = {
  normal:   'rgba(70,177,127,0.15)',
  warning:  'rgba(217,166,78,0.22)',
  critical: 'rgba(224,96,84,0.28)',
}
const STATUS_STROKE = {
  normal:   '#46b17f',
  warning:  '#d9a64e',
  critical: '#e06054',
}
const PERMIT_COLORS = {
  hot_work:       '#e06054',
  confined_space: '#d9a64e',
  electrical:     '#5b8def',
  excavation:     '#9b8fc4',
}
const SEV_COLOR = { CRITICAL: '#e06054', HIGH: '#d9a64e', NORMAL: '#46b17f' }

// Fallback thresholds matching zone_definitions.json — used only when sensor_meta
// is absent from the store (e.g., before first WS message arrives).
const DEFAULT_SENSOR_META = {
  gas_h2s:     { warning: 10, critical: 15 },
  temperature: { warning: 50, critical: 65 },
  vibration:   { warning: 5,  critical: 8  },
  pressure:    { warning: 20, critical: 25, warning_low: 4, critical_low: 2 },
}

function sensorStatus(val, meta) {
  if (val == null || !meta) return 'normal'
  if (meta.critical     != null && val >= meta.critical)     return 'critical'
  if (meta.warning      != null && val >= meta.warning)      return 'warning'
  if (meta.critical_low != null && val <= meta.critical_low) return 'critical'
  if (meta.warning_low  != null && val <= meta.warning_low)  return 'warning'
  return 'normal'
}

function workerPositions(zone, persons, index) {
  const zonePersons = persons.filter(p => p.zone === zone.id)
  const cols = 5
  return zonePersons.map((p, i) => ({
    person: p,
    cx: zone.x + 20 + (i % cols) * 28,
    cy: zone.y + 95 + Math.floor(i / cols) * 22,
  }))
}

function SensorBadge({ x, y, label, value, unit, status }) {
  const color = status === 'critical' ? '#e06054' : status === 'warning' ? '#d9a64e' : '#46b17f'
  return (
    <g>
      <rect x={x} y={y} width={54} height={22} rx={3}
        fill="rgba(15,20,30,0.82)" stroke={color} strokeWidth={0.8} />
      <text x={x + 4} y={y + 9} fontSize={7} fill="rgba(180,190,210,0.7)" fontFamily="monospace">{label}</text>
      <text x={x + 4} y={y + 18} fontSize={9} fill={color} fontFamily="monospace" fontWeight="600">
        {value != null ? `${Number(value).toFixed(1)} ${unit}` : '—'}
      </text>
    </g>
  )
}

export default function SafetyHeatmap({ onClose }) {
  const zones       = useRigStore(s => s.zones)
  const persons     = useRigStore(s => s.persons)
  const compoundRisk = useRigStore(s => s.compoundRisk)
  const [permits, setPermits] = useState([])

  const fetchPermits = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/permits`, { headers: authHeaders() })
      if (res.ok) setPermits(await res.json())
    } catch {}
  }, [])

  useEffect(() => {
    fetchPermits()
    const id = setInterval(fetchPermits, 20000)
    return () => clearInterval(id)
  }, [fetchPermits])

  const activePermits = permits.filter(p => p.status === 'active')
  const overallSev    = compoundRisk?.severity || 'NORMAL'
  const sevColor      = SEV_COLOR[overallSev] || '#46b17f'

  return (
    <div style={{
      position: 'absolute', top: 14, right: 14, zIndex: 25,
      width: W + 2, pointerEvents: 'auto',
      background: 'var(--bg-panel)',
      border: `1px solid ${sevColor}`,
      borderRadius: 6,
      boxShadow: 'var(--shadow-panel)',
      fontFamily: 'var(--font-mono)',
      userSelect: 'none',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '9px 12px 8px',
        borderBottom: '1px solid var(--border-solid)',
      }}>
        <div>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: 0.4 }}>
            GEOSPATIAL SAFETY HEATMAP
          </span>
          <span style={{
            marginLeft: 10, fontSize: 9, fontWeight: 700, letterSpacing: 1,
            color: sevColor,
            border: `1px solid ${sevColor}40`,
            background: `${sevColor}18`,
            padding: '1px 6px', borderRadius: 2,
          }}>{overallSev}</span>
        </div>
        <button onClick={onClose} style={{
          background: 'transparent', border: 'none', color: 'var(--text-dim)',
          cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: '0 2px',
        }}>×</button>
      </div>

      {/* SVG floor plan */}
      <svg width={W} height={H} style={{ display: 'block' }}>
        {/* Background */}
        <rect width={W} height={H} fill="var(--bg-deep)" />

        {/* Floor label */}
        <text x={W / 2} y={18} textAnchor="middle" fontSize={9}
          fill="rgba(150,165,185,0.5)" fontFamily="monospace" letterSpacing={2}>
          FACILITY FLOOR PLAN — TOP VIEW
        </text>

        {ZONES_LAYOUT.map(zLayout => {
          const zData    = zones[zLayout.id] || {}
          const workers  = workerPositions(zLayout, persons)

          // Permits active in this zone
          const zonePermits = activePermits.filter(p => p.zone === zLayout.id)

          // Sensor values
          const gas  = zData.gas_h2s
          const temp = zData.temperature
          const pres = zData.pressure
          const vib  = zData.vibration

          // Use thresholds from sensor_meta (same source as sensor console: zone_definitions.json via /api/sensors/manifest)
          const smeta = zData.sensor_meta || DEFAULT_SENSOR_META
          const gasStatus  = sensorStatus(gas,  smeta['gas_h2s']     || DEFAULT_SENSOR_META['gas_h2s'])
          const tempStatus = sensorStatus(temp, smeta['temperature'] || DEFAULT_SENSOR_META['temperature'])
          const vibStatus  = sensorStatus(vib,  smeta['vibration']   || DEFAULT_SENSOR_META['vibration'])
          const presStatus = sensorStatus(pres, smeta['pressure']    || DEFAULT_SENSOR_META['pressure'])

          // Derive zone status from live sensor thresholds (don't rely on CV pipeline zData.status which may lag)
          const _ss = [gasStatus, tempStatus, vibStatus, presStatus]
          const status = _ss.includes('critical') ? 'critical' : _ss.includes('warning') ? 'warning' : 'normal'
          const fill   = STATUS_FILL[status]   || STATUS_FILL.normal
          const stroke = STATUS_STROKE[status] || STATUS_STROKE.normal

          return (
            <g key={zLayout.id}>
              {/* Zone fill + border */}
              <rect
                x={zLayout.x} y={zLayout.y}
                width={ZONE_W} height={ZONE_H}
                fill={fill} stroke={stroke} strokeWidth={1.5} rx={4}
              />

              {/* Zone label */}
              <text x={zLayout.x + 8} y={zLayout.y + 14} fontSize={9}
                fill={stroke} fontFamily="monospace" fontWeight="700" letterSpacing={1}>
                {zLayout.label}
              </text>

              {/* Status badge */}
              <text x={zLayout.x + ZONE_W - 8} y={zLayout.y + 14} fontSize={9}
                textAnchor="end" fill={stroke} fontFamily="monospace" fontWeight="600">
                {status.toUpperCase()}
              </text>

              {/* Person count */}
              <text x={zLayout.x + 8} y={zLayout.y + 26} fontSize={8}
                fill="rgba(150,165,185,0.7)" fontFamily="monospace">
                {zData.person_count ?? 0} PERSONNEL · {zonePermits.length} PERMIT{zonePermits.length !== 1 ? 'S' : ''}
              </text>

              {/* Sensor badges row */}
              <SensorBadge x={zLayout.x + 8}   y={zLayout.y + 32} label="H₂S"  value={gas}  unit="ppm" status={gasStatus}  />
              <SensorBadge x={zLayout.x + 66}  y={zLayout.y + 32} label="TEMP" value={temp} unit="°C"  status={tempStatus} />
              <SensorBadge x={zLayout.x + 124} y={zLayout.y + 32} label="PRES" value={pres} unit="bar" status={presStatus} />
              <SensorBadge x={zLayout.x + 182} y={zLayout.y + 32} label="VIB"  value={vib}  unit="g"   status={vibStatus}  />

              {/* Permit overlays */}
              {zonePermits.map((p, pi) => {
                const pc = PERMIT_COLORS[p.type] || '#9b8fc4'
                const ox = zLayout.x + 8 + pi * 70
                const oy = zLayout.y + 60
                return (
                  <g key={p.permit_id}>
                    <rect x={ox} y={oy} width={64} height={26} rx={2}
                      fill={`${pc}18`} stroke={pc} strokeWidth={1} strokeDasharray="3,2" />
                    <text x={ox + 4} y={oy + 9} fontSize={7} fill={pc} fontFamily="monospace" fontWeight="700">
                      {p.type.replace(/_/g, ' ').toUpperCase().slice(0, 10)}
                    </text>
                    <text x={ox + 4} y={oy + 19} fontSize={7} fill="rgba(180,190,210,0.7)" fontFamily="monospace">
                      {p.permit_id.slice(0, 12)}
                    </text>
                  </g>
                )
              })}

              {/* Worker dots */}
              {workers.map(({ person, cx, cy }) => {
                const ppeAlert = person.ppe?.hat === 'missing' || person.ppe?.glasses === 'missing'
                return (
                  <g key={person.id}>
                    <circle cx={cx} cy={cy} r={7}
                      fill={ppeAlert ? 'rgba(224,96,84,0.25)' : 'rgba(91,141,239,0.2)'}
                      stroke={ppeAlert ? '#e06054' : '#5b8def'}
                      strokeWidth={1.2}
                    />
                    <text x={cx} y={cy + 3} textAnchor="middle"
                      fontSize={7} fill={ppeAlert ? '#e06054' : '#8aaee8'} fontFamily="monospace">
                      {(person.name || `P${person.id}`).slice(0, 2).toUpperCase()}
                    </text>
                  </g>
                )
              })}

              {/* PPE violation count */}
              {(zData.ppe_violations?.length > 0) && (
                <g>
                  <circle cx={zLayout.x + ZONE_W - 14} cy={zLayout.y + ZONE_H - 14} r={10}
                    fill="rgba(224,96,84,0.22)" stroke="#e06054" strokeWidth={1} />
                  <text x={zLayout.x + ZONE_W - 14} y={zLayout.y + ZONE_H - 10}
                    textAnchor="middle" fontSize={9} fill="#e06054" fontFamily="monospace" fontWeight="700">
                    {zData.ppe_violations.length}⚠
                  </text>
                </g>
              )}
            </g>
          )
        })}

        {/* Compound risk banner at bottom */}
        {compoundRisk && (
          <g>
            <rect x={0} y={H - 36} width={W} height={36} fill="rgba(10,14,22,0.92)" />
            <text x={12} y={H - 22} fontSize={8} fill="rgba(150,165,185,0.6)" fontFamily="monospace" letterSpacing={1}>
              COMPOUND RISK ENGINE
            </text>
            <text x={12} y={H - 10} fontSize={9} fill={sevColor} fontFamily="monospace" fontWeight="600">
              {compoundRisk.rules_fired?.length > 0
                ? compoundRisk.rules_fired.slice(0, 4).map(r => typeof r === 'string' ? r : r.rule_id).join(' · ')
                : 'No compound rules firing'}
            </text>
          </g>
        )}

        {/* Legend */}
        {[
          { color: '#46b17f', label: 'NORMAL' },
          { color: '#d9a64e', label: 'WARNING' },
          { color: '#e06054', label: 'CRITICAL' },
        ].map((item, i) => (
          <g key={item.label} transform={`translate(${W - 160 + i * 52}, ${H - 52})`}>
            <rect width={10} height={10} rx={2} fill={`${item.color}30`} stroke={item.color} strokeWidth={1} />
            <text x={13} y={9} fontSize={7} fill="rgba(150,165,185,0.7)" fontFamily="monospace">{item.label}</text>
          </g>
        ))}
      </svg>

      {/* Footer: permit legend */}
      {activePermits.length > 0 && (
        <div style={{
          padding: '6px 12px 8px',
          borderTop: '1px solid var(--border-solid)',
          display: 'flex', gap: 8, flexWrap: 'wrap',
        }}>
          {Object.entries(PERMIT_COLORS).map(([type, color]) => {
            const count = activePermits.filter(p => p.type === type).length
            if (!count) return null
            return (
              <span key={type} style={{
                fontSize: 9, fontFamily: 'var(--font-mono)', letterSpacing: 0.6,
                color, border: `1px dashed ${color}`,
                padding: '1px 6px', borderRadius: 2,
                background: `${color}14`,
              }}>
                {type.replace(/_/g, ' ').toUpperCase()} ×{count}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}
