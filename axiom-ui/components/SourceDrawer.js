'use client';

const LABELS = {
  id: 'node id', type: 'type', time: 'time', code: 'code', display: 'display',
  value: 'value', unit: 'unit', ref_low: 'ref low', ref_high: 'ref high',
  drug: 'drug', dose: 'dose', substance: 'substance', reaction: 'reaction',
  severity: 'severity', observed_at: 'observed at', facility: 'facility',
  loinc: 'loinc', modality: 'modality', body_site: 'body site',
};

export default function SourceDrawer({ source, onClose }) {
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
          <div>
            <div style={{ fontSize: 10, color: 'var(--gold-dim)', fontWeight: 800, letterSpacing: 1 }}>
              SOURCE RECORD
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4 }}>{source.label}</div>
          </div>
          <button
            onClick={onClose}
            style={{
              border: '1px solid var(--line)', background: 'var(--white)', borderRadius: 4,
              padding: '6px 11px', cursor: 'pointer', fontSize: 12, fontFamily: 'inherit',
            }}
          >
            Close
          </button>
        </div>

        <p style={{ fontSize: 12, color: 'var(--grey)', lineHeight: 1.5, margin: '0 0 16px' }}>
          This is the raw record behind the citation. Nothing on the claim screen
          exists without a node like this one.
        </p>

        <div className="source">
          <div className="source-id">{source.id} · {source.type}</div>
          {Object.entries(source.raw || {}).map(([k, v]) => (
            <div key={k} className="source-row">
              <span className="source-k">{LABELS[k] || k}</span>
              <span className="source-v">{v === null || v === undefined ? '—' : String(v)}</span>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 18, padding: '12px 14px', background: '#eef3f9',
                      borderLeft: '4px solid var(--blue)', borderRadius: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--blue)', fontWeight: 800, letterSpacing: 0.8, marginBottom: 6 }}>
            PROVENANCE
          </div>
          <div style={{ fontSize: 12, color: 'var(--grey-d)', lineHeight: 1.65 }}>
            Claim → node <code>{source.id}</code> → raw record above.
            Two clicks, always resolvable. Refusals are logged the same way.
          </div>
        </div>

        <div style={{ marginTop: 14, fontSize: 11, color: 'var(--grey)', lineHeight: 1.6 }}>
          Data posture: 100% synthetic. No real PHI at any point in this system.
        </div>
      </div>
    </div>
  );
}