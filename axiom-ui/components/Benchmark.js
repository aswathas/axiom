'use client';

import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell,
} from 'recharts';

const pct = (v) => `${(v * 100).toFixed(1)}%`;

// 'drug_drug_interaction' -> 'drug-drug interaction', not 'drug drug'
const prettyType = (k) => k.replace(/_/g, ' ').replace('drug drug', 'drug-drug');

export default function Benchmark({ fixture }) {
  const b = fixture.benchmark;
  const er = b.entity_resolution || {};

  const metrics = [
    { l: 'DETECTION RATE', v: pct(b.detection_rate),
      d: `${b.planted_detected} of ${b.planted_total} planted findings`,
      warn: b.detection_rate < 0.95 },
    { l: 'UNSUPPORTED CLAIMS', v: pct(b.unsupported_claim_rate),
      d: `${b.claims_examined} claims examined` },
    { l: 'CITATION VALIDITY', v: pct(b.citation_validity),
      d: 'every claim resolves to a real node' },
    { l: 'FALSE POSITIVES', v: pct(b.false_positive_rate),
      d: `${b.clean_patients_examined} clean patients examined` },
    { l: 'ABSTENTION RECALL', v: pct(b.abstention_recall),
      d: 'unanswerable questions refused' },
    { l: 'NEGATION ACCURACY', v: pct(b.negation_accuracy),
      d: '"denies" never became "has"' },
  ];

  const sweep = (b.robustness_sweep || []).map((r) => ({
    noise: `noise ${r.noise_level.toFixed(2)}`,
    rate: r.detection_rate,
  }));

  return (
    <div style={{ marginTop: 20 }}>
      <div className="metrics">
        {metrics.map((m) => (
          <div key={m.l} className={`metric ${m.warn ? 'warn' : ''}`}>
            <div className="metric-l">{m.l}</div>
            <div className="metric-v">{m.v}</div>
            <div className="metric-d">{m.d}</div>
          </div>
        ))}
      </div>

      <section className="card" style={{ marginTop: 18 }}>
        <div className="card-title">
          <span>ROBUSTNESS UNDER DEGRADED DATA</span>
          <span style={{ color: 'var(--grey)' }}>show this, not the headline</span>
        </div>
        <div style={{ height: 190 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={sweep} margin={{ top: 8, right: 12, bottom: 4, left: -18 }}>
              <XAxis dataKey="noise" tick={{ fontSize: 10, fill: '#8a8a8a' }}
                     tickLine={false} axisLine={{ stroke: '#ddd8cc' }} />
              <YAxis domain={[0.7, 1.02]} tick={{ fontSize: 10, fill: '#8a8a8a' }}
                     tickLine={false} axisLine={{ stroke: '#ddd8cc' }}
                     tickFormatter={(v) => v.toFixed(2)} />
              <Tooltip
                cursor={{ fill: '#f4f2ec' }}
                contentStyle={{ fontSize: 11, borderRadius: 4, border: '1px solid #e4dfd2' }}
                formatter={(v) => [v.toFixed(3), 'detection rate']}
              />
              <Bar dataKey="rate" radius={[3, 3, 0, 0]}>
                {sweep.map((r, i) => (
                  <Cell key={i} fill={i === 0 ? '#1b4f8a' : '#7fa3c8'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p style={{ fontSize: 12, color: 'var(--grey)', lineHeight: 1.55, marginTop: 8 }}>
          Unit chaos, missing reference ranges, case drift and coding inconsistency
          injected at increasing levels. Degradation is graceful rather than cliff-edged.
          This is the only figure here that predicts real-world behaviour.
        </p>
      </section>

      <div className="missed">
        <h4>HERE IS WHAT WE MISSED — {b.MISSED} of {b.planted_total}</h4>
        <p>
          All {b.MISSED} misses were drug–drug interactions where the system
          correctly identified the interacting pair but cited a pre-existing
          prescription instance rather than the planted one. The clinical finding
          was still surfaced; only the node attribution differed. Entity resolution
          scored P/R/F1 = {er.precision?.toFixed(2)}/{er.recall?.toFixed(2)}/{er.f1?.toFixed(2)}{' '}
          across {er.negative_pairs_tested} negative pairs, with the closest
          non-match scoring {er.max_negative_score} against a threshold of{' '}
          {er.threshold} — a margin of {er.margin}, which is thin and would need
          manual review for ambiguous pairs on real data.
        </p>
      </div>

      <section className="card" style={{ marginTop: 18 }}>
        <div className="card-title"><span>DETECTION BY PLANTED FINDING TYPE</span></div>
        {Object.entries(b.by_type).map(([k, v]) => (
          <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0' }}>
            <span style={{ fontSize: 12, color: 'var(--grey-d)', width: 200 }}>
              {prettyType(k)}
            </span>
            <div style={{ flex: 1, height: 8, background: '#f0ece3', borderRadius: 4 }}>
              <div style={{ width: `${v.rate * 100}%`, height: '100%', background: '#c8901e', borderRadius: 4 }} />
            </div>
            <span style={{ fontSize: 11.5, fontFamily: 'monospace', color: 'var(--grey-d)', width: 78 }}>
              {v.detected}/{v.planted} ({pct(v.rate)})
            </span>
          </div>
        ))}
      </section>

      <div className="limit" style={{ marginTop: 18 }}>
        <h4>LIMITATIONS — READ BEFORE QUOTING ANY NUMBER ABOVE</h4>
        <ol>
          {fixture.limitations.map((l, i) => <li key={i}>{l}</li>)}
        </ol>
      </div>
    </div>
  );
}