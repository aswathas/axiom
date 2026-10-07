'use client';

import { API } from '../lib/api';
import { Chip, LoadingCards, Notice, OfflineNotice } from './Chrome';

/**
 * Scene 01 — `GET /api/patients`.
 *
 * A card per patient showing identity plus the two counts that matter for a
 * demo: how many documents back the record, and how many typed nodes the graph
 * built from it. `node_count: 0` on a record with documents is a real signal,
 * so it is shown as a chip rather than hidden.
 */
export default function PatientList({ state, onOpen, onRetry }) {
  if (state.loading) {
    return (
      <>
        <h1 className="page">Patients</h1>
        <p className="lede">Reading the case list from the AXIOM store.</p>
        <LoadingCards n={3} label="Loading patients" />
      </>
    );
  }

  return (
    <>
      <h1 className="page">Patients</h1>
      <p className="lede">
        Every record is reconstructed from uploaded documents into a typed,
        time-stamped graph. Click a patient to open the chart.
      </p>

      {state.offline && (
        <OfflineNotice api={API} onRetry={onRetry} reason={state.reason} />
      )}

      <div className="pt-grid">
        {state.rows.map((p) => {
          const empty = Number(p.node_count) === 0;
          return (
            <button
              key={p.id}
              type="button"
              className="pt-card"
              onClick={() => onOpen(p.id)}
              aria-label={`Open chart for ${p.name}, MRN ${p.mrn}`}
            >
              <div className="pt-card-name">{p.name || p.id}</div>
              <div className="pt-card-dem">
                DOB {p.dob || '—'} · {p.mrn || 'no MRN'}
              </div>
              <div style={{ marginTop: 9, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Chip kind="info">{p.doc_count ?? 0} documents</Chip>
                <Chip kind={empty ? 'mute' : 'ok'}>
                  {p.node_count ?? 0} graph nodes
                </Chip>
                {empty && <Chip kind="mute">no provenance yet</Chip>}
              </div>
              <div className="pt-card-stats">
                <div>
                  <div className="stat-l">id</div>
                  <div className="pt-card-dem">{p.id}</div>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {state.rows.length === 0 && !state.offline && (
        <Notice tone="warn" title="NO PATIENTS IN THE STORE">
          The backend answered successfully with an empty list. Ingest a
          document on the Ingest screen, or point <code>{API}</code> at a
          database that has records.
        </Notice>
      )}

      {state.rows.length === 0 && state.offline && (
        <Notice tone="warn" title="NO FALLBACK PATIENTS AVAILABLE">
          The backend is unreachable and the inline dataset returned nothing.
          This is a bug in the fallback fixture, not an empty database — check
          <code>axiom-ui/lib/fixtures.js</code>.
        </Notice>
      )}
    </>
  );
}