import { useEffect } from 'react'
import { createPortal } from 'react-dom'

// API base mirrors useRigStore so the proof image resolves to the same backend.
const host = window.location.hostname === 'localhost' ? '127.0.0.1' : window.location.hostname
export const API_BASE = import.meta.env.VITE_API_URL || `http://${host}:8000/api`

// Maps a live PPE item status to a label tone + glyph for the per-person chips.
export function ppeChipStyle(status) {
  if (status === 'detected') return { tone: 'var(--accent-green)', mark: '✓' }
  if (status === 'missing')  return { tone: 'var(--accent-red)',   mark: '✗' }
  return { tone: 'var(--text-muted)', mark: '?' }   // unknown | null
}

// Turn a person's per-person ppe object {hat, glasses} into the two display chips.
// `proof` token is `{personId}_{hat|glasses}`, matching the Redis proof key the
// pipeline writes and the /api/ppe/proof/{item} endpoint serves.
export function personPpeItems(personId, ppe = {}) {
  return [
    { key: 'hat',     label: '⛑ Hat',     status: ppe.hat,     proof: `${personId}_hat` },
    { key: 'glasses', label: '🕶 Glasses', status: ppe.glasses, proof: `${personId}_glasses` },
  ]
}

// True if any item is explicitly missing (drives ALERT badges / counts).
export function ppeHasAlert(ppe = {}) {
  return ppe.hat === 'missing' || ppe.glasses === 'missing'
}

// Centered, viewport-anchored proof lightbox. Rendered through a portal to document.body
// so it escapes the sidebar's stacking/backdrop-filter context. Closes on click or Escape.
export function ProofLightbox({ item, since, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.78)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        zIndex: 1000, cursor: 'pointer',
      }}>
      <div style={{ textAlign: 'center' }} onClick={e => e.stopPropagation()}>
        <img
          src={`${API_BASE}/ppe/proof/${item}?t=${since || ''}`}
          alt={`Proof: ${item} missing`}
          style={{
            maxWidth: '82vw', maxHeight: '78vh', borderRadius: 8,
            border: '2px solid var(--accent-red, #e06054)',
            boxShadow: '0 12px 48px rgba(0,0,0,0.6)',
          }}
        />
        <div style={{ marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 12, color: '#fff' }}>
          Proof — {item.replace('_', ' ')} missing · press Esc or click to close
        </div>
      </div>
    </div>,
    document.body
  )
}
