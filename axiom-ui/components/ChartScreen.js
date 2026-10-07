'use client';

import { useCallback, useMemo, useState } from 'react';
import { API, getGraph, getPatient } from '../lib/api';
import { useResource } from '../lib/useApi';
import { computeTrends, docIdsFor, locateTerm, nodeLabel, sourceOf } from '../lib/derive';
import Cite from './Cite';
import Timeline from './Timeline';
import TrendChart from './TrendChart';
import { Chip, Notice, OfflineNotice, Spinner } from './Chrome';

const TYPE_ORDER = [
  'Diagnosis', 'LabResult', 'MedicationOrder', 'Allergy',
  'ImagingStudy', 'Note', 'VitalSeries', 'Encounter',
];

/**
 * Scene 02 — the chart. `GET /api/patients/{id}` and `/graph`.
 *
 * Every card here is a claim about the patient and every card carries its
 * provenance. A card whose node has no `source_doc_id` says so in words
 * instead of rendering a dead link — and when the term can be located in a
 * document this record does reference, we find the real offsets and open them.
 */
export default function ChartScreen({ patientId, onAsk, onSource }) {
  const patient = useResource(
    () => (patientId ? getPatient(patientId) : Promise.resolve(null)),
    [patientId], { skip: !patientId },
  );
  const graph = useResource(
    () => (patientId ? getGraph(patientId) : Promise.resolve(null)),
    [patientId], { skip: !patientId },
  );

  if (!patientId) {
    return (
      <>
        <h1 className="page">Chart</h1>
        <Notice tone="warn" title="NO PATIENT SELECTED">
          Pick a patient from the Patients screen first.
        </Notice>
      </>
    );
  }

  return (
    <>
      <h1 className="page">Chart</h1>
      <p className="lede">
        The record reconstructed into typed, time-stamped nodes. Every card is a
        statement about this patient, and every one of them opens its source.
      </p>

      {(patient.offline || graph.offline) && (
        <OfflineNotice api={API} onRetry={() => { patient.reload(); graph.reload(); }}
          reason={patient.reason || graph.reason} />
      )}

      {patient.loading && <Spinner label={`Loading ${patientId}…`} />}

      {patient.error && (
        <Notice tone="error" title="COULD NOT LOAD THE PATIENT">
          {patient.error}
          <div style={{ marginTop: 8 }}>
            <button type="button" className="btn" onClick={patient.reload}>Retry</button>
          </div>
        </Notice>
      )}

      {patient.data && (
        <PatientHeader
          patient={patient.data}
          stats={graph.data?.stats}
          onAsk={onAsk}
          loadingGraph={graph.loading}
        />
      )}

      {graph.error && (
        <Notice tone="error" title="GRAPH UNAVAILABLE">
          {graph.error}
        </Notice>
      )}

      {graph.data && (
        <div className="cols">
          <div>
            <EvidenceCards
              graph={graph.data}
              patient={patient.data}
              onSource={onSource}
            />
            <TrendPanel graph={graph.data} docIds={docIdsFor(patient.data)} onSource={onSource} />
          </div>
          <div>
            <GraphPanel graph={graph.data} />
          </div>
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ */

function PatientHeader({ patient, stats, onAsk, loadingGraph }) {
  const encs = (patient.encounters || []).length;
  return (
    <section className="card" style={{ marginTop: 22 }}>
      <div className="pt-header">
        <div>
          <div className="pt-name">{patient.name || patient.id}</div>
          <div className="pt-dem">
            DOB {patient.dob || '—'} · MRN {patient.mrn || '—'}
          </div>
          <div className="pt-dem" style={{ marginTop: 2, color: 'var(--green)' }}>
            synthetic record — no real patient data
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 12 }}>
          <div className="stat-row">
            <div className="stat">
              <div className="stat-n">{stats ? stats.nodes : '—'}</div>
              <div className="stat-l">graph nodes</div>
            </div>
            <div className="stat">
              <div className="stat-n">{stats ? stats.edges : '—'}</div>
              <div className="stat-l">typed edges</div>
            </div>
            <div className="stat">
              <div className="stat-n">{encs}</div>
              <div className="stat-l">encounters</div>
            </div>
          </div>
          <button type="button" className="btn primary" onClick={onAsk}>
            Ask about this patient →
          </button>
        </div>
      </div>
      {loadingGraph && <Spinner label="Building clinical graph…" />}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function EvidenceCards({ graph, patient, onSource }) {
  const [filter, setFilter] = useState('all');
  const [resolving, setResolving] = useState(null);
  const [unresolved, setUnresolved] = useState({});

  const docs = useMemo(() => docIdsFor(patient), [patient]);

  const grouped = useMemo(() => {
    const byType = {};
    (graph.nodes || []).forEach((n) => {
      (byType[n.type] = byType[n.type] || []).push(n);
    });
    Object.values(byType).forEach((list) => {
      list.sort((a, b) => (String(a.time) < String(b.time) ? -1 : 1));
    });
    return byType;
  }, [graph]);

  const types = useMemo(() => {
    const present = Object.keys(grouped);
    return ['all', ...TYPE_ORDER.filter((t) => present.includes(t)), ...present.filter((t) => !TYPE_ORDER.includes(t))];
  }, [grouped]);

  /**
   * Open a node's source. If the node carries no doc_id we search the text
   * layer of the documents this record does reference, and we say plainly when
   * the term cannot be found — an unresolved citation is a bug to surface, not
   * a gap to paper over.
   */
  const open = useCallback(async (node) => {
    const direct = sourceOf(node);
    if (direct) {
      onSource({
        docId: direct.docId, page: direct.page,
        charStart: direct.charStart, charEnd: direct.charEnd,
        label: nodeLabel(node), nodeId: node.id, raw: node,
      });
      return;
    }
    setResolving(node.id);
    setUnresolved((u) => ({ ...u, [node.id]: undefined }));
    const found = await locateTerm(docs, nodeLabel(node).split(' ')[0] || node.display || node.name);
    setResolving(null);
    if (found) {
      onSource({
        docId: found.docId, page: found.page,
        charStart: found.charStart, charEnd: found.charEnd,
        label: nodeLabel(node), nodeId: node.id, raw: node,
      });
    } else {
      setUnresolved((u) => ({ ...u, [node.id]: 'not found in any referenced document' }));
    }
  }, [docs, onSource]);

  const shown = types.filter((t) => t !== 'all');
  const total = (graph.nodes || []).length;

  return (
    <section className="card">
      <div className="card-title">
        <span>EVIDENCE CARDS</span>
        <Chip kind="info">{total} nodes</Chip>
      </div>

      <div className="type-filter" role="tablist" aria-label="Filter nodes by type">
        {types.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={filter === t}
            className={`filterbtn ${filter === t ? 'active' : ''}`}
            onClick={() => setFilter(t)}
          >
            {t === 'all' ? `All ${total}` : `${t} ${(grouped[t] || []).length}`}
          </button>
        ))}
      </div>

      {(filter === 'all' ? shown : [filter]).map((t) => (
        <div key={t} style={{ marginTop: 16 }}>
          <div className="subhead">{t.replace(/([A-Z])/g, ' $1').toUpperCase()}</div>
          {(grouped[t] || []).map((node) => {
            const direct = sourceOf(node);
            const busy = resolving === node.id;
            const note = unresolved[node.id];
            return (
              <div key={node.id} className="evcard">
                <div className="evcard-main">
                  <div className="evcard-label">{nodeLabel(node)}</div>
                  <div className="evcard-meta">
                    <span>{node.id}</span>
                    <span>·</span>
                    <span>{String(node.time || '').slice(0, 10) || 'no timestamp'}</span>
                    {node.abnormal === true && <Chip kind="critical">abnormal</Chip>}
                    {node.negated && <Chip kind="info">negated</Chip>}
                    {node.active === false && <Chip kind="mute">discontinued</Chip>}
                  </div>
                </div>
                <div className="evcard-cite">
                  {note ? (
                    <span className="noprovenance">{note}</span>
                  ) : direct ? (
                    <span className="cite-loc">
                      {direct.docId} p{direct.page}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    className="cite"
                    onClick={() => open(node)}
                    disabled={busy}
                    title="Open the source document for this node"
                  >
                    {busy ? 'locating…' : 'source'}
                  </button>
                </div>
              </div>
            );
          })}
          {(grouped[t] || []).length === 0 && (
            <p className="noprovenance">No {t} nodes in this record.</p>
          )}
        </div>
      ))}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function TrendPanel({ graph, docIds, onSource }) {
  const trends = useMemo(() => computeTrends(graph), [graph]);

  if (!trends.length) {
    return (
      <section className="card">
        <div className="card-title"><span>LAB TRENDS</span></div>
        <p className="noprovenance">
          No analyte in this record has two or more results. A single draw is a
          value, not a trajectory — plotting one point would imply a trend the
          data does not support.
        </p>
      </section>
    );
  }

  return (
    <>
      {trends.map((t) => (
        <section className="card" key={t.loinc}>
          <div className="card-title">
            <span>{t.display.toUpperCase()} TRAJECTORY</span>
            <span style={{ color: 'var(--grey)' }}>
              {t.summary.change_pct > 0 ? '+' : ''}{t.summary.change_pct}% change
            </span>
          </div>
          <TrendChart trend={t} />
          <div className="trend-facts">
            <span>
              first <b>{t.series[0].v}</b> {t.unit} on {t.series[0].t}
            </span>
            <span>
              latest <b>{t.series[t.series.length - 1].v}</b> {t.unit} on{' '}
              {t.series[t.series.length - 1].t}
            </span>
            <span>
              reference {t.ref_low ?? '—'}–{t.ref_high ?? '—'} {t.unit}
            </span>
            <Chip kind={t.summary.deteriorated ? 'critical' : 'ok'}>
              {t.summary.deteriorated ? 'deteriorating' : 'stable or improving'}
            </Chip>
          </div>
          <div className="cites" style={{ marginTop: 10 }}>
            <span className="cite-lead">SOURCE POINTS</span>
            {t.node_ids.map((id) => {
              const node = graph.nodes.find((n) => n.id === id);
              if (!node) return <span key={id} className="cite dead">{id} ✕</span>;
              return (
                <Cite
                  key={id}
                  node={node}
                  graph={graph}
                  docIds={docIds}
                  onSource={onSource}
                  label={String(node.time || '').slice(0, 10)}
                />
              );
            })}
          </div>
          <p className="trend-note">
            Plotted from typed graph nodes, not retrieved as text. The series is
            a join on LOINC across encounters — the layer a chunk-retrieval
            system cannot express.
          </p>
        </section>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ */

function GraphPanel({ graph }) {
  const s = graph.stats || { nodes: 0, edges: 0, by_type: {} };
  const edgeTypes = s.edge_types || {};
  return (
    <section className="card">
      <div className="card-title"><span>CLINICAL GRAPH</span></div>
      <div className="stat-row" style={{ marginBottom: 14, justifyContent: 'flex-start' }}>
        <div className="stat" style={{ textAlign: 'left' }}>
          <div className="stat-n">{s.nodes}</div><div className="stat-l">nodes</div>
        </div>
        <div className="stat" style={{ textAlign: 'left' }}>
          <div className="stat-n">{s.edges}</div><div className="stat-l">edges</div>
        </div>
      </div>

      <div style={{ fontSize: 11.5, color: 'var(--grey)' }}>
        {Object.entries(s.by_type || {}).map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
            <span>{k.replace(/([A-Z])/g, ' $1')}</span>
            <span style={{ fontFamily: 'monospace' }}>{v}</span>
          </div>
        ))}
      </div>

      {Object.keys(edgeTypes).length > 0 && (
        <>
          <div className="subhead" style={{ marginTop: 16 }}>TYPED EDGES</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(edgeTypes).map(([k, v]) => (
              <Chip key={k} kind="mute">{k.replace(/_/g, ' ')} {v}</Chip>
            ))}
          </div>
        </>
      )}

      {graph.nodes?.length > 0 && <Timeline graph={graph} />}
    </section>
  );
}