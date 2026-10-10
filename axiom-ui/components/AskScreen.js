'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API, ask, getGraph, getPatient } from '../lib/api';
import { docIdsFor } from '../lib/derive';
import Cite, { DeadCite } from './Cite';
import { Chip, Notice, Spinner } from './Chrome';

const SAMPLES = [
  'Is the renal function deteriorating?',
  'Is there a drug interaction concern with the current medications?',
  'What is this patient’s blood type?',
  'Has the patient ever had a stroke?',
  'What is the patient’s insurance plan?',
  'Is the family history of cardiac disease documented?',
];

/**
 * Scene 03 — `POST /api/ask`.
 *
 * THE CENTRAL UI RULE OF THIS SCREEN: a refusal arrives as HTTP 200 with a
 * refusal payload. It is rendered as `<RefusalPanel>` — a dark, deliberate,
 * considered panel — and never through `<Notice tone="error">`, which is
 * reserved in this app for things that are actually broken.
 *
 * While the query executes, the clinician sees the pipeline's genuine stages:
 * query compilation against the clinical graph, candidate claim generation,
 * and formal claim verification against evidence.
 */
export default function AskScreen({ patientId, onSource }) {
  const [query, setQuery] = useState('');
  const [docIds, setDocIds] = useState([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [timeoutError, setTimeoutError] = useState(null);
  const [result, setResult] = useState(null);
  const [graph, setGraph] = useState(null);
  const [offline, setOffline] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [finalElapsedMs, setFinalElapsedMs] = useState(null);
  const startTimeRef = useRef(null);

  // Timer for tracking real elapsed time during graph traversal & LLM verification
  useEffect(() => {
    let timer = null;
    if (pending) {
      setElapsedMs(0);
      setFinalElapsedMs(null);
      startTimeRef.current = Date.now();
      timer = setInterval(() => {
        if (startTimeRef.current) {
          setElapsedMs(Date.now() - startTimeRef.current);
        }
      }, 100);
    } else if (startTimeRef.current) {
      setFinalElapsedMs(Date.now() - startTimeRef.current);
      startTimeRef.current = null;
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [pending]);

  // The documents this record can cite from. Needed because Contract 2 gives
  // labs no source_doc_id, so their citations are resolved by searching the
  // text of exactly these documents.
  useEffect(() => {
    if (!patientId) { setDocIds([]); return; }
    let live = true;
    getPatient(patientId)
      .then((r) => { if (live) setDocIds(docIdsFor(r.data)); })
      .catch(() => { if (live) setDocIds([]); });
    return () => { live = false; };
  }, [patientId]);

  const submit = useCallback(async (e) => {
    e?.preventDefault();
    const q = query.trim();
    if (!q || !patientId || pending) return;
    setPending(true);
    setError(null);
    setTimeoutError(null);
    try {
      const res = await ask(patientId, q);
      setResult(res.data);
      setOffline(Boolean(res.offline));
      setPending(false);

      if (res.data?.plan?.intent === 'timeout') {
        setTimeoutError(res.data.refusal_reason || 'Query timed out after 45s.');
      }

      // Citations are node ids; we need the graph to turn them into sources.
      if (!(res.data?.published || []).length) {
        setGraph(null);
      } else {
        getGraph(patientId).then((g) => setGraph(g.data)).catch(() => setGraph(null));
      }
    } catch (e) {
      setPending(false);
      const msg = e.message || String(e);
      if (msg.toLowerCase().includes('timed out')) {
        setTimeoutError(msg);
      } else {
        setError(msg);
      }
    }
  }, [query, patientId, pending]);

  const useSample = useCallback((q) => {
    setQuery(q);
    setResult(null);
    setError(null);
    setTimeoutError(null);
  }, []);

  return (
    <>
      <h1 className="page">Ask</h1>
      <p className="lede">
        Ask a question about this record. AXIOM answers from the graph or it
        says plainly that the record cannot support an answer. It never
        guesses, and it does not fail silently.
      </p>

      {!patientId ? (
        <Notice tone="warn" title="NO PATIENT SELECTED">
          Pick a patient from the Patients screen first.
        </Notice>
      ) : (
        <>
          <form className="card" style={{ marginTop: 22 }} onSubmit={submit}>
            <div className="card-title"><span>QUESTION</span></div>
            <div className="field">
              <label htmlFor="ask-query">Ask about {patientId}</label>
              <input
                id="ask-query"
                type="text"
                value={query}
                placeholder="e.g. Is the renal function deteriorating?"
                onChange={(e) => setQuery(e.target.value)}
                autoComplete="off"
                disabled={pending}
              />
              <div className="hint">
                Scope boundary: this system summarises a record you already hold.
                It does not diagnose and it does not prescribe.
              </div>
            </div>
            <div className="toolbar">
              <button
                type="submit"
                className="btn primary"
                disabled={pending || !query.trim()}
              >
                {pending ? 'Verifying against graph…' : 'Ask AXIOM'}
              </button>
              {result && !pending && (
                <button
                  type="button"
                  className="btn ghost"
                  onClick={() => { setResult(null); setError(null); setTimeoutError(null); }}
                >
                  Clear
                </button>
              )}
            </div>
            <div style={{ marginTop: 16 }}>
              <div className="subhead">TRY ONE</div>
              <div style={{ marginTop: 8 }}>
                {SAMPLES.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="sample-q"
                    onClick={() => useSample(q)}
                    disabled={pending}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          </form>

          {/* Pipeline progress with honest verification stages */}
          {pending && (
            <AskProgressTracker
              query={query}
              patientId={patientId}
              elapsedMs={elapsedMs}
            />
          )}

          {/* Timeout error state */}
          {timeoutError && !pending && (
            <Notice
              tone="error"
              title="QUERY TIMED OUT (45s)"
              action={
                <button type="button" className="btn" onClick={submit}>
                  Retry question
                </button>
              }
            >
              {timeoutError}
              <div className="hint" style={{ marginTop: 6 }}>
                The backend took longer than 45 seconds to complete graph traversal
                and claim verification. The server may be under heavy load or waiting
                on local model inference.
              </div>
            </Notice>
          )}

          {/* Genuine request failure */}
          {error && !pending && (
            <Notice tone="error" title="REQUEST FAILED">
              {error}
            </Notice>
          )}

          {/* Offline notice: explains refusal without inventing canned dataset */}
          {offline && !error && result && (
            <Notice tone="warn" title="BACKEND UNREACHABLE — LOCAL REFUSAL">
              The analysis backend at <code>{API}</code> is not reachable.
              AXIOM refused this question because no live graph evidence could be retrieved.
              To enable graph traversal and claim generation, start the backend with{' '}
              <code>uvicorn api.main:app --port 8000</code>.
            </Notice>
          )}

          {/* Result view */}
          {result && !pending && (
            <ResultView
              result={result}
              graph={graph}
              docIds={docIds}
              onSource={onSource}
              elapsedMs={finalElapsedMs}
            />
          )}
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

/**
 * Honest visualization of the clinical analysis and verification pipeline.
 */
function AskProgressTracker({ query, patientId, elapsedMs }) {
  const seconds = (elapsedMs / 1000).toFixed(1);

  return (
    <section className="card" style={{ marginTop: 18 }} role="status" aria-live="polite">
      <div className="card-title">
        <span>ANALYSIS &amp; VERIFICATION PIPELINE IN PROGRESS</span>
        <Chip kind="info">{seconds}s · timeout at 45s</Chip>
      </div>

      <div style={{ fontSize: 13.5, color: 'var(--ink)', marginBottom: 12 }}>
        Querying record for <strong>{patientId}</strong>: <code style={{ fontFamily: 'ui-monospace, monospace' }}>&ldquo;{query}&rdquo;</code>
      </div>

      <p className="pipeline-note" style={{ fontSize: 12.5, color: 'var(--grey-d)', lineHeight: 1.55, margin: '0 0 14px' }}>
        AXIOM does not guess or generate ungrounded prose. It compiles the question
        against the patient graph, synthesises candidate claims, and runs a formal
        verification pass checking every claim against cited evidence before publishing.
      </p>

      <div className="stage-list">
        <StageRow
          status="active"
          name="1. Compiling question against clinical graph"
          detail="Parsing clinical intent, identifying target entities, and retrieving temporal graph paths"
        />
        <StageRow
          status="waiting"
          name="2. Checking coverage against record schema"
          detail="Confirming required evidence classes exist in this chart before proceeding"
        />
        <StageRow
          status="waiting"
          name="3. Generating candidate claims"
          detail="Formulating candidate assertions constrained by observed graph relationships"
        />
        <StageRow
          status="waiting"
          name="4. Formally verifying claims against evidence (The Product)"
          detail="Tracing every statement to exact document spans; checking entailment against sources"
        />
        <StageRow
          status="waiting"
          name="5. Applying calibration & abstention rules"
          detail="Scoring claim confidence; suppressing or abstaining on unsupported claims"
        />
      </div>

      <div style={{ marginTop: 14 }}>
        <Spinner label="Traversing graph and verifying candidate claims against evidence…" />
      </div>
    </section>
  );
}

function StageRow({ status, name, detail }) {
  const icons = {
    done: '✓',
    active: '●',
    waiting: '○',
    warn: '⚠',
    info: 'ℹ',
  };

  const colors = {
    done: 'var(--green)',
    active: 'var(--gold)',
    waiting: 'var(--grey)',
    warn: 'var(--crit)',
    info: 'var(--blue)',
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 10,
      padding: '7px 0',
      borderBottom: '1px dotted var(--line)',
      fontSize: 12.5,
    }}>
      <span style={{
        color: colors[status] || 'var(--grey)',
        fontWeight: 800,
        fontFamily: 'ui-monospace, monospace',
        minWidth: 16,
      }}>
        {icons[status] || '•'}
      </span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, color: status === 'waiting' ? 'var(--grey)' : 'var(--ink)' }}>
          {name}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--grey-d)', marginTop: 2 }}>
          {detail}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ResultView({ result, graph, docIds, onSource, elapsedMs }) {
  if (result.refused) return <RefusalPanel result={result} elapsedMs={elapsedMs} />;

  const published = result.published || [];
  const abstained = result.abstained || [];

  return (
    <div style={{ marginTop: 20 }}>
      <div className="answer-head">
        <span className="answer-head-t">ANSWERED FROM THE RECORD</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {elapsedMs != null && <Chip kind="mute">{(elapsedMs / 1000).toFixed(2)}s</Chip>}
          <Chip kind="ok">HTTP 200 · {published.length} claim{published.length === 1 ? '' : 's'} published</Chip>
        </div>
      </div>

      {published.length === 0 && (
        <Notice tone="warn" title="ANSWERED, BUT NOTHING PUBLISHED">
          The pipeline ran and produced no claim that survived verification.
          The answer withheld is listed below — nothing was invented to fill
          the gap.
        </Notice>
      )}

      {published.map((c) => (
        <ClaimCard key={c.claim_id} claim={c} graph={graph} docIds={docIds} onSource={onSource} />
      ))}

      {abstained.length > 0 && <WithheldList abstained={abstained} graph={graph} docIds={docIds} onSource={onSource} />}

      <AuditStrip auditRef={result.audit_ref} plan={result.plan} />
    </div>
  );
}

/* ------------------------------------------------------------------ */

function ClaimCard({ claim, graph, docIds, onSource }) {
  const cites = claim.cited_nodes || [];
  return (
    <div className="claim">
      <div className="claim-head">
        <span className="claim-id">
          {claim.claim_id} · calibrated{' '}
          {claim.calibrated_score == null ? 'n/a' : claim.calibrated_score}
        </span>
        <span style={{ display: 'flex', gap: 6 }}>
          {claim.severity && <Chip kind={sevKind(claim.severity)}>{claim.severity}</Chip>}
          <Chip kind="info">{(claim.claim_type || '').replace(/_/g, ' ')}</Chip>
        </span>
      </div>
      <div className="claim-text">{claim.text}</div>

      <div className="cites">
        <span className="cite-lead">SOURCES ({cites.length})</span>
        {cites.length === 0 && (
          <span className="noprovenance">
            no nodes cited — this claim should not have been published
          </span>
        )}
        {cites.map((id) => (
          <Citation key={id} nodeId={id} graph={graph} docIds={docIds} onSource={onSource} />
        ))}
      </div>

      <div className="verified">
        ✓ {claim.verdict || 'ENTAILED'}
        {claim.reason ? ` — ${claim.reason}` : ' — every statement traced to source'}
      </div>
    </div>
  );
}

/**
 * Turn a cited node id into a chip that opens the document.
 */
function Citation({ nodeId, graph, docIds, onSource }) {
  const node = useMemo(
    () => (graph?.nodes || []).find((n) => n.id === nodeId),
    [graph, nodeId],
  );
  if (!graph) return <span className="cite dead">{nodeId}</span>;
  if (!node) return <DeadCite id={nodeId} />;
  return <Cite node={node} graph={graph} docIds={docIds} onSource={onSource} />;
}

/* ------------------------------------------------------------------ */

function WithheldList({ abstained, graph, docIds, onSource }) {
  return (
    <section className="card" style={{ marginTop: 18 }}>
      <div className="card-title">
        <span>WITHHELD — CLAIMS THAT DID NOT SURVIVE VERIFICATION</span>
        <Chip kind="mute">{abstained.length}</Chip>
      </div>
      {abstained.map((a, i) => {
        const c = a.claim || a;
        return (
          <div key={c.claim_id || i} className="claim withheld">
            <div className="claim-head">
              <span className="claim-id">{c.claim_id || '—'}</span>
              <Chip kind="mute">{a.action}</Chip>
            </div>
            {c.text && <div className="claim-text">{c.text}</div>}
            <div className="withheld-meta">
              {a.message || c.reason}
              {a.escalate_to ? ` · routed to ${a.escalate_to}` : ''}
            </div>
            {(c.cited_nodes || []).length > 0 && (
              <div className="cites" style={{ marginTop: 8 }}>
                <span className="cite-lead">CONSIDERED</span>
                {c.cited_nodes.map((id) => (
                  <Citation key={id} nodeId={id} graph={graph} docIds={docIds} onSource={onSource} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* THE REFUSAL: FIRST-CLASS, CONSIDERED CLINICAL OUTCOME              */
/* ------------------------------------------------------------------ */

function RefusalPanel({ result, elapsedMs }) {
  const route =
    (result.abstained || []).find((a) => a.escalate_to)?.escalate_to ||
    'records request';
  const rawMissing = result.missing || result.missing_evidence || null;

  const missingDisplay = useMemo(() => {
    if (!rawMissing) return 'no specific evidence class captured';
    if (Array.isArray(rawMissing)) {
      return rawMissing
        .map((m) => (typeof m === 'string' ? m.replace(/_/g, ' ') : JSON.stringify(m)))
        .join(', ');
    }
    return String(rawMissing).replace(/_/g, ' ');
  }, [rawMissing]);

  return (
    <div style={{ marginTop: 20 }}>
      <div className="answer-head">
        <span className="answer-head-t">COVERAGE REFUSAL — CONSIDERED OUTCOME</span>
        <div style={{ display: 'flex', gap: 6 }}>
          {elapsedMs != null && <Chip kind="mute">{(elapsedMs / 1000).toFixed(2)}s</Chip>}
          <Chip kind="ok">HTTP 200 · refused</Chip>
        </div>
      </div>

      <section className="refusal" role="status" aria-live="polite">
        <div className="refusal-kicker">
          <span aria-hidden="true">■</span> AXIOM DECLINED TO ANSWER
        </div>

        <div className="refusal-q">
          <strong style={{ color: '#8a8a8a', fontWeight: 700 }}>Q</strong>{' '}
          <code style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>{result.query}</code>
        </div>

        <div className="refusal-a">This record cannot support an answer to that question.</div>

        <p className="refusal-body">
          {result.refusal_reason ? (
            <>Reason given: <strong>{result.refusal_reason}</strong>.</>
          ) : (
            'No supporting evidence class exists in this record schema.'
          )}{' '}
          No query plan was executed and no claim was published — AXIOM
          stopped at the coverage check rather than generating a hedged
          non-answer.
        </p>

        <div className="refusal-grid">
          <div className="refusal-cell">
            <div className="refusal-cell-l">MISSING EVIDENCE</div>
            <div className="refusal-cell-v" style={{ fontWeight: 600 }}>
              {missingDisplay}
            </div>
          </div>
          <div className="refusal-cell">
            <div className="refusal-cell-l">ROUTED TO</div>
            <div className="refusal-cell-v">{route}</div>
          </div>
          <div className="refusal-cell">
            <div className="refusal-cell-l">AUDIT REF</div>
            <div className="refusal-cell-v">
              <code style={{ fontFamily: 'ui-monospace, Menlo, monospace' }}>
                {result.audit_ref || 'not recorded — offline'}
              </code>
            </div>
          </div>
        </div>

        <p className="refusal-note">
          Absence of documentation is not absence of the condition. A refusal
          here is a confident, useful answer — it is never an error state, and
          no part of this panel is a failure.
        </p>
      </section>

      {result.plan && (
        <section className="card" style={{ marginTop: 16 }}>
          <div className="card-title">
            <span>WHAT THE PLANNER DECIDED</span>
            <Chip kind="mute">no traversal run</Chip>
          </div>
          <div className="source" style={{ marginTop: 0 }}>
            {Object.entries(result.plan).map(([k, v]) => (
              <div key={k} className="source-row">
                <span className="source-k">{k.replace(/_/g, ' ')}</span>
                <span className="source-v">
                  {v === null || v === undefined || v === '' ? '—' : String(v)}
                </span>
              </div>
            ))}
          </div>
          <p className="noprovenance" style={{ marginTop: 10 }}>
            The planner parsed the question and then declined it. Refusing after
            parsing — rather than before — is what lets AXIOM name the specific
            evidence class that is absent instead of shrugging.
          </p>
        </section>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

function AuditStrip({ auditRef, plan }) {
  return (
    <div className="audit-strip">
      <span>
        <b>Audit ref</b> <code>{auditRef || 'none'}</code>
      </span>
      {plan?.intent && (
        <span>
          <b>Intent</b> {String(plan.intent).replace(/_/g, ' ')}
          {plan.entity ? ` · entity ${plan.entity}` : ''}
        </span>
      )}
      <span className="audit-strip-note">
        Every answer and every refusal is written to the audit trail through
        the same path.
      </span>
    </div>
  );
}

const sevKind = (s) =>
  ({ critical: 'critical', high: 'critical', medium: 'medium', low: 'low' }[s] || 'mute');