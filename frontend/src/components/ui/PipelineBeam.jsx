import { memo } from 'react'

// Animated SVG beam diagram — shows the 5-node diagnostic pipeline with
// CSS-animated dashes traveling along active segments.
// Lives only in the /diagnostics tab (separate window from the 3D dashboard).
// GPU-composited: only stroke-dashoffset repaints, nothing on the main thread.

const NODES = [
  { key: 'alert',   label: 'Alert',    icon: '⚡' },
  { key: 'neo4j',   label: 'Neo4j KG', icon: '◈'  },
  { key: 'chroma',  label: 'ChromaDB', icon: '⬡'  },
  { key: 'llm',     label: 'LLM',      icon: '◎'  },
  { key: 'report',  label: 'Report',   icon: '✓'  },
]

// Beam segment i connects node i → node i+1.
// active threshold = shownOrder at which the beam starts traveling.
// done  threshold  = shownOrder at which it becomes a solid line.
const BEAMS = [
  { active: 1, done: 2 },
  { active: 2, done: 4 },
  { active: 4, done: 6 },
  { active: 6, done: 7 },
]

const W      = 600
const H      = 86
const CY     = 34
const R_OUTER = 22
const R_INNER = 17
// Node X centres, evenly distributed
const NX = [44, 182, 300, 418, 556]

const PipelineBeam = memo(function PipelineBeam({ shownOrder = 0, isError = false, accent = 'var(--accent-cobalt)' }) {
  return (
    <div style={{ width: '100%', overflowX: 'auto', marginBottom: 24 }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
        style={{ display: 'block', minWidth: 360 }}>

        {/* Beam segments */}
        {BEAMS.map((b, i) => {
          const x1 = NX[i]     + R_INNER + 3
          const x2 = NX[i + 1] - R_INNER - 3
          const isDone   = shownOrder >= b.done
          const isActive = !isDone && shownOrder >= b.active && !isError
          const segColor = isDone ? 'var(--accent-green)'
            : isActive            ? accent
            :                       'var(--border-solid)'

          return (
            <g key={i}>
              {/* Static base line */}
              <line x1={x1} y1={CY} x2={x2} y2={CY}
                stroke="var(--border-solid)" strokeWidth={1.5} />
              {/* Active / done overlay */}
              {(isActive || isDone) && (
                <line x1={x1} y1={CY} x2={x2} y2={CY}
                  stroke={segColor} strokeWidth={isDone ? 2 : 1.5}
                  strokeDasharray={isDone ? 'none' : '7 5'}
                  style={isActive ? { animation: 'beam-travel 0.6s linear infinite' } : {}} />
              )}
              {/* Arrowhead */}
              <polygon
                points={`${x2},${CY - 4} ${x2 + 6},${CY} ${x2},${CY + 4}`}
                fill={isDone ? 'var(--accent-green)' : isActive ? accent : 'var(--border-solid)'}
                opacity={0.7}
              />
            </g>
          )
        })}

        {/* Nodes */}
        {NODES.map((node, i) => {
          // Node i is "lit" once the incoming beam has started (beam i-1 is active),
          // and "done" once the outgoing beam has completed (beam i is done).
          const inDone    = i === 0 || shownOrder >= BEAMS[i - 1]?.done
          const outDone   = i === NODES.length - 1 ? shownOrder >= 7 : shownOrder >= BEAMS[i]?.done
          const isLit     = i === 0 ? shownOrder >= 1 : shownOrder >= (BEAMS[i - 1]?.active ?? 99)
          const nodeError = isError && isLit && !outDone

          const strokeColor = nodeError ? '#e06054'
            : outDone || (i === NODES.length - 1 && shownOrder >= 7) ? 'var(--accent-green)'
            : isLit   ? accent
            :           'var(--border-solid)'

          const fillColor = nodeError    ? 'rgba(224,96,84,0.14)'
            : outDone     ? 'rgba(70,177,127,0.14)'
            : isLit       ? 'rgba(91,141,239,0.10)'
            :               'transparent'

          const x = NX[i]

          return (
            <g key={node.key}>
              {/* Outer halo ring */}
              <circle cx={x} cy={CY} r={R_OUTER}
                fill="transparent" stroke={strokeColor} strokeWidth={0.6} opacity={0.3} />
              {/* Main circle */}
              <circle cx={x} cy={CY} r={R_INNER}
                fill={fillColor} stroke={strokeColor} strokeWidth={1.5}
                style={{ transition: 'fill 0.4s, stroke 0.4s' }} />
              {/* Icon */}
              <text x={x} y={CY + 4} textAnchor="middle"
                fontSize={11} fill={strokeColor} fontFamily="monospace" style={{ userSelect: 'none' }}>
                {node.icon}
              </text>
              {/* Label below */}
              <text x={x} y={CY + R_OUTER + 14} textAnchor="middle"
                fontSize={8} fill="var(--text-muted)" fontFamily="var(--font-mono)"
                style={{ userSelect: 'none' }}>
                {node.label}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
})

export default PipelineBeam
