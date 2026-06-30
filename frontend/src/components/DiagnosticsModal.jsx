import { useState, useEffect } from 'react'
import { useRigStore } from '../stores/useRigStore.js'

const SEVERITY_COLOR = {
  LOW:      '#00e676',
  MEDIUM:   '#ffb300',
  HIGH:     '#ff7043',
  CRITICAL: '#ff3b3b',
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

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
      zIndex: 999999, background: 'rgba(3, 7, 15, 0.85)',
      backdropFilter: 'blur(16px)', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '40px 20px', boxSizing: 'border-box'
    }}>
      {/* CSS keyframes injected inline */}
      <style>{`
        @keyframes modalAppear {
          from { opacity: 0; transform: scale(0.96) translateY(10px); }
          to { opacity: 1; transform: scale(1) translateY(0); }
        }
        .diag-modal {
          animation: modalAppear 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        .diag-item:hover {
          background: rgba(0, 180, 255, 0.05) !important;
          border-color: rgba(0, 180, 255, 0.2) !important;
        }
        .close-btn:hover {
          color: #ff3b3b !important;
          background: rgba(255, 59, 59, 0.1) !important;
        }
      `}</style>

      <div className="diag-modal" style={{
        width: '100%', maxWidth: 1200, height: '85vh',
        background: 'rgba(5, 12, 24, 0.95)', border: '1px solid rgba(0, 180, 255, 0.22)',
        borderRadius: 12, display: 'flex', flexDirection: 'column', overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(0, 0, 0, 0.6), 0 0 30px rgba(0, 180, 255, 0.12)',
      }}>
        {/* Header */}
        <div style={{
          padding: '16px 24px', borderBottom: '1px solid rgba(0, 180, 255, 0.15)',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          background: 'rgba(8, 18, 36, 0.8)', flexShrink: 0
        }}>
          <div>
            <div style={{
              fontFamily: "'Share Tech Mono'", fontSize: 10, color: '#5a8aaa',
              letterSpacing: 3, textTransform: 'uppercase', marginBottom: 2
            }}>
              INCIDENT RESPONSE HUB
            </div>
            <div style={{
              fontFamily: "'Barlow Condensed'", fontSize: 24, fontWeight: 700,
              color: '#00b4ff', letterSpacing: 1.5, display: 'flex', alignItems: 'center', gap: 10
            }}>
              🧠 AI-DRIVEN SYSTEM DIAGNOSTICS
              {diagnostics.length > 0 && (
                <span style={{
                  background: 'rgba(0, 255, 213, 0.12)', border: '1px solid #00ffd5',
                  color: '#00ffd5', fontSize: 11, padding: '2px 8px', borderRadius: 4,
                  fontFamily: "'Share Tech Mono'", letterSpacing: 0
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
              background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: 6, width: 32, height: 32, cursor: 'pointer',
              color: '#5a8aaa', fontSize: 20, display: 'flex', alignItems: 'center', justifyContent: 'center',
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
            width: 320, borderRight: '1px solid rgba(0, 180, 255, 0.12)',
            display: 'flex', flexDirection: 'column', background: 'rgba(3, 7, 16, 0.4)',
            flexShrink: 0
          }}>
            <div style={{
              padding: '12px 16px', background: 'rgba(0, 180, 255, 0.03)',
              fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa',
              borderBottom: '1px solid rgba(0, 180, 255, 0.08)', letterSpacing: 1.5
            }}>
              ALERT LOGS
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
              {diagnostics.length === 0 ? (
                <div style={{
                  textAlign: 'center', color: '#2a4a5a', fontFamily: "'Share Tech Mono'",
                  fontSize: 12, padding: '40px 10px'
                }}>
                  No incident reports logged.
                </div>
              ) : (
                diagnostics.map((d, index) => {
                  const uniqueId = d.event_id || d.timestamp || index
                  const isSelected = selectedId === uniqueId
                  const sc = SEVERITY_COLOR[d.severity] || '#00e676'
                  const title = d.primary_diagnosis || (d.error ? "Agent Error" : "Unknown Anomaly")
                  
                  return (
                    <div
                      key={uniqueId}
                      className="diag-item"
                      onClick={() => setSelectedId(uniqueId)}
                      style={{
                        padding: '12px 14px', borderRadius: 8, marginBottom: 8,
                        cursor: 'pointer', transition: 'all 0.2s',
                        background: isSelected ? 'rgba(0, 180, 255, 0.08)' : 'rgba(255,255,255,0.01)',
                        border: `1px solid ${isSelected ? '#00b4ff88' : 'rgba(255,255,255,0.05)'}`,
                        borderLeft: `3px solid ${d.error ? '#ff3b3b' : sc}`
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{
                          fontFamily: "'Share Tech Mono'", fontSize: 9.5, fontWeight: 'bold',
                          color: d.error ? '#ff3b3b' : sc, letterSpacing: 1
                        }}>
                          {d.error ? 'ERROR' : d.severity || 'INFO'}
                        </span>
                        <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 9.5, color: '#5a8aaa' }}>
                          {d.timestamp ? timeAgo(new Date(d.timestamp).getTime()) : 'just now'}
                        </span>
                      </div>
                      
                      <div style={{
                        fontFamily: "'Rajdhani'", fontSize: 14, fontWeight: 700,
                        color: isSelected ? '#00ffd5' : '#e0f4ff', marginBottom: 6,
                        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                      }}>
                        {title}
                      </div>

                      <div style={{
                        fontFamily: "'Share Tech Mono'", fontSize: 9.5, color: '#5a8aaa',
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
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'rgba(5, 10, 20, 0.2)' }}>
            {!selectedDiag ? (
              <div style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexDirection: 'column', color: '#2a4a5a', fontFamily: "'Share Tech Mono'"
              }}>
                <div style={{ fontSize: 40, marginBottom: 10 }}>🔍</div>
                <div style={{ fontSize: 13, letterSpacing: 2 }}>SELECT AN INCIDENT TO VIEW FULL DETAILS</div>
              </div>
            ) : selectedDiag.error ? (
              <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
                <div style={{
                  background: 'rgba(255,59,59,0.03)', border: '1px solid rgba(255,59,59,0.15)',
                  borderLeft: '4px solid #ff3b3b', borderRadius: 8, padding: 20,
                  fontFamily: "'Share Tech Mono'", color: '#ff3b3b'
                }}>
                  <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8, letterSpacing: 1.5 }}>
                    ⚠️ DIAGNOSTIC PIPELINE ERROR
                  </div>
                  <div style={{ fontSize: 13, color: '#e0f4ff', lineHeight: 1.6 }}>
                    The diagnostic agent encountered an error processing this alert:
                    <pre style={{
                      background: 'rgba(0,0,0,0.3)', padding: 12, borderRadius: 6,
                      marginTop: 10, overflowX: 'auto', border: '1px solid rgba(255,255,255,0.05)'
                    }}>{selectedDiag.error}</pre>
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ flex: 1, padding: 24, overflowY: 'auto', boxSizing: 'border-box' }}>
                {/* Meta Header block */}
                <div style={{
                  display: 'flex', gap: 20, justifyContent: 'space-between', alignItems: 'flex-start',
                  borderBottom: '1px solid rgba(0,180,255,0.1)', paddingBottom: 16, marginBottom: 20
                }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                      <span style={{
                        background: (SEVERITY_COLOR[selectedDiag.severity] || '#00e676') + '22',
                        border: `1px solid ${SEVERITY_COLOR[selectedDiag.severity] || '#00e676'}`,
                        color: SEVERITY_COLOR[selectedDiag.severity] || '#00e676',
                        fontSize: 10, fontWeight: 700, padding: '2px 10px', borderRadius: 4,
                        fontFamily: "'Share Tech Mono'", letterSpacing: 1.5
                      }}>
                        {selectedDiag.severity || 'CRITICAL'}
                      </span>
                      <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa' }}>
                        ID: <span style={{ color: '#e0f4ff' }}>{selectedDiag.event_id || 'unknown'}</span>
                      </span>
                      <span style={{ color: 'rgba(255,255,255,0.1)' }}>|</span>
                      <span style={{ fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa' }}>
                        ZONE: <span style={{ color: '#00b4ff', fontWeight: 'bold' }}>{selectedDiag.zone_id ? selectedDiag.zone_id.replace(/_/g, ' ').toUpperCase() : 'UNKNOWN'}</span>
                      </span>
                    </div>
                    <div style={{
                      fontFamily: "'Barlow Condensed'", fontSize: 28, fontWeight: 700,
                      color: '#e0f4ff', letterSpacing: 1, lineHeight: 1.1
                    }}>
                      {selectedDiag.primary_diagnosis || 'Unclassified failure mode'}
                    </div>
                  </div>

                  {/* Confidence gauge */}
                  <div style={{ textAlign: 'right', flexShrink: 0 }}>
                    <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 9.5, color: '#5a8aaa', letterSpacing: 1.5, marginBottom: 4 }}>
                      DIAGNOSIS CONFIDENCE
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 100, height: 8, background: 'rgba(255,255,255,0.06)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%', width: `${selectedDiag.confidence_score || 0}%`,
                          background: 'linear-gradient(90deg, #00b4ff, #00ffd5)',
                          boxShadow: '0 0 10px #00ffd5bb', borderRadius: 4
                        }} />
                      </div>
                      <span style={{
                        fontFamily: "'Barlow Condensed'", fontSize: 24, fontWeight: 700,
                        color: '#00ffd5', lineHeight: 1
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
                    <div style={{
                      background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(0,180,255,0.08)',
                      borderRadius: 8, padding: 14
                    }}>
                      <div style={{
                        fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#00b4ff',
                        letterSpacing: 2, borderBottom: '1px solid rgba(0,180,255,0.1)',
                        paddingBottom: 6, marginBottom: 10
                      }}>
                        🚨 ANOMALOUS TELEMETRY SNAPSHOT
                      </div>
                      
                      {selectedDiag.telemetry_snapshot ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                          {Object.entries(selectedDiag.telemetry_snapshot).map(([key, val]) => {
                            const isTriggered = selectedDiag.triggered_sensors?.some(s => key.toLowerCase().includes(s.toLowerCase()));
                            return (
                              <div key={key} style={{
                                background: isTriggered ? 'rgba(255,59,59,0.03)' : 'rgba(255,255,255,0.01)',
                                border: `1px solid ${isTriggered ? 'rgba(255,59,59,0.15)' : 'rgba(255,255,255,0.03)'}`,
                                borderRadius: 6, padding: '8px 10px'
                              }}>
                                <div style={{ fontFamily: "'Share Tech Mono'", fontSize: 9, color: '#5a8aaa' }}>
                                  {formatSensorKey(key)}
                                </div>
                                <div style={{
                                  fontFamily: "'Barlow Condensed'", fontSize: 18, fontWeight: 700,
                                  color: isTriggered ? '#ff3b3b' : '#00e676', marginTop: 2
                                }}>
                                  {val}
                                  {isTriggered && <span style={{ fontSize: 10, marginLeft: 6, color: '#ff3b3b' }}>⚠ ALERT</span>}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      ) : (
                        <div style={{
                          fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#5a8aaa',
                          fontStyle: 'italic', padding: '10px 0'
                        }}>
                          No telemetry snapshot attached. Triggered sensors: {selectedDiag.triggered_sensors?.join(', ')}
                        </div>
                      )}
                    </div>

                    {/* Subgraph Topology */}
                    <div style={{
                      background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(0,180,255,0.08)',
                      borderRadius: 8, padding: 14
                    }}>
                      <div style={{
                        fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#00b4ff',
                        letterSpacing: 2, borderBottom: '1px solid rgba(0,180,255,0.1)',
                        paddingBottom: 6, marginBottom: 10
                      }}>
                        🕸️ NEO4J TOPOLOGY RELATIONS
                      </div>
                      
                      <div style={{
                        background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(0,180,255,0.08)',
                        borderRadius: 6, padding: 10, fontFamily: "'Share Tech Mono'",
                        fontSize: 10, color: '#88b5d5', maxHeight: 180, overflowY: 'auto'
                      }}>
                        <div style={{ color: '#00ffd5', fontWeight: 'bold', marginBottom: 4 }}>
                          MATCHED FAILURE MODES:
                        </div>
                        {selectedDiag.triggered_sensors?.map(sensor => (
                          <div key={sensor} style={{ margin: '4px 0', paddingLeft: 8, borderLeft: '2px solid rgba(0,180,255,0.3)' }}>
                            Sensor type <span style={{ color: '#e0f4ff' }}>{sensor}</span> links to suspected device failures.
                          </div>
                        ))}
                        <div style={{ marginTop: 8, fontSize: 9.5, color: '#5a8aaa', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: 6 }}>
                          {"Query: MATCH (z:Zone)-[:CONTAINS]->(d:Device)-[:CAN_EXPERIENCE]->(f:FailureMode)..."}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Right subcolumn: Ruled Out Reasoning (LLM Analysis) */}
                  <div style={{
                    background: 'rgba(255,255,255,0.01)', border: '1px solid rgba(0,180,255,0.08)',
                    borderRadius: 8, padding: 14, display: 'flex', flexDirection: 'column'
                  }}>
                    <div style={{
                      fontFamily: "'Share Tech Mono'", fontSize: 11, color: '#00b4ff',
                      letterSpacing: 2, borderBottom: '1px solid rgba(0,180,255,0.1)',
                      paddingBottom: 6, marginBottom: 10
                    }}>
                      ⚡ NEGATIVE REASONING & ROOT-CAUSE
                    </div>
                    
                    <div style={{
                      flex: 1, fontFamily: "'Rajdhani', sans-serif", fontSize: 14,
                      color: '#cbe4ff', lineHeight: 1.6, overflowY: 'auto',
                      background: 'rgba(0,0,0,0.12)', borderRadius: 6, padding: 12,
                      border: '1px solid rgba(255,255,255,0.02)'
                    }}>
                      {selectedDiag.reasoning || 'No diagnostics log detail found.'}
                    </div>
                  </div>
                </div>

                {/* Bottom section: Mitigation Recommendations (Highly Detailed) */}
                {selectedDiag.recommended_action && (
                  <div style={{
                    background: 'rgba(255, 179, 0, 0.02)',
                    border: '1px solid rgba(255, 179, 0, 0.25)',
                    borderLeft: '4px solid #ffb300',
                    borderRadius: 8, padding: 16,
                    boxShadow: '0 0 15px rgba(255, 179, 0, 0.04)'
                  }}>
                    <div style={{
                      fontFamily: "'Share Tech Mono'", fontSize: 12, color: '#ffb300',
                      letterSpacing: 2, fontWeight: 700, marginBottom: 8,
                      display: 'flex', alignItems: 'center', gap: 8
                    }}>
                      ⚡ EMERGENCY RESPONSE MITIGATION PROTOCOL
                    </div>
                    
                    <div style={{
                      fontFamily: "'Rajdhani', sans-serif", fontSize: 15,
                      color: '#fff', lineHeight: 1.6
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
                                borderRadius: '50%', background: '#ffb300'
                              }} />
                              <strong style={{ color: '#ffb300', textTransform: 'uppercase', fontSize: 13, fontFamily: "'Share Tech Mono'" }}>
                                {parts[0]}:
                              </strong>{' '}
                              <span style={{ color: '#e0f4ff' }}>{parts.slice(1).join(': ')}</span>
                            </div>
                          )
                        }

                        return (
                          <div key={idx} style={{ marginBottom: 6, paddingLeft: 12, position: 'relative', color: '#e0f4ff' }}>
                            <span style={{
                              position: 'absolute', left: 0, top: 8, width: 4, height: 4,
                              borderRadius: '50%', background: '#ffb300'
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
