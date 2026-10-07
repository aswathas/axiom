'use client';

/**
 * Renders the evidence panel.
 *
 * The previous version read pre-baked percentages out of `fixture.json`:
 * a robustness sweep over injected noise levels, a planted-truth detection
 * table, and an F1 score for entity resolution. None of that is derivable
 * from the HTTP API — it comes from the Python benchmark harness — so this
 * component now takes metrics as props and the live-data collector in
 * BenchmarkScreen decides what can honestly be claimed.
 *
 * Where a figure is unavailable it renders as "not measurable from the API"
 * rather than being carried over from a previous run. A benchmark panel that
 * quietly shows stale numbers is worse than one that admits a gap.
 */
export default function Benchmark({ metrics, limitations, notes = [] }) {
  return (
    <div style={{ marginTop: 20 }}>
      <div className="metrics">
        {metrics.map((m) => (
          <div key={m.l} className={`metric ${m.warn ? 'warn' : ''}`}>
            <div className="metric-l">{m.l}</div>
            <div className="metric-v" style={m.na ? { fontSize: 15, color: 'var(--grey)' } : undefined}>
              {m.na ? 'not measurable' : m.v}
            </div>
            <div className="metric-d">{m.d}</div>
          </div>
        ))}
      </div>

      {notes.map((n) => (
        <div key={n.h} className="missed">
          <h4>{n.h}</h4>
          <p>{n.b}</p>
        </div>
      ))}

      <div className="limit" style={{ marginTop: 18 }}>
        <h4>LIMITATIONS — READ BEFORE QUOTING ANY NUMBER ABOVE</h4>
        <ol>
          {(limitations || []).map((l, i) => <li key={i}>{l}</li>)}
        </ol>
      </div>
    </div>
  );
}