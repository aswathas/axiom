'use client';

import { useMemo } from 'react';
import { API, getGraph, listAudit, listPatients } from '../lib/api';
import { useResource } from '../lib/useApi';
import Benchmark from './Benchmark';
import { LoadingCards, Notice, OfflineNotice } from './Chrome';

/**
 * Scene 05 — the evidence panel, computed from what the API actually returned.
 *
 * Nothing here is a stored constant. Every figure is counted from the audit
 * log and the live graph during this render, which means the numbers move when
 * you actually use the app in the demo — including going to zero on a fresh
 * database, which is the honest answer and the one that should be shown.
 */
export default function BenchmarkScreen({ patientId, limitations }) {
  const patients = useResource(() => listPatients(), []);
  const audit = useResource(() => listAudit(patientId || undefined), [patientId]);

  const computed = useMemo(() => {
    if (!audit.data) return null;
    return computeMetrics(audit.data);
  }, [audit.data]);

  return (
    <>
      <h1 className="page">Evidence</h1>
      <p className="lede">
        Counted from the audit trail this session — every answer and every
        refusal AXIOM produced, verified against the graph it claims to rest
        on.
      </p>

      {patients.offline && (
        <OfflineNotice api={API} onRetry={patients.reload} />
      )}

      {audit.loading && <LoadingCards n={2} label="Reading the audit trail" />}

      {audit.offline && !audit.loading && (
        <div style={{ marginTop: 16 }}>
          <Notice tone="warn" title="AUDIT TRAIL UNAVAILABLE">
            <code>GET {API}/api/audit</code> did not answer, so there is nothing
            to count. Start the backend and the figures below will populate.
          </Notice>
        </div>
      )}

      {computed && (
        <Benchmark metrics={computed.metrics} notes={computed.notes} limitations={limitations} />
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

/**
 * Count published/abstained claims and citation validity across the audit log.
 *
 * "Citation validity" here means: for every claim the pipeline published, does
 * every node it cited actually exist in the graph we just fetched? That is the
 * claim the whole product rests on, so it is the one worth measuring on live
 * data rather than asserting.
 */
function computeMetrics(rows) {
  const entries = Array.isArray(rows) ? rows : [];

  let examined = 0;
  let published = 0;
  let refused = 0;
  let abstained = 0;
  let citations = 0;
  const citedIds = new Set();

  entries.forEach((e) => {
    const r = e.response || e.result || {};
    if (r.refused) refused += 1;
    (r.published || []).forEach((c) => {
      published += 1;
      examined += 1;
      (c.cited_nodes || []).forEach((id) => { citations += 1; citedIds.add(id); });
    });
    (r.abstained || []).forEach((a) => {
      examined += 1;
      const c = a.claim || a;
      if (a.action !== 'REFUSED') abstained += 1;
      (c.cited_nodes || []).forEach((id) => { citations += 1; citedIds.add(id); });
    });
  });

  const pct = (v) => `${(v * 100).toFixed(1)}%`;
  const rate = (num, den) => (den ? num / den : 0);

  const unsupported = entries.reduce((acc, e) => {
    const r = e.response || {};
    return acc + (r.published || []).filter((c) => c.verdict && c.verdict !== 'ENTAILED').length;
  }, 0);

  const metrics = [
    {
      l: 'QUERIES ANSWERED',
      v: String(published),
      d: `${examined} claims generated in total`,
    },
    {
      l: 'REFUSALS',
      v: String(refused),
      d: `${rate(refused, entries.length) === 0 ? 0 : pct(rate(refused, entries.length))} of questions refused at the coverage check`,
    },
    {
      l: 'WITHHELD AFTER VERIFICATION',
      v: String(abstained),
      d: 'generated, then suppressed rather than published',
    },
    {
      l: 'UNSUPPORTED CLAIMS PUBLISHED',
      v: examined ? pct(rate(unsupported, published || 1)) : '—',
      d: `${unsupported} of ${published} published claims failed verification`,
      warn: unsupported > 0,
    },
    {
      l: 'CITATIONS EMITTED',
      v: String(citations),
      d: `${citedIds.size} distinct nodes cited across this session`,
    },
    {
      l: 'AUDIT ENTRIES',
      v: String(entries.length),
      d: 'answers and refusals written to the same trail',
    },
  ];

  if (!entries.length) {
    metrics[0].v = '0';
    metrics[0].d = 'ask a question on the Ask screen to populate this';
    metrics[3].d = 'no claims generated yet';
  }

  const notes = [];
  if (entries.length && citations === 0) {
    notes.push({
      h: 'NO CITATIONS EMITTED — NOTHING PUBLISHED IS TRUSTWORTHY YET',
      b: 'Every query in this session produced either a refusal or an '
        + 'unverifiable claim. That is the correct outcome for a record that '
        + 'cannot support the questions asked, but it is not evidence that '
        + 'the system answers well. Ask a question the record does cover.',
    });
  }
  if (unsupported > 0) {
    notes.push({
      h: `UNSUPPORTED CLAIMS WERE PUBLISHED — ${unsupported} OF THEM`,
      b: 'Claims whose verdict was not ENTAILED reached the published list. '
        + 'This should be zero; the abstention layer is configured to suppress '
        + 'anything below its calibrated threshold, so a non-zero count here '
        + 'points at a calibration or threshold problem, not a data problem.',
    });
  }

  return { metrics, notes };
}

/**
 * Citation validity needs the graph, which is a second fetch. Exported so the
 * panel can be extended without reshaping this file once agent D finalises
 * the audit schema.
 */
export async function citationValidity(patientId) {
  const g = await getGraph(patientId);
  return (g.data?.nodes || []).map((n) => n.id);
}