import { memo } from 'react'

// Radial tick on the ring at a given 0-1 fraction of the full circle.
// The SVG is rotated -90deg so SVG angle 0 maps to 12 o'clock visually.
// Angle pct*2π in SVG coords therefore maps to pct*360deg clockwise from top.
function RingTick({ pct, color, r, size }) {
  const angle = pct * 2 * Math.PI
  const cx = size / 2
  const cy = size / 2
  return (
    <line
      x1={cx + (r - 1.5) * Math.cos(angle)}
      y1={cy + (r - 1.5) * Math.sin(angle)}
      x2={cx + (r + 1.5) * Math.cos(angle)}
      y2={cy + (r + 1.5) * Math.sin(angle)}
      stroke={color} strokeWidth={1.5} strokeLinecap="round" opacity={0.85}
    />
  )
}

// SVG arc gauge — value → stroke-dashoffset via CSS transition (no JS RAF).
// The transition runs on the paint compositor thread, never blocking React.
// size prop controls diameter; r is derived with 6 px padding each side.
const CircularGauge = memo(function CircularGauge({ label, value, meta, size = 52 }) {
  const { min = 0, max = 100, warning, critical, warning_low, critical_low, unit = '' } = meta || {}

  const known = value != null && !Number.isNaN(Number(value))
  const num   = known ? Number(value) : 0
  const pct   = Math.max(0, Math.min(1, (num - min) / ((max - min) || 1)))

  const r    = (size - 12) / 2
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - pct)

  const isHighCrit = critical     != null && num >= critical
  const isHighWarn = warning      != null && num >= warning
  const isLowCrit  = critical_low != null && num <= critical_low
  const isLowWarn  = warning_low  != null && num <= warning_low

  const color = !known
    ? 'var(--text-dim)'
    : (isHighCrit || isLowCrit) ? 'var(--accent-red)'
    : (isHighWarn || isLowWarn) ? 'var(--accent-amber)'
    : 'var(--accent-green)'

  const valStr   = known ? String(value) : '—'
  const baseFs   = Math.round(size * 0.225)
  const fontSize = valStr.length > 4 ? baseFs - 2 : valStr.length > 3 ? baseFs - 1 : baseFs

  const toPct = v => v != null ? Math.max(0, Math.min(1, (v - min) / ((max - min) || 1))) : null
  const warnPct  = toPct(warning)
  const critPct  = toPct(critical)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
      <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
        {/* SVG rotated so arc starts at 12 o'clock */}
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}
          style={{ display: 'block', transform: 'rotate(-90deg)', overflow: 'visible' }}>
          {/* Track */}
          <circle cx={size / 2} cy={size / 2} r={r}
            fill="none" stroke="var(--border-solid)" strokeWidth={4} />
          {/* Fill */}
          <circle cx={size / 2} cy={size / 2} r={r}
            fill="none" stroke={color} strokeWidth={4} strokeLinecap="round"
            strokeDasharray={circ} strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 0.45s ease, stroke 0.3s ease' }} />
          {/* Threshold ticks — warning amber, critical red */}
          {warnPct != null && <RingTick pct={warnPct} color="var(--accent-amber)" r={r} size={size} />}
          {critPct != null && <RingTick pct={critPct} color="var(--accent-red)"   r={r} size={size} />}
        </svg>
        {/* Value text centered */}
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
        }}>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize, fontWeight: 600, color, lineHeight: 1 }}>
            {valStr}
          </span>
          {known && unit && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', marginTop: 2, lineHeight: 1 }}>
              {unit}
            </span>
          )}
        </div>
      </div>
      <span style={{
        fontFamily: 'var(--font-mono)', fontSize: 11,
        color: 'var(--text-muted)', letterSpacing: 0.3, marginTop: 4,
        textAlign: 'center', lineHeight: 1,
      }}>
        {label}
      </span>
    </div>
  )
})

export default CircularGauge
