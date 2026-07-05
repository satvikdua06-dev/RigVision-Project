import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { authHeaders } from '../utils/api.js';

const API_BASE = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000/api`;

// Highlight text helper
function HighlightText({ text, search }) {
  if (!search) return <span>{text}</span>;
  const parts = text.split(new RegExp(`(${escapeRegExp(search)})`, 'gi'));
  return (
    <span>
      {parts.map((part, i) => 
        part.toLowerCase() === search.toLowerCase() ? (
          <mark key={i} style={{ backgroundColor: 'rgba(217, 166, 78, 0.4)', color: 'var(--text-primary)', borderRadius: '2px', padding: '0 2px' }}>{part}</mark>
        ) : (
          part
        )
      )}
    </span>
  );
}

function escapeRegExp(string) {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export default function ManualsViewer() {
  const [manuals, setManuals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSectionIdx, setActiveSectionIdx] = useState(0);
  const [activeTab, setActiveTab] = useState('all'); // 'all', 'specs', 'limits', 'diag', 'schedule'

  const location = useLocation();
  const navigate = useNavigate();
  const searchInputRef = useRef(null);

  // Parse sections and structure them
  const parseManualText = (text) => {
    const sections = [];
    const rawSections = text.split(/(?=---\s+[^-\n]+\s+---)/g);
    
    rawSections.forEach((rawSec) => {
      const lines = rawSec.split('\n');
      if (lines.length === 0) return;
      
      let titleLine = lines[0].trim();
      if (!titleLine.startsWith('---')) return;
      
      const title = titleLine.replace(/---/g, '').trim();
      const metadata = [];
      const subSections = [];
      let currentSubSection = null;
      
      for (let i = 1; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();
        if (!trimmed) continue;
        
        const metaMatch = trimmed.match(/^(Device|Model|Manufacturer|Equipment Class|Document|Scope):\s*(.+)$/i);
        if (metaMatch && subSections.length === 0 && !currentSubSection) {
          metadata.push({ label: metaMatch[1], value: metaMatch[2] });
          continue;
        }
        
        const isHeader = trimmed.match(/^(Specifications:|Section \d+(?:\.\d+)?\s*—\s*[^:\n]+:)$/i);
        if (isHeader) {
          if (currentSubSection) {
            subSections.push(currentSubSection);
          }
          currentSubSection = {
            header: trimmed.replace(/:$/, '').trim(),
            lines: []
          };
          continue;
        }
        
        if (currentSubSection) {
          currentSubSection.lines.push(line);
        }
      }
      
      if (currentSubSection) {
        subSections.push(currentSubSection);
      }
      
      sections.push({
        title,
        metadata,
        subSections
      });
    });
    
    return sections;
  };

  // Fetch the manuals text
  useEffect(() => {
    const fetchManuals = async () => {
      try {
        setLoading(true);
        const res = await fetch(`${API_BASE}/documents/manuals`, {
          headers: authHeaders()
        });
        if (!res.ok) {
          throw new Error(`Failed to load manuals: ${res.status} ${res.statusText}`);
        }
        const text = await res.text();
        const parsed = parseManualText(text);
        setManuals(parsed);
        
        // Deep linking handling on load
        const params = new URLSearchParams(location.search);
        const secParam = params.get('section');
        const searchParam = params.get('search');
        
        if (searchParam) {
          setSearchQuery(searchParam);
        }
        
        if (secParam) {
          const idx = parsed.findIndex(m => m.title.toLowerCase().includes(secParam.toLowerCase()) || secParam.toLowerCase().includes(m.title.toLowerCase()));
          if (idx !== -1) {
            setActiveSectionIdx(idx);
          }
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    fetchManuals();
  }, []);

  // Update URL parameters when changing active section/search
  const handleSectionSelect = (idx) => {
    setActiveSectionIdx(idx);
    const params = new URLSearchParams(location.search);
    params.set('section', manuals[idx].title);
    navigate({ search: params.toString() }, { replace: true });
  };

  const handleSearchChange = (query) => {
    setSearchQuery(query);
    const params = new URLSearchParams(location.search);
    if (query) {
      params.set('search', query);
    } else {
      params.delete('search');
    }
    navigate({ search: params.toString() }, { replace: true });
  };

  // Helper to check if a subSection header matches our tab filters
  const getSubSectionType = (header) => {
    const h = header.toLowerCase();
    if (h.includes('specifications')) return 'specs';
    if (h.includes('limits')) return 'limits';
    if (h.includes('diagnostics') || h.includes('hazard')) return 'diag';
    if (h.includes('schedule') || h.includes('maintenance')) return 'schedule';
    return 'other';
  };

  // Parser helper to group diagnostic failure modes and required actions
  const renderDiagnosticModes = (lines) => {
    const modes = [];
    let currentMode = null;
    
    lines.forEach(line => {
      const trimmed = line.trim();
      if (!trimmed) return;
      
      const modeMatch = trimmed.match(/^(\d+)\.\s+([^:]+):\s*(.+)$/);
      if (modeMatch) {
        if (currentMode) modes.push(currentMode);
        currentMode = {
          index: modeMatch[1],
          name: modeMatch[2],
          description: modeMatch[3],
          requiredAction: null
        };
        return;
      }
      
      const actionMatch = trimmed.match(/^-\s*Required\s+Action:\s*(.+)$/i);
      if (actionMatch && currentMode) {
        currentMode.requiredAction = actionMatch[1];
        return;
      }
      
      if (currentMode) {
        currentMode.description += ' ' + trimmed;
      }
    });
    
    if (currentMode) modes.push(currentMode);

    if (modes.length === 0) {
      return (
        <ul style={{ paddingLeft: 20, margin: 0, color: 'var(--text-primary)', lineHeight: 1.6 }}>
          {lines.map((l, i) => (
            <li key={i} style={{ marginBottom: 8, fontFamily: 'var(--font-ui)' }}>
              <HighlightText text={l} search={searchQuery} />
            </li>
          ))}
        </ul>
      );
    }

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {modes.map((mode, i) => (
          <div 
            key={i} 
            style={{ 
              background: 'rgba(255,255,255,0.02)', 
              border: '1px solid var(--border)', 
              borderRadius: 8, 
              padding: 16 
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <span style={{ 
                fontFamily: 'var(--font-mono)', 
                fontSize: 11, 
                color: 'var(--accent-red)', 
                background: 'rgba(224, 96, 84, 0.1)', 
                padding: '2px 6px', 
                borderRadius: 4,
                fontWeight: 600
              }}>
                F-{mode.index.padStart(2, '0')}
              </span>
              <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                <HighlightText text={mode.name} search={searchQuery} />
              </h4>
            </div>
            
            <p style={{ margin: '0 0 12px 0', fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5 }}>
              <HighlightText text={mode.description} search={searchQuery} />
            </p>
            
            {mode.requiredAction && (
              <div style={{ 
                background: 'rgba(217, 166, 78, 0.06)', 
                borderLeft: '3px solid var(--accent-amber)', 
                padding: '10px 12px', 
                borderRadius: '0 6px 6px 0',
                fontSize: 12.5,
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-ui)'
              }}>
                <strong style={{ color: 'var(--accent-amber)', fontFamily: 'var(--font-mono)', fontSize: 10.5, display: 'block', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  🔧 Required Action:
                </strong>
                <HighlightText text={mode.requiredAction} search={searchQuery} />
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // Parser helper to group lists beautifully
  const renderListSection = (lines) => {
    return (
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {lines.map((line, i) => {
          const clean = line.replace(/^-\s*/, '');
          return (
            <li 
              key={i} 
              style={{ 
                padding: '8px 12px', 
                borderBottom: i < lines.length - 1 ? '1px solid rgba(255,255,255,0.03)' : 'none',
                display: 'flex',
                gap: 10,
                alignItems: 'flex-start',
                fontSize: 13,
                color: 'var(--text-primary)',
                lineHeight: 1.5
              }}
            >
              <span style={{ color: 'var(--accent-cobalt)', fontSize: 14, userSelect: 'none', marginTop: 1 }}>•</span>
              <div>
                <HighlightText text={clean} search={searchQuery} />
              </div>
            </li>
          );
        })}
      </ul>
    );
  };

  // Parser helper to format operating limits with warning checks
  const renderOperatingLimits = (lines) => {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {lines.map((line, i) => {
          const clean = line.replace(/^-\s*/, '');
          
          // Detect alarm/trip keywords
          const isCritical = clean.toLowerCase().includes('shutdown') || clean.toLowerCase().includes('critical') || clean.toLowerCase().includes('trip');
          const isWarning = clean.toLowerCase().includes('alarm') || clean.toLowerCase().includes('warning');
          
          let cardBorderColor = 'var(--border)';
          let cardBg = 'rgba(255,255,255,0.01)';
          let badgeText = '';
          let badgeColor = '';
          let badgeBg = '';

          if (isCritical) {
            cardBorderColor = 'rgba(224, 96, 84, 0.2)';
            cardBg = 'rgba(224, 96, 84, 0.03)';
            badgeText = 'CRITICAL LIMIT';
            badgeColor = 'var(--accent-red)';
            badgeBg = 'rgba(224, 96, 84, 0.1)';
          } else if (isWarning) {
            cardBorderColor = 'rgba(217, 166, 78, 0.2)';
            cardBg = 'rgba(217, 166, 78, 0.03)';
            badgeText = 'WARNING LIMIT';
            badgeColor = 'var(--accent-amber)';
            badgeBg = 'rgba(217, 166, 78, 0.1)';
          }

          return (
            <div 
              key={i} 
              style={{ 
                border: '1px solid ' + cardBorderColor, 
                background: cardBg, 
                borderRadius: 8, 
                padding: 14,
                display: 'flex',
                flexDirection: 'column',
                gap: 8
              }}
            >
              {badgeText && (
                <div style={{ display: 'flex' }}>
                  <span style={{ 
                    fontFamily: 'var(--font-mono)', 
                    fontSize: 8.5, 
                    fontWeight: 600, 
                    color: badgeColor, 
                    background: badgeBg, 
                    padding: '2px 6px', 
                    borderRadius: 3,
                    letterSpacing: 0.5
                  }}>
                    {badgeText}
                  </span>
                </div>
              )}
              <div style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--text-primary)' }}>
                <HighlightText text={clean} search={searchQuery} />
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const renderSubSection = (subSec) => {
    const type = getSubSectionType(subSec.header);
    
    return (
      <div 
        key={subSec.header} 
        id={subSec.header.replace(/\s+/g, '-').toLowerCase()}
        style={{ 
          background: 'var(--bg-card)', 
          border: '1px solid var(--border)', 
          borderRadius: 8, 
          padding: 20, 
          marginBottom: 20 
        }}
      >
        <h3 style={{ 
          margin: '0 0 16px 0', 
          fontFamily: 'var(--font-ui)', 
          fontWeight: 600, 
          fontSize: 15, 
          color: 'var(--accent-cobalt)',
          borderBottom: '1px solid rgba(255,255,255,0.05)',
          paddingBottom: 8,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>
            <HighlightText text={subSec.header} search={searchQuery} />
          </span>
          <span style={{ 
            fontFamily: 'var(--font-mono)', 
            fontSize: 9, 
            color: 'var(--text-muted)', 
            textTransform: 'uppercase', 
            fontWeight: 400 
          }}>
            {type}
          </span>
        </h3>

        {type === 'diag' && renderDiagnosticModes(subSec.lines)}
        {type === 'limits' && renderOperatingLimits(subSec.lines)}
        {type === 'specs' && renderListSection(subSec.lines)}
        {type === 'schedule' && renderListSection(subSec.lines)}
        {type === 'other' && renderListSection(subSec.lines)}
      </div>
    );
  };

  // Filter sections by search query
  const filteredManuals = manuals.map((m, idx) => {
    if (!searchQuery) return { ...m, matchCount: 0 };
    
    let matches = 0;
    const queryLower = searchQuery.toLowerCase();
    
    if (m.title.toLowerCase().includes(queryLower)) matches++;
    m.metadata.forEach(meta => {
      if (meta.label.toLowerCase().includes(queryLower) || meta.value.toLowerCase().includes(queryLower)) {
        matches++;
      }
    });
    
    m.subSections.forEach(sub => {
      if (sub.header.toLowerCase().includes(queryLower)) matches++;
      sub.lines.forEach(line => {
        if (line.toLowerCase().includes(queryLower)) matches++;
      });
    });
    
    return { ...m, matchCount: matches };
  });

  const activeManual = filteredManuals[activeSectionIdx];
  const activeSubSections = activeManual 
    ? activeManual.subSections.filter(sub => {
        if (activeTab === 'all') return true;
        return getSubSectionType(sub.header) === activeTab;
      })
    : [];

  return (
    <div style={{ 
      width: '100vw', 
      height: '100vh', 
      display: 'flex', 
      flexDirection: 'column', 
      background: 'var(--bg-deep)', 
      color: 'var(--text-primary)',
      fontFamily: 'var(--font-ui)',
      overflow: 'hidden'
    }}>
      {/* Top Header Panel */}
      <div className="glass" style={{ 
        height: 54, 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between', 
        padding: '0 24px', 
        zIndex: 10,
        borderBottom: '1px solid var(--border)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button 
            onClick={() => window.close()}
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '6px 12px',
              cursor: 'pointer',
              transition: 'all 0.15s',
              outline: 'none'
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border-bright)'; e.currentTarget.style.color = 'var(--text-primary)' }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text-muted)' }}
          >
            ← CLOSE TAB
          </button>
          
          <div style={{ width: 1, height: 20, background: 'var(--border)' }} />

          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: 0.5 }}>
              RIG<span style={{ color: 'var(--accent-cobalt)' }}>VISION</span>
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)', letterSpacing: 1 }}>
              O&M MANUAL VIEWER
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ position: 'relative', width: 260 }}>
            <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontSize: 12 }}>🔍</span>
            <input
              ref={searchInputRef}
              type="text"
              placeholder="Search specifications, limits, logs..."
              value={searchQuery}
              onChange={e => handleSearchChange(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 12px 6px 30px',
                background: 'rgba(255,255,255,0.03)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                outline: 'none',
                transition: 'border-color 0.15s'
              }}
              onFocus={e => e.target.style.borderColor = 'var(--border-bright)'}
              onBlur={e => e.target.style.borderColor = 'var(--border)'}
            />
            {searchQuery && (
              <button 
                onClick={() => handleSearchChange('')}
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: 14
                }}
              >
                ×
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Main Body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {/* Left Sidebar Directory */}
        <div style={{ 
          width: 320, 
          background: 'var(--bg-panel)', 
          borderRight: '1px solid var(--border)', 
          display: 'flex', 
          flexDirection: 'column', 
          overflow: 'hidden'
        }}>
          <div style={{ 
            padding: 16, 
            fontSize: 11, 
            fontFamily: 'var(--font-mono)', 
            color: 'var(--text-muted)', 
            letterSpacing: 1, 
            textTransform: 'uppercase',
            borderBottom: '1px solid rgba(255,255,255,0.03)'
          }}>
            Documents Directory
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {loading ? (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: 20, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                Loading directory...
              </div>
            ) : error ? (
              <div style={{ color: 'var(--accent-red)', textAlign: 'center', padding: 20, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                Directory error
              </div>
            ) : (
              filteredManuals.map((m, idx) => {
                const isActive = activeSectionIdx === idx;
                const devMeta = m.metadata.find(meta => meta.label.toLowerCase() === 'device');
                const modelMeta = m.metadata.find(meta => meta.label.toLowerCase() === 'model');
                
                return (
                  <button
                    key={idx}
                    onClick={() => handleSectionSelect(idx)}
                    style={{
                      background: isActive ? 'var(--bg-elev)' : 'transparent',
                      border: '1px solid ' + (isActive ? 'var(--border-bright)' : 'transparent'),
                      borderRadius: 8,
                      padding: 12,
                      textAlign: 'left',
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                      outline: 'none',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 4
                    }}
                    onMouseEnter={e => { if(!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.02)' }}
                    onMouseLeave={e => { if(!isActive) e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center' }}>
                      <span style={{ 
                        fontFamily: 'var(--font-ui)', 
                        fontWeight: 600, 
                        fontSize: 13, 
                        color: isActive ? 'var(--accent-cobalt)' : 'var(--text-primary)'
                      }}>
                        {m.title}
                      </span>
                      {m.matchCount > 0 && (
                        <span style={{ 
                          fontSize: 9, 
                          fontFamily: 'var(--font-mono)', 
                          background: 'rgba(217,166,78,0.1)', 
                          color: 'var(--accent-amber)', 
                          padding: '2px 6px', 
                          borderRadius: 4, 
                          fontWeight: 600 
                        }}>
                          {m.matchCount} matches
                        </span>
                      )}
                    </div>
                    
                    {devMeta && (
                      <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
                        {devMeta.value}
                      </div>
                    )}
                    
                    {modelMeta && (
                      <div style={{ 
                        fontSize: 10, 
                        fontFamily: 'var(--font-mono)', 
                        color: 'var(--text-dim)',
                        marginTop: 2
                      }}>
                        {modelMeta.value}
                      </div>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right Reader Workspace */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {loading ? (
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>RETRIEVING DOCUMENT MANUALS</div>
              <div style={{ width: 120, height: 2, background: 'var(--border)', position: 'relative', overflow: 'hidden', borderRadius: 1 }}>
                <div style={{ position: 'absolute', height: '100%', width: '40%', background: 'var(--accent-cobalt)', animation: 'pulse 1.5s infinite ease-in-out' }} />
              </div>
            </div>
          ) : error ? (
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', gap: 16, padding: 40 }}>
              <span style={{ fontSize: 32 }}>⚠️</span>
              <div style={{ fontSize: 14, color: 'var(--accent-red)', fontFamily: 'var(--font-mono)' }}>ERROR: {error}</div>
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>Could not load device documentation from backend API.</p>
            </div>
          ) : !activeManual ? (
            <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--text-dim)' }}>
              No document selected.
            </div>
          ) : (
            <>
              {/* Document Banner & Info Card */}
              <div style={{ 
                padding: '24px 30px', 
                borderBottom: '1px solid var(--border)',
                background: 'rgba(255,255,255,0.01)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                flexShrink: 0
              }}>
                <div>
                  <h1 style={{ margin: '0 0 12px 0', fontSize: 22, fontWeight: 700, letterSpacing: -0.2 }}>
                    <HighlightText text={activeManual.title} search={searchQuery} />
                  </h1>
                  
                  {/* Metadata Tags Row */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {activeManual.metadata.map((meta, i) => (
                      <div 
                        key={i} 
                        style={{
                          fontSize: 11,
                          fontFamily: 'var(--font-mono)',
                          background: 'rgba(255,255,255,0.03)',
                          border: '1px solid var(--border)',
                          borderRadius: 4,
                          padding: '3px 8px',
                          color: 'var(--text-muted)'
                        }}
                      >
                        <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>{meta.label}:</span>
                        <span style={{ color: 'var(--text-primary)' }}>
                          <HighlightText text={meta.value} search={searchQuery} />
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Sub-navigation Tabs */}
              <div style={{ 
                padding: '0 30px', 
                borderBottom: '1px solid var(--border)', 
                display: 'flex',
                gap: 20,
                flexShrink: 0
              }}>
                {[
                  { id: 'all', label: 'All Content' },
                  { id: 'specs', label: 'Specifications' },
                  { id: 'limits', label: 'Operating Limits' },
                  { id: 'diag', label: 'Diagnostics & Failure Modes' },
                  { id: 'schedule', label: 'Maintenance Schedule' }
                ].map(tab => {
                  const hasMatchingContent = tab.id === 'all' || activeManual.subSections.some(sub => getSubSectionType(sub.header) === tab.id);
                  if (!hasMatchingContent) return null;

                  const isSelected = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        borderBottom: '2px solid ' + (isSelected ? 'var(--accent-cobalt)' : 'transparent'),
                        padding: '14px 0',
                        fontSize: 12.5,
                        fontWeight: isSelected ? 600 : 400,
                        color: isSelected ? 'var(--text-primary)' : 'var(--text-muted)',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                        outline: 'none'
                      }}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              {/* Scrollable Reader Panel */}
              <div style={{ 
                flex: 1, 
                overflowY: 'auto', 
                padding: 30
              }}>
                <div style={{ maxWidth: 840, margin: '0 auto' }}>
                  {activeSubSections.length === 0 ? (
                    <div style={{ textAlign: 'center', color: 'var(--text-dim)', padding: 40, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                      No content sections found in this category.
                    </div>
                  ) : (
                    activeSubSections.map(renderSubSection)
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
