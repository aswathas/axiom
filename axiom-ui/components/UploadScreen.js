'use client';

import { useCallback, useRef, useState } from 'react';
import { API, listPatients, uploadDocument } from '../lib/api';
import { useMutation, useResource } from '../lib/useApi';
import { Chip, Notice, OfflineNotice, Spinner } from './Chrome';

const ACCEPT = '.pdf,.txt,.md,.text';
const KIND_LABEL = {
  lab_report: 'lab report',
  discharge_summary: 'discharge summary',
  med_list: 'medication printout',
  unknown: 'unrecognised',
};

/**
 * Scene 04 — `POST /api/upload`.
 *
 * The point of this screen is not "it accepts a file". It is that the answer
 * comes back with provenance attached: detected layout, every extracted fact,
 * and the page and character range each one was read from. A fact you cannot
 * click back to a span is a fact nobody should act on, so every row here opens
 * its own source.
 *
 * Upload has no offline fallback on purpose (see lib/api.js): fabricating a
 * parse result for a document that was never parsed would be inventing
 * provenance, which is the one thing this app must never do.
 */
export default function UploadScreen({ onSource }) {
  const [dragging, setDragging] = useState(false);
  const [patientId, setPatientId] = useState('');
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);
  const mutation = useMutation();

  const patients = useResource(() => listPatients(), []);

  const submit = useCallback(async (file) => {
    if (!file) return;
    setResult(null);
    const res = await mutation.run(() => uploadDocument(file, patientId || undefined));
    if (res) setResult(res.data);
  }, [mutation, patientId]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) submit(file);
  }, [submit]);

  return (
    <>
      <h1 className="page">Ingest</h1>
      <p className="lede">
        Drop a document. The parser detects the layout, extracts typed facts,
        and records the page and character range each one came from.
      </p>

      <div className="cols">
        <div>
          <section className="card">
            <div className="card-title">
              <span>UPLOAD</span>
              <span style={{ color: 'var(--grey)' }}>multipart/form-data</span>
            </div>

            <button
              type="button"
              className={`drop ${dragging ? 'over' : ''}`}
              onClick={() => inputRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              aria-describedby="upload-help"
            >
              <div className="drop-t">Drop a file here, or click to choose</div>
              <div className="drop-s" id="upload-help">
                PDF or plain text · up to 25 MB
                <br />
                Layouts detected: {Object.keys(KIND_LABEL).slice(0, 3).map((k) => KIND_LABEL[k]).join(' · ')}
              </div>
            </button>

            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              onChange={(e) => submit(e.target.files?.[0])}
              style={{ position: 'absolute', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }}
              aria-label="Choose a document to upload"
            />

            <div className="field">
              <label htmlFor="upload-patient">Attach to patient (optional)</label>
              <select
                id="upload-patient"
                value={patientId}
                onChange={(e) => setPatientId(e.target.value)}
              >
                <option value="">— unattributed —</option>
                {(patients.data || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.mrn}
                  </option>
                ))}
              </select>
              <div className="hint">
                Unattributed uploads are still parsed and fully browsable — they
                just do not join a patient graph.
              </div>
            </div>

            {mutation.pending && <Spinner label="Uploading and parsing…" />}

            {mutation.error && (
              <Notice tone="error" title="UPLOAD REJECTED">
                {mutation.error}
                <div className="hint" style={{ marginTop: 6 }}>
                  AXIOM needs a text layer it can cite. Scanned images and
                  office formats are refused rather than guessed at, because a
                  character offset pointing into invented text is worse than no
                  offset at all.
                </div>
              </Notice>
            )}

            {patients.offline && (
              <div style={{ marginTop: 14 }}>
                <OfflineNotice api={API} onRetry={patients.reload} />
              </div>
            )}
          </section>

          {result && <UploadResult result={result} onSource={onSource} />}
        </div>

        <div>
          <section className="card">
            <div className="card-title"><span>WHAT HAPPENS ON INGEST</span></div>
            <ol className="limit-ol">
              <li>
                Bytes become a per-page text layer. No OCR, no office converter
                — a span has to point at characters that genuinely exist.
              </li>
              <li>
                Layout is detected (lab table, discharge narrative, medication
                printout) and the matching parser runs.
              </li>
              <li>
                Facts are typed against the Fact schema: kind, value, unit,
                LOINC where known, reference range, and whether it is abnormal.
              </li>
              <li>
                Every fact keeps its document id, page, and character offsets.
                The browser never recomputes those — they arrive from the
                parser.
              </li>
            </ol>
            <p className="noprovenance" style={{ marginTop: 14 }}>
              Contract 5 returns facts and page metadata but not the extracted
              text itself, so the highlighted span is fetched from the document
              endpoint when you click a row.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */

function UploadResult({ result, onSource }) {
  const facts = result.facts || [];
  const pages = result.pages || [];
  const byKind = facts.reduce((acc, f) => {
    acc[f.kind] = (acc[f.kind] || 0) + 1;
    return acc;
  }, {});

  return (
    <section className="card">
      <div className="card-title">
        <span>PARSED</span>
        <Chip kind="ok">{facts.length} facts</Chip>
      </div>

      <div className="kv-grid">
        <div><span className="kv-k">document</span><span className="kv-v">{result.doc_id}</span></div>
        <div>
          <span className="kv-k">detected layout</span>
          <span className="kv-v">
            <Chip kind="info">{KIND_LABEL[result.kind] || result.kind || 'unrecognised'}</Chip>
          </span>
        </div>
        <div><span className="kv-k">file</span><span className="kv-v">{result.filename || '—'}</span></div>
        <div><span className="kv-k">pages</span><span className="kv-v">{pages.length || '—'}</span></div>
        <div><span className="kv-k">sha256</span><span className="kv-v mono-small">{String(result.sha256 || '').slice(0, 16)}…</span></div>
        <div>
          <span className="kv-k">by kind</span>
          <span className="kv-v">
            {Object.entries(byKind).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'}
          </span>
        </div>
      </div>

      {pages.length > 0 && (
        <p className="noprovenance" style={{ marginTop: 10 }}>
          {pages.map((p) => `page ${p.page_no}: ${p.chars} chars`).join(' · ')}
        </p>
      )}

      <div className="subhead" style={{ marginTop: 18 }}>EXTRACTED FACTS</div>

      {facts.length === 0 && (
        <Notice tone="warn" title="NO FACTS EXTRACTED">
          The document parsed without error but produced no facts. That is a
          truthful result for an unrecognised layout — the file is stored and
          still browsable, but nothing has been asserted about this patient.
        </Notice>
      )}

      <div className="fact-table">
        {facts.map((f, i) => {
          const hasSpan = Number(f.source_char_end) > Number(f.source_char_start);
          return (
            <div key={`${f.name}-${i}`} className="fact-row">
              <div>
                <div className="fact-name">{f.name}</div>
                <div style={{ marginTop: 4, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                  <Chip kind="mute">{f.kind}</Chip>
                  {f.extractor && <Chip kind="mute">{f.extractor}</Chip>}
                  {f.abnormal && <Chip kind="critical">abnormal</Chip>}
                  {f.negated && <Chip kind="info">negated</Chip>}
                </div>
              </div>
              <div className="fact-val">
                {f.value ?? '—'}
                {f.unit ? ` ${f.unit}` : ''}
                {f.timestamp ? <span style={{ color: 'var(--grey)' }}> · {String(f.timestamp).slice(0, 10)}</span> : null}
                {f.loinc ? <span style={{ color: 'var(--grey)' }}> · LOINC {f.loinc}</span> : null}
                {f.ref_low != null ? (
                  <span style={{ color: 'var(--grey)' }}>
                    {' '}· ref {f.ref_low}–{f.ref_high}
                  </span>
                ) : null}
              </div>
              <div className="fact-src">
                <div style={{ fontSize: 10.5, color: 'var(--grey)', marginBottom: 4 }}>
                  p{f.source_page}
                  {hasSpan ? ` · chars ${f.source_char_start}–${f.source_char_end}` : ' · no span'}
                </div>
                {hasSpan ? (
                  <button
                    type="button"
                    className="cite"
                    onClick={() => onSource({
                      docId: f.source_doc_id || result.doc_id,
                      page: f.source_page,
                      charStart: f.source_char_start,
                      charEnd: f.source_char_end,
                      label: `${f.name} — ${result.filename || f.source_doc_id}`,
                      nodeId: f.source_doc_id,
                    })}
                  >
                    view source
                  </button>
                ) : (
                  <span className="noprovenance">not resolvable</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}