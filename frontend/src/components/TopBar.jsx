import { useRigStore } from '../stores/useRigStore.js'
import useAuthStore from '../stores/useAuthStore.js'
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export default function TopBar() {
  const zones = useRigStore(s => s.zones)
  const persons = useRigStore(s => s.persons)
  const diagnostics = useRigStore(s => s.diagnostics) || []
  const setShowDiagnosticsModal = useRigStore(s => s.setShowDiagnosticsModal)

  const { user, logout } = useAuthStore()
  const navigate = useNavigate()
  const [showUserMenu, setShowUserMenu] = useState(false)

  const criticalZones = Object.values(zones).filter(z => z.status === 'critical').length
  const warningZones = Object.values(zones).filter(z => z.status === 'warning').length
  // PPE alerts from live per-person Body Gear/Hat detection (p.ppe.{backpack,hat}).
  const alertPersons = persons.filter(p => p.ppe?.backpack === 'missing' || p.ppe?.hat === 'missing').length

  // Status values map onto the Industrial Slate accent palette (no neon).
  const OK = 'var(--text-primary)'
  const stats = [
    { label: 'Zones', value: Object.keys(zones).length, color: 'var(--text-primary)' },
    { label: 'Critical', value: criticalZones, color: criticalZones > 0 ? 'var(--accent-red)' : OK },
    { label: 'Warnings', value: warningZones, color: warningZones > 0 ? 'var(--accent-amber)' : OK },
    { label: 'Personnel', value: persons.length, color: 'var(--accent-cobalt)' },
    { label: 'PPE Alerts', value: alertPersons, color: alertPersons > 0 ? 'var(--accent-red)' : OK },
  ]

  // Clean clock implementation that updates every second
  const [timeStr, setTimeStr] = useState("")
  useEffect(() => {
    const update = () => {
      setTimeStr(new Date().toLocaleTimeString('en-IN', { hour12: false }) + " IST")
    }
    update()
    const interval = setInterval(update, 1000)
    return () => clearInterval(interval)
  }, [])

  return (
    <div style={{
      height: 54, display: 'flex', alignItems: 'center',
      background: 'var(--glass-panel)',
      backdropFilter: 'blur(16px) saturate(120%)',
      WebkitBackdropFilter: 'blur(16px) saturate(120%)',
      borderBottom: '1px solid var(--border)',
      padding: '0 22px', gap: 0, flexShrink: 0,
      userSelect: 'none', position: 'relative', zIndex: 5,
    }}>
      {/* Left: Logo & Info */}
      <div style={{ flexShrink: 0, display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{
          fontFamily: 'var(--font-ui)', fontWeight: 700, fontSize: 17,
          color: 'var(--text-primary)', letterSpacing: 0.5,
        }}>RIG<span style={{ color: 'var(--accent-cobalt)' }}>VISION</span></span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 9,
          color: 'var(--text-dim)', letterSpacing: 1, textTransform: 'uppercase'
        }}>v1.0 · Phase-1</span>
      </div>

      <div style={{ width: 1, height: 28, background: 'var(--border)', marginLeft: 24, marginRight: 24 }} />

      {/* Middle-Left: Telemetry Stats */}
      <div style={{ display: 'flex', gap: 32, alignItems: 'center' }}>
        {stats.map((s, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)',
              letterSpacing: 1.5, textTransform: 'uppercase'
            }}>{s.label}</div>
            <div style={{
              fontFamily: 'var(--font-ui)', fontSize: 20, fontWeight: 600,
              color: s.color, lineHeight: 1.1
            }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Spacer to push controls to the right */}
      <div style={{ flex: 1 }} />

      {/* Middle-Right: Action Controls Group */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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
            height: 38,
            boxSizing: 'border-box',
            transition: 'border-color 0.15s, background-color 0.15s',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--border-bright)';
            e.currentTarget.style.backgroundColor = 'var(--bg-panel)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--border)';
            e.currentTarget.style.backgroundColor = 'var(--bg-card)';
          }}
        >
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 8.5, color: 'var(--text-muted)', letterSpacing: 1.2, lineHeight: 1, marginBottom: 3, fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>Sensor Input</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', lineHeight: 1, letterSpacing: 0.3 }}>
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
            <div style={{ fontSize: 8.5, color: 'var(--text-muted)', letterSpacing: 1.2, lineHeight: 1, marginBottom: 3, fontFamily: 'var(--font-mono)', textTransform: 'uppercase' }}>AI Diagnostics</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-ui)', lineHeight: 1, letterSpacing: 0.3 }}>
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

      <div style={{ width: 1, height: 28, background: 'var(--border)', marginLeft: 20, marginRight: 20 }} />

      {/* Right: User Menu & System Info */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexShrink: 0 }}>
        {/* User Profile Menu */}
        {user && (
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                padding: '6px 12px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontFamily: 'var(--font-ui)',
                fontSize: 13,
                color: 'var(--text-primary)',
                transition: 'border-color 0.15s, background 0.15s',
                outline: 'none',
                height: 38,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--bg-panel)';
                e.currentTarget.style.borderColor = 'var(--border-bright)';
              }}
              onMouseLeave={(e) => {
                if (!showUserMenu) {
                  e.currentTarget.style.background = 'var(--bg-card)';
                  e.currentTarget.style.borderColor = 'var(--border)';
                }
              }}
            >
              <div style={{
                width: 24,
                height: 24,
                borderRadius: '50%',
                background: 'var(--accent-cobalt)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'white',
                fontSize: 11,
                fontWeight: 600,
              }}>
                {user.username?.[0]?.toUpperCase() || 'U'}
              </div>
              <span>{user.username}</span>
              <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>▼</span>
            </button>

            {/* Dropdown Menu */}
            {showUserMenu && (
              <div
                style={{
                  position: 'absolute',
                  top: 44,
                  right: 0,
                  background: 'var(--glass-panel)',
                  backdropFilter: 'blur(16px)',
                  WebkitBackdropFilter: 'blur(16px)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  minWidth: 200,
                  boxShadow: '0 10px 30px rgba(0,0,0,0.3)',
                  zIndex: 100,
                }}
              >
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>LOGGED IN AS</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', marginTop: 4 }}>{user.username}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{user.email}</div>
                  <div style={{ fontSize: 10, background: 'var(--accent-cobalt)', color: 'white', display: 'inline-block', padding: '2px 8px', borderRadius: 3, marginTop: 6, textTransform: 'uppercase', fontWeight: 600 }}>
                    {user.role || 'User'}
                  </div>
                </div>

                <button
                  onClick={async () => {
                    setShowUserMenu(false);
                    await logout();
                    navigate('/login');
                  }}
                  style={{
                    width: '100%',
                    background: 'transparent',
                    border: 'none',
                    padding: '10px 16px',
                    textAlign: 'left',
                    cursor: 'pointer',
                    color: 'var(--accent-red)',
                    fontFamily: 'var(--font-ui)',
                    fontSize: 13,
                    transition: 'background 0.15s',
                    outline: 'none',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(244, 67, 54, 0.1)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  🚪 Logout
                </button>
              </div>
            )}
          </div>
        )}

        {/* Clock */}
        <div style={{
          fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)',
          letterSpacing: 1
        }}>
          {timeStr}
        </div>
      </div>
    </div>
  );
}
