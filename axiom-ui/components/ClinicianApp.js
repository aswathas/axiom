'use client';

import { useState } from 'react';
import TrendChart from './TrendChart';
import Timeline from './Timeline';
import Benchmark from './Benchmark';
import SourceDrawer from './SourceDrawer';

const SEV = { critical: 'critical', high: 'high', medium: 'medium', low: 'low' };
const SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };

function Chip({ kind, children }) {
  return <span className={`chip ${kind}`}>{children}</span>;
}

export default function ClinicianApp({ fixture }) {
  const [scene, setScene] = useState(0);
  const [selected, setSelected] = useState(null);
  const [openSource, setOpenSource] = useState(null);

  const scenes = fixture.scenes;
  const cur = scenes[scene];
  const { patient, meta, graph, trend } = fixture;

  // Attention queue is derived ONLY from claims the pipeline actually
  // published, and severity comes from the pipeline too.
  //
  // It did NOT used to: an earlier build fuzzy-matched claim text against the
  // planted descriptions in JavaScript to infer severity, and almost every
  // match failed — which rendered a CRITICAL warfarin/ibuprofen bleeding
  // interaction as LOW. Inferring clinical severity by string matching in the
  // browser is precisely the failure mode this project exists to eliminate.
  // The pipeline knows the severity; the UI renders it.
  const queue = [];
  scenes.forEach((s) => {
    (s.published || []).forEach((c) => {
      queue.push({
        claim: c,
        scene: scenes.indexOf(s),
        severity: c.severity || 'info',
        type: c.claim_type,
      });
    });
  });
  queue.sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9));

  const openClaim = selected != null ? queue[selected] : null;

  function selectClaim(i) {
    setSelected(i);
    setOpenSource(null);
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div>
            <div className="brand">{meta.product}</div>
            <div className="brand-sub">AI-NATIVE CLINICAL ASSISTANCE</div>
          </div>
          <div className="topbar-meta">
            <div>{meta.district}</div>
            <div style={{ color: '#6e6e6e' }}>{meta.data_posture}</div>
          </div>
        </div>
      </header>

      <div className="boundary">{meta.boundary}</div>

      <main className="shell">
        <div className="nav">
          {scenes.map((s, i) => (
            <button
              key={s.id}
              className={`navbtn ${i === scene ? 'active' : ''}`}
              onClick={() => { setScene(i); setSelected(null); setOpenSource(null); }}
            >
              <span className="navbtn-t">{s.beat}</span>
              <span className="navbtn-n">{s.screen}</span>
            </button>
          ))}
        </div>

        <h1 className="page">{cur.screen}</h1>
        <p className="lede">{cur.narration}</p>

        {/* ---------------- patient header, always visible ---------------- */}
        <section className="card">
          <div className="pt-header">
            <div>
              <div className="pt-name">{patient.demographics.name}</div>
              <div className="pt-dem">
                DOB {patient.demographics.dob} · {patient.demographics.sex} ·{' '}
                {patient.demographics.mrn}
              </div>
              <div className="pt-dem" style={{ marginTop: 2, color: 'var(--green)' }}>
                synthetic record — no real patient data
              </div>
            </div>
            <div className="stat-row">
              <div className="stat"><div className="stat-n">{graph.stats.nodes}</div><div className="stat-l">graph nodes</div></div>
              <div className="stat"><div className="stat-n">{graph.stats.edges}</div><div className="stat-l">typed edges</div></div>
              <div className="stat"><div className="stat-n">{patient.encounters}</div><div className="stat-l">encounters</div></div>
            </div>
          </div>
        </section>

        {/* ---------------- SCENE: patient chart / attention queue -------- */}
        {(cur.id === 's1' || cur.id === 's2') && (
          <div className="cols">
            <div>
              <section className="card">
                <div className="card-title">
                  <span>ATTENTION QUEUE</span>
                  <Chip kind="info">{queue.length} surfaced</Chip>
                </div>
                {queue.length === 0 && (
                  <p style={{ fontSize: 13, color: 'var(--grey)' }}>
                    No claims published for this scene.
                  </p>
                )}
                {queue.map((q, i) => (
                  <div
                    key={i}
                    className={`qitem ${selected === i ? 'selected' : ''}`}
                    onClick={() => selectClaim(i)}
                  >
                    <div className="qitem-head">
                      <Chip kind={SEV[q.severity] || 'low'}>{q.severity}</Chip>
                      <span className="qitem-type">{q.type.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="qitem-text">{q.claim.text}</div>
                  </div>
                ))}
              </section>

              {openClaim && (
                <section className="card">
                  <div className="card-title">
                    <span>EVIDENCE — {openClaim.claim.claim_id.toUpperCase()}</span>
                    <Chip kind="ok">verified</Chip>
                  </div>
                  <div className="claim">
                    <div className="claim-head">
                      <span className="claim-id">
                        {openClaim.claim.claim_id} · calibrated{' '}
                        {openClaim.claim.calibrated_score}
                      </span>
                    </div>
                    <div className="claim-text">{openClaim.claim.text}</div>
                    <div className="cites">
                      {(openClaim.claim.source_records || []).map((s) => (
                        <button
                          key={s.id}
                          className="cite"
                          onClick={() => setOpenSource(s)}
                        >
                          {s.id}
                        </button>
                      ))}
                    </div>
                    <div className="verified">
                      ✓ {openClaim.claim.verdict} — every statement traced to source
                    </div>
                  </div>

                  {trend && trend.series.length > 1 && (
                    <>
                      <div className="card-title" style={{ marginTop: 20 }}>
                        <span>{trend.display.toUpperCase()} TRAJECTORY</span>
                        <span style={{ color: 'var(--grey)' }}>
                          {trend.summary.change_pct}% change
                        </span>
                      </div>
                      <TrendChart trend={trend} />
                      <p style={{ fontSize: 11.5, color: 'var(--grey)', marginTop: 8 }}>
                        Plotted from the clinical graph, not retrieved as text.
                        Reference band {trend.ref_low}–{trend.ref_high} {trend.unit}.
                      </p>
                    </>
                  )}
                </section>
              )}
            </div>

            <div>
              <PlantedTruth fixture={fixture} />
              <GraphStats graph={graph} />
            </div>
          </div>
        )}

        {/* ---------------- SCENE: interaction ---------------- */}
        {cur.id === 's3' && (
          <div className="cols">
            <div>
              <ClaimsList claims={cur.published} onCite={setOpenSource} />
              {(cur.abstained || []).length > 0 && (
                <Withheld claims={cur.abstained} />
              )}
            </div>
            <div>
              <InteractionPanel graph={graph} />
              <GraphStats graph={graph} />
            </div>
          </div>
        )}

        {/* ---------------- SCENE: THE TURN — refusal ---------------- */}
        {cur.id === 's4' && (
          <div className="cols">
            <div>
              <div className="refusal">
                <div className="refusal-q">
                  Q: <span style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>
                    {cur.query}
                  </span>
                </div>
                <div className="refusal-a">REFUSED</div>
                <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--ink)', margin: '0 0 4px' }}>
                  This record cannot support an answer to that question:{' '}
                  <strong>{cur.refusal_reason}</strong>
                </p>
                <div className="refusal-meta">
                  <div>
                    <strong>Routed to:</strong>{' '}
                    {(cur.abstained[0] || {}).escalate_to || 'records request'}
                  </div>
                  <div><strong>Audit ref:</strong> {cur.audit_ref}</div>
                  <div>
                    <strong>Refused at:</strong> coverage check — no query plan
                    was executed, because the concept is not representable in
                    this record schema
                  </div>
                </div>
                <div className="refusal-note">
                  Absence of documentation is not absence of the condition. A refusal
                  is a confident, useful answer — never an error state.
                </div>
              </div>

              <section className="card" style={{ marginTop: 18 }}>
                <div className="card-title"><span>ALSO REFUSED — THE SAME RULE, APPLIED</span></div>
                <RefusalList />
              </section>
            </div>

            <div>
              <section className="card">
                <div className="card-title"><span>WHY THIS MATTERS</span></div>
                <p style={{ fontSize: 13, lineHeight: 1.65, color: 'var(--grey-d)', margin: 0 }}>
                  In this domain the failure modes are asymmetric. A missing answer
                  costs the clinician one more minute. A confident wrong answer about
                  a drug interaction can reach a patient.
                </p>
                <p style={{ fontSize: 13, lineHeight: 1.65, color: 'var(--grey-d)', margin: '12px 0 0' }}>
                  Every other project in this track will demonstrate that it
                  <em> answers well</em>. This is the beat nobody else will show:
                  the system knows when not to.
                </p>
              </section>
              <PlantedTruth fixture={fixture} />
            </div>
          </div>
        )}

        {/* ---------------- SCENE: benchmark ---------------- */}
        {cur.id === 's5' && <Benchmark fixture={fixture} />}

        {cur.query && (
          <div className="narration">
            <strong>Query:</strong> <code>{cur.query}</code>
          </div>
        )}
      </main>

      {openSource && <SourceDrawer source={openSource} onClose={() => setOpenSource(null)} />}

      <style jsx>{`
        .drawer-backdrop {
          position: fixed; inset: 0; background: rgba(20, 20, 20, 0.42);
          display: flex; justify-content: flex-end; z-index: 50;
        }
        .drawer {
          background: var(--white); width: 430px; max-width: 92vw; height: 100%;
          overflow-y: auto; padding: 22px 24px; box-shadow: -3px 0 16px rgba(0,0,0,0.18);
        }
      `}</style>
    </>
  );
}

/* ------------------------------------------------------------------ */
function ClaimsList({ claims, onCite }) {
  if (!claims || claims.length === 0)
    return <section className="card"><p style={{ fontSize: 13, color: 'var(--grey)' }}>No published claims.</p></section>;
  return (
    <section className="card">
      <div className="card-title">
        <span>VERIFIED CLAIMS</span>
        <Chip kind="ok">{claims.length} published</Chip>
      </div>
      {claims.map((c) => (
        <div key={c.claim_id} className="claim">
          <div className="claim-head">
            <span className="claim-id">{c.claim_id} · calibrated {c.calibrated_score}</span>
            <Chip kind="info">{c.claim_type.replace(/_/g, ' ')}</Chip>
          </div>
          <div className="claim-text">{c.text}</div>
          <div className="cites">
            {(c.source_records || []).map((s) => (
              <button key={s.id} className="cite" onClick={() => onCite(s)}>{s.id}</button>
            ))}
          </div>
          <div className="verified">✓ {c.verdict}</div>
        </div>
      ))}
    </section>
  );
}

function Withheld({ claims }) {
  return (
    <section className="card">
      <div className="card-title"><span>WITHHELD</span></div>
      {claims.map((c, i) => (
        <div key={i} className="claim" style={{ borderLeft: '4px solid var(--crit)' }}>
          <div className="claim-head">
            <span className="claim-id">{c.claim_id}</span>
            <Chip kind="critical">{c.action}</Chip>
          </div>
          <div className="claim-text">{c.text}</div>
          <div style={{ fontSize: 11.5, color: 'var(--grey-d)' }}>
            {c.message} · routed to {c.escalate_to}
          </div>
        </div>
      ))}
    </section>
  );
}

function InteractionPanel({ graph }) {
  const inter = graph.interaction_edges || [];
  const contra = graph.contraindications || [];
  return (
    <section className="card">
      <div className="card-title">
        <span>STRUCTURED RELATIONSHIPS</span>
        <Chip kind="info">graph edges</Chip>
      </div>
      {contra.map((c, i) => (
        <div key={i} className="qitem" style={{ borderLeftColor: 'var(--crit)', cursor: 'default' }}>
          <div className="qitem-head">
            <Chip kind="critical">{c.severity}</Chip>
            <span className="qitem-type">contraindication</span>
          </div>
          <div className="qitem-text">
            Documented {c.severity} {c.substance} allergy ({c.reaction}) while{' '}
            {c.substance} is actively prescribed.
          </div>
        </div>
      ))}
      {inter.length === 0 && contra.length === 0 && (
        <p style={{ fontSize: 12.5, color: 'var(--grey)' }}>No typed conflicts in this record.</p>
      )}
      <p style={{ fontSize: 11.5, color: 'var(--grey)', marginTop: 10, lineHeight: 1.5 }}>
        These are <code>contraindicated_with</code> edges in the temporal graph — not
        keyword matches in a document store.
      </p>
    </section>
  );
}

function PlantedTruth({ fixture }) {
  const planted = fixture.patient.planted || [];
  return (
    <section className="card">
      <div className="card-title">
        <span>PLANTED GROUND TRUTH</span>
        <Chip kind="info">answer key</Chip>
      </div>
      {planted.map((f) => (
        <div key={f.id} style={{ marginBottom: 13 }}>
          <div className="qitem-head">
            <Chip kind={SEV[f.severity] || 'low'}>{f.severity}</Chip>
            <span className="qitem-type">{f.type.replace(/_/g, ' ')}</span>
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--grey-d)', lineHeight: 1.5 }}>
            {f.description}
          </div>
        </div>
      ))}
      <p style={{ fontSize: 11.5, color: 'var(--grey)', lineHeight: 1.5, margin: '12px 0 0' }}>
        The answer key the system is graded against — planted at known type,
        severity and timestamp.
      </p>
    </section>
  );
}

function GraphStats({ graph }) {
  const s = graph.stats;
  return (
    <section className="card">
      <div className="card-title"><span>CLINICAL GRAPH</span></div>
      <div className="stat-row" style={{ marginBottom: 14 }}>
        <div className="stat" style={{ textAlign: 'left' }}>
          <div className="stat-n">{s.nodes}</div><div className="stat-l">nodes</div>
        </div>
        <div className="stat" style={{ textAlign: 'left' }}>
          <div className="stat-n">{s.edges}</div><div className="stat-l">edges</div>
        </div>
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--grey)' }}>
        {Object.entries(s.by_type).map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
            <span>{k}</span><span style={{ fontFamily: 'monospace' }}>{v}</span>
          </div>
        ))}
      </div>
      <Timeline graph={graph} />
    </section>
  );
}

function RefusalList() {
  const examples = [
    ['What is this patient’s blood type?', 'no blood-bank resource in the record schema'],
    ['Has the patient ever had a stroke?', 'no cerebrovascular code documented — absence of documentation ≠ absence of condition'],
    ['What is the family history of cardiac disease?', 'family history is not modelled as a node type'],
    ['What is the patient’s insurance plan?', 'no payer/claims resource in the record schema'],
  ];
  return (
    <div>
      {examples.map(([q, r], i) => (
        <div key={i} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--ink)', marginBottom: 3 }}>
            {q}
          </div>
          <div style={{ fontSize: 12, color: 'var(--crit)' }}>
            REFUSED — {r}
          </div>
        </div>
      ))}
    </div>
  );
}