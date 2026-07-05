import { memo } from 'react'

// CSS-only animated status badge — no JS animation loop, safe to render at 10 Hz.
// Uses transform + opacity (GPU-composited) so it never triggers layout.
const STATUS_CFG = {
  normal:   { color: 'var(--accent-green)', label: 'NORMAL',   ring: false, period: '2s'   },
  warning:  { color: 'var(--accent-amber)', label: 'WARNING',  ring: true,  period: '1.8s' },
  critical: { color: 'var(--accent-red)',   label: 'CRITICAL', ring: true,  period: '1s'   },
}

const StatusBadge = memo(function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || {
    color: 'var(--text-dim)',
    label: (status || 'UNKNOWN').toUpperCase(),
    ring: false,
  }

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      color: cfg.color, fontFamily: 'var(--font-mono)',
      fontSize: 10, letterSpacing: 1, textTransform: 'uppercase', fontWeight: 600,
    }}>
      {/* Dot + expanding ring */}
      <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 14, height: 14, flexShrink: 0 }}>
        {cfg.ring && (
          <span style={{
            position: 'absolute', inset: 0, borderRadius: '50%',
            border: `1px solid ${cfg.color}`,
            animation: `sb-ring ${cfg.period} ease-out infinite`,
            transformOrigin: 'center',
          }} />
        )}
        <span style={{
          width: cfg.ring ? 6 : 5, height: cfg.ring ? 6 : 5, borderRadius: '50%',
          background: cfg.color, flexShrink: 0,
          animation: cfg.ring ? `sb-pulse ${cfg.period} ease-in-out infinite` : 'none',
        }} />
      </span>
      {cfg.label}
    </span>
  )
})

export default StatusBadge
