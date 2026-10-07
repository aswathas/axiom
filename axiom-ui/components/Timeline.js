'use client';

import { useMemo } from 'react';

const TYPE_COLOR = {
  Encounter: '#141414',
  Diagnosis: '#c8901e',
  LabResult: '#1b4f8a',
  MedicationOrder: '#2e7d52',
  Allergy: '#8c1d18',
  ImagingStudy: '#7a5a0b',
  Note: '#8a8a8a',
  VitalSeries: '#4a4a4a',
};

const LANES = ['Encounter', 'Diagnosis', 'LabResult', 'MedicationOrder',
               'Allergy', 'ImagingStudy', 'Note', 'VitalSeries'];

/**
 * Temporal clinical graph as a lane chart.
 *
 * Every node is time-stamped and placed on its own lane by type, so temporal
 * reasoning becomes VISIBLE rather than magical — this is the layer that a
 * chunk-retrieval system structurally cannot represent.
 */
export default function Timeline({ graph }) {
  const { nodes } = graph;

  const { min, max, positioned } = useMemo(() => {
    const times = nodes.map((n) => new Date(n.time).getTime()).filter((t) => !isNaN(t));
    const lo = Math.min(...times);
    const hi = Math.max(...times);
    const span = hi - lo || 1;
    const pos = nodes
      .filter((n) => !isNaN(new Date(n.time).getTime()))
      .map((n) => {
        const lane = LANES.indexOf(n.type);
        return {
          ...n,
          lane: lane >= 0 ? lane : LANES.length - 1,
          pct: ((new Date(n.time).getTime() - lo) / span) * 100,
        };
      });
    return { min: lo, max: hi, positioned: pos };
  }, [nodes]);

  const H = LANES.length * 22 + 26;

  return (
    <div style={{ marginTop: 16 }}>
      <div style={{ fontSize: 10, color: '#8a8a8a', letterSpacing: 0.8, fontWeight: 700, marginBottom: 8 }}>
        TEMPORAL GRAPH — {positioned.length} EVENTS ON A TIME AXIS
      </div>

      <svg width="100%" height={H} style={{ display: 'block' }} role="img"
           aria-label="Temporal clinical graph timeline">
        {LANES.map((lane, i) => (
          <g key={lane}>
            <line
              x1="78" x2="100%" y1={i * 22 + 14} y2={i * 22 + 14}
              stroke="#eee9df" strokeWidth="1"
            />
            <text x="2" y={i * 22 + 18} fontSize="9" fill="#8a8a8a" fontFamily="inherit">
              {lane}
            </text>
          </g>
        ))}

        {positioned.map((n) => {
          const x = 78 + (n.pct / 100) * (100 - 78 - 6);
          const y = n.lane * 22 + 14;
          const r = n.type === 'Encounter' ? 5 : 3.5;
          return (
            <g key={n.id}>
              <circle cx={`${x}%`} cy={y} r={r}
                      fill={TYPE_COLOR[n.type] || '#8a8a8a'} opacity="0.88">
                <title>{`${n.type} · ${n.time}\n${n.label}${n.value ? ` = ${n.value} ${n.unit || ''}` : ''}`}</title>
              </circle>
            </g>
          );
        })}
      </svg>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9.5, color: '#8a8a8a', marginTop: 2 }}>
        <span>{new Date(min).toISOString().slice(0, 10)}</span>
        <span>{new Date(max).toISOString().slice(0, 10)}</span>
      </div>
    </div>
  );
}