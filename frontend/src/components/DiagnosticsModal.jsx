import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

// Severity → accent hex (kept as hex because some styles concatenate an alpha suffix).
const SEVERITY_COLOR = {
  LOW:      '#46b17f',
  MEDIUM:   '#d9a64e',
  HIGH:     '#e06054',
  CRITICAL: '#e06054',
}

function formatSensorKey(key) {
  return key
    .replace(/_c$/i, ' (°C)')
    .replace(/_mm_s$/i, ' (mm/s)')
    .replace(/_db$/i, ' (dB)')
    .replace(/_ppm$/i, ' (ppm)')
    .replace(/_/g, ' ')
    .toUpperCase();
}

export default function DiagnosticsModal() {
  const show = useRigStore(s => s.showDiagnosticsModal)
  const setShow = useRigStore(s => s.setShowDiagnosticsModal)
  const diagnostics = useRigStore(s => s.diagnostics) || []

  const [selectedId, setSelectedId] = useState(null)

  // Auto-select first diagnostic when list updates or modal opens
  useEffect(() => {
    if (diagnostics.length > 0 && (!selectedId || !diagnostics.some(d => (d.event_id || d.timestamp) === selectedId))) {
      setSelectedId(diagnostics[0].event_id || diagnostics[0].timestamp)
    }
  }, [diagnostics, selectedId, show])

  if (!show) return null

  const selectedDiag = diagnostics.find(d => (d.event_id || d.timestamp) === selectedId) || diagnostics[0]

  const timeAgo = (ts) => {
    const s = Math.floor((Date.now() - ts) / 1000)
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    return `${Math.floor(s / 3600)}h ago`
  }

  // Card shell reused for the detail panels (flat steel, sharp 1px border).
  const cardStyle = {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 8, padding: 14,
  }
  const sectionTitle = {
    fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
    letterSpacing: 1.5, textTransform: 'uppercase',
    borderBottom: '1px solid var(--border)', paddingBottom: 6, marginBottom: 10,
  }

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
      zIndex: 999999, background: 'rgba(8, 9, 11, 0.8)',
      backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '40px 20px', boxSizing: 'border-box'
    }}>
      {/* CSS keyframes injected inline */}
      <style>{`
        @keyframes modalAppear {
          from { opacity: 0; transform: scale(0.98) translateY(8px); }
          to { opacity: 1; transform: scale(1) translateY(0); }
        }
        .diag-modal { animation: modalAppear 0.18s ease-out forwards; }
        .diag-item:hover {
          background: var(--bg-card) !important;
          border-color: var(--border-bright) !important;
        }
        .close-btn:hover {
          color: var(--accent-red) !important;
          border-color: var(--accent-red) !important;
        }
      `}</style>

      <div className="diag-modal" style={{
        width: '100%', maxWidth: 1200, height: '85vh',
        background: 'var(--bg-panel)', border: '1px solid var(--border)',
        borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(0, 0, 0, 0.6)',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid var(--border)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          background: 'var(--bg-card)', flexShrink: 0
        }}>
          <div>
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)',
              letterSpacing: 2, textTransform: 'uppercase', marginBottom: 3
            }}>
              Incident Response Hub
            </div>
            <div style={{
              fontFamily: 'var(--font-ui)', fontSize: 22, fontWeight: 600,
              color: 'var(--text-primary)', letterSpacing: 0.3, display: 'flex', alignItems: 'center', gap: 10
            }}>
              AI-Driven System Diagnostics
              {diagnostics.length > 0 && (
                <span style={{
                  background: 'var(--bg-panel)', border: '1px solid var(--border-bright)',
                  color: 'var(--accent-cobalt)', fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  fontFamily: 'var(--font-mono)', letterSpacing: 0
                }}>
                  {diagnostics.length} Active Events
                </span>
              )}
            </div>
          </div>
          <button
            className="close-btn"
            onClick={() => setShow(false)}
            style={{
              background: 'var(--bg-card)', border: '1px solid var(--border)',
              borderRadius: 6, width: 32, height: 32, cursor: 'pointer',
              color: 'var(--text-muted)', fontSize: 20, display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.15s'
            }}
          >
            ×
          </button>
        </div>

        {/* Split Body */}
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {/* Left Panel: Event List */}
          <div style={{
            width: 320, borderRight: '1px solid var(--border)',
            display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)',
            flexShrink: 0
          }}>
            <div style={{
              padding: '12px 16px', background: 'var(--bg-card)',
              fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
              borderBottom: '1px solid var(--border)', letterSpacing: 1.5, textTransform: 'uppercase'
            }}>
              Alert Logs
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
              {diagnostics.length === 0 ? (
                <div style={{
                  textAlign: 'center', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)',
                  fontSize: 12, padding: '40px 10px'
                }}>
                  No incident reports logged.
                </div>
              ) : (
                diagnostics.map((d, index) => {
                  const uniqueId = d.event_id || d.timestamp || index
                  const isSelected = selectedId === uniqueId
                  const sc = SEVERITY_COLOR[d.severity] || '#46b17f'
                  const title = d.primary_diagnosis || (d.error ? "Agent Error" : "Unknown Anomaly")

                  return (
                    <div
                      key={uniqueId}
                      className="diag-item"
                      onClick={() => setSelectedId(uniqueId)}
                      style={{
                        padding: '12px 14px', borderRadius: 6, marginBottom: 8,
                        cursor: 'pointer', transition: 'all 0.15s',
                        background: isSelected ? 'var(--bg-card)' : 'var(--bg-panel)',
                        border: '1px solid var(--border)',
                        borderLeft: `3px solid ${d.error ? '#e06054' : sc}`
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{
                          fontFamily: 'var(--font-mono)', fontSize: 9.5, fontWeight: 600,
                          color: d.error ? 'var(--accent-red)' : sc, letterSpacing: 1
                        }}>
                          {d.error ? 'ERROR' : d.severity || 'INFO'}
                        </span>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)' }}>
                          {d.timestamp ? timeAgo(new Date(d.timestamp).getTime()) : 'just now'}
                        </span>
                      </div>

                      <div style={{
                        fontFamily: 'var(--font-ui)', fontSize: 14, fontWeight: 600,
                        color: isSelected ? 'var(--accent-cobalt)' : 'var(--text-primary)', marginBottom: 6,
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                      }}>
                        {title}
                      </div>

                      <div style={{
                        fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)',
                        display: 'flex', justifyContent: 'space-between'
                      }}>
                        <span>ID: {d.event_id ? d.event_id.substring(5) : 'unknown'}</span>
                        <span>ZONE: {d.zone_id ? d.zone_id.replace(/_/g, ' ').toUpperCase() : 'UNKNOWN'}</span>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* Right Panel: Detailed View */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-panel)' }}>
            {!selectedDiag ? (
              <div style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexDirection: 'column', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)'
              }}>
                <div style={{ fontSize: 40, marginBottom: 10 }}>🔍</div>
                <div style={{ fontSize: 13, letterSpacing: 1.5 }}>SELECT AN INCIDENT TO VIEW FULL DETAILS</div>
              </div>
            ) : selectedDiag.error ? (
              <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
                <div style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderLeft: '4px solid var(--accent-red)', borderRadius: 8, padding: 20,
                  fontFamily: 'var(--font-mono)', color: 'var(--accent-red)'
                }}>
                  <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, letterSpacing: 1 }}>
                    ⚠️ DIAGNOSTIC PIPELINE ERROR
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.6 }}>
                    The diagnostic agent encountered an error processing this alert:
                    <pre style={{
                      background: 'var(--bg-deep)', padding: 12, borderRadius: 6,
                      marginTop: 10, overflowX: 'auto', border: '1px solid var(--border)'
                    }}>{selectedDiag.error}</pre>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ flex: 1, padding: 24, overflowY: 'auto', boxSizing: 'border-box' }}>
                {/* Meta Header block */}
                <div style={{
                  display: 'flex', gap: 20, justifyContent: 'space-between', alignItems: 'flex-start',
                  borderBottom: '1px solid var(--border)', paddingBottom: 16, marginBottom: 20
                }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                      <span style={{
                        background: 'var(--bg-card)',
                        border: `1px solid ${SEVERITY_COLOR[selectedDiag.severity] || '#46b17f'}`,
                        color: SEVERITY_COLOR[selectedDiag.severity] || '#46b17f',
                        fontSize: 10, fontWeight: 600, padding: '2px 10px', borderRadius: 4,
                        fontFamily: 'var(--font-mono)', letterSpacing: 1
                      }}>
                        {selectedDiag.severity || 'CRITICAL'}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                        ID: <span style={{ color: 'var(--text-primary)' }}>{selectedDiag.event_id || 'unknown'}</span>
                      </span>
                      <span style={{ color: 'var(--border-bright)' }}>|</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                        ZONE: <span style={{ color: 'var(--accent-cobalt)', fontWeight: 600 }}>{selectedDiag.zone_id ? selectedDiag.zone_id.replace(/_/g, ' ').toUpperCase() : 'UNKNOWN'}</span>
                      </span>
                    </div>
                    <div style={{
                      fontFamily: 'var(--font-ui)', fontSize: 26, fontWeight: 600,
                      color: 'var(--text-primary)', letterSpacing: 0.2, lineHeight: 1.15
                    }}>
                      {selectedDiag.primary_diagnosis || 'Unclassified failure mode'}
                    </div>
                  </div>

                  {/* Confidence gauge */}
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4, textTransform: 'uppercase' }}>
                      Diagnosis Confidence
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 100, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', width: `${selectedDiag.confidence_score || 0}%`,
                          background: 'var(--accent-cobalt)', borderRadius: 4
                        }} />
                      </div>
                      <span style={{
                        fontFamily: 'var(--font-ui)', fontSize: 22, fontWeight: 600,
                        color: 'var(--text-primary)', lineHeight: 1
                      }}>
                        {selectedDiag.confidence_score || 0}%
                      </span>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>
                  {/* Left subcolumn: Telemetry Snapshot & Topology */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
                    {/* Telemetry Snap */}
                    <div style={cardStyle}>
                      <div style={sectionTitle}>
                        Anomalous Telemetry Snapshot
                      </div>

                      {selectedDiag.telemetry_snapshot ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                          {Object.entries(selectedDiag.telemetry_snapshot).map(([key, val]) => {
                            const isTriggered = selectedDiag.triggered_sensors?.some(s => key.toLowerCase().includes(s.toLowerCase()));
                            return (
                              <div key={key} style={{
                                background: 'var(--bg-panel)',
                                border: `1px solid ${isTriggered ? 'var(--accent-red)' : 'var(--border)'}`,
                                borderRadius: 6, padding: '8px 10px'
                              }}>
                                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>
                                  {formatSensorKey(key)}
                                </div>
                                <div style={{
                                  fontFamily: 'var(--font-ui)', fontSize: 18, fontWeight: 600,
                                  color: isTriggered ? 'var(--accent-red)' : 'var(--accent-green)', marginTop: 2
                                }}>
                                  {val}
                                  {isTriggered && <span style={{ fontSize: 10, marginLeft: 6, color: 'var(--accent-red)' }}>⚠ ALERT</span>}
                                </div>
                                {isTriggered && selectedDiag.threshold_context?.[key] && (() => {
                                  const ctx = selectedDiag.threshold_context[key]
                                  const showLimits = ctx.warning_min != null || ctx.critical_min != null
                                  return (
                                    <div style={{
                                      marginTop: 8, paddingTop: 8,
                                      borderTop: '1px solid var(--border)',
                                      fontFamily: 'var(--font-mono)', fontSize: 9.5,
                                      color: 'var(--text-muted)', lineHeight: 1.4
                                    }}>
                                      {showLimits && (
                                        <div style={{ color: 'var(--accent-amber)', fontWeight: 600 }}>
                                          LIMITS: {ctx.warning_min != null ? `Warn ${ctx.warning_min}` : '—'} / {ctx.critical_min != null ? `Crit ${ctx.critical_min}` : '—'} {ctx.unit || ''}
                                        </div>
                                      )}
                                      {ctx.source_manual && (
                                        <div style={{ color: 'var(--accent-cobalt)', marginTop: 2 }}>
                                          📄 {ctx.source_manual} {ctx.source_section ? `(Sec ${ctx.source_section})` : ''}
                                        </div>
                                      )}
                                      {ctx.device_name && (
                                        <div style={{ color: 'var(--text-muted)', marginTop: 1 }}>
                                          ⚙ Equipment: {ctx.device_name}
                                        </div>
                                      )}
                                      {ctx.selection_reason && (
                                        <div style={{ color: 'var(--text-dim)', fontSize: 8.5, fontStyle: 'italic', marginTop: 3, whiteSpace: 'normal' }}>
                                          {ctx.selection_reason}
                                        </div>
                                      )}
                                    </div>
                                  )
                                })()}
                              </div>
                            )
                          })}
                        </div>
                      ) : (
                        <div style={{
                          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
                          fontStyle: 'italic', padding: '10px 0'
                        }}>
                          No telemetry snapshot attached. Triggered sensors: {selectedDiag.triggered_sensors?.join(', ')}
                        </div>
                      )}
                    </div>

                    {/* Subgraph Topology */}
                    <div style={cardStyle}>
                      <div style={sectionTitle}>
                        Neo4j Topology Relations
                      </div>

                      <div style={{
                        background: 'var(--bg-deep)', border: '1px solid var(--border)',
                        borderRadius: 6, padding: 10, fontFamily: 'var(--font-mono)',
                        fontSize: 10, color: 'var(--text-muted)', maxHeight: 180, overflowY: 'auto'
                      }}>
                        <div style={{ color: 'var(--text-primary)', fontWeight: 600, marginBottom: 4 }}>
                          MATCHED FAILURE MODES:
                        </div>
                        {selectedDiag.triggered_sensors?.map(sensor => (
                          <div key={sensor} style={{ margin: '4px 0', paddingLeft: 8, borderLeft: '2px solid var(--border-bright)' }}>
                            Sensor type <span style={{ color: 'var(--text-primary)' }}>{sensor}</span> links to suspected device failures.
                          </div>
                        ))}
                        <div style={{ marginTop: 8, fontSize: 9.5, color: 'var(--text-dim)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                          {"Query: MATCH (z:Zone)-[:CONTAINS]->(d:Device)-[:CAN_EXPERIENCE]->(f:FailureMode)..."}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Right subcolumn: Reasoning (LLM Analysis) */}
                  <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column' }}>
                    <div style={sectionTitle}>
                      Negative Reasoning &amp; Root-Cause
                    </div>

                    <div style={{
                      flex: 1, fontFamily: 'var(--font-ui)', fontSize: 14,
                      color: 'var(--text-primary)', lineHeight: 1.6, overflowY: 'auto',
                      background: 'var(--bg-deep)', borderRadius: 6, padding: 12,
                      border: '1px solid var(--border)'
                    }}>
                      {selectedDiag.reasoning || 'No diagnostics log detail found.'}
                    </div>
                  </div>
                </div>

                {/* Bottom section: Mitigation Recommendations */}
                {selectedDiag.recommended_action && (
                  <div style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderLeft: '4px solid var(--accent-amber)',
                    borderRadius: 8, padding: 16,
                  }}>
                    <div style={{
                      fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent-amber)',
                      letterSpacing: 1, fontWeight: 600, marginBottom: 8, textTransform: 'uppercase',
                      display: 'flex', alignItems: 'center', gap: 8
                    }}>
                      Emergency Response Mitigation Protocol
                    </div>

                    <div style={{
                      fontFamily: 'var(--font-ui)', fontSize: 15,
                      color: 'var(--text-primary)', lineHeight: 1.6
                    }}>
                      {/* Formats text blocks with bullet points or paragraphs nicely */}
                      {selectedDiag.recommended_action.split(/\d+\)\s+/).map((item, idx) => {
                        const trimmed = item.trim()
                        if (!trimmed) return null
                        if (idx === 0) {
                          return <p key={idx} style={{ marginTop: 0, marginBottom: 10, fontWeight: 500 }}>{trimmed}</p>
                        }

                        // Split title from step details if formatted as title: details
                        const parts = trimmed.split(/:\s+/)
                        if (parts.length > 1) {
                          return (
                            <div key={idx} style={{ marginBottom: 8, paddingLeft: 12, position: 'relative' }}>
                              <span style={{
                                position: 'absolute', left: 0, top: 8, width: 4, height: 4,
                                borderRadius: '50%', background: 'var(--accent-amber)'
                              }} />
                              <strong style={{ color: 'var(--accent-amber)', textTransform: 'uppercase', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
                                {parts[0]}:
                              </strong>{' '}
                              <span style={{ color: 'var(--text-primary)' }}>{parts.slice(1).join(': ')}</span>
                            </div>
                          )
                        }

                        return (
                          <div key={idx} style={{ marginBottom: 6, paddingLeft: 12, position: 'relative', color: 'var(--text-primary)' }}>
                            <span style={{
                              position: 'absolute', left: 0, top: 8, width: 4, height: 4,
                              borderRadius: '50%', background: 'var(--accent-amber)'
                            }} />
                            {trimmed}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
