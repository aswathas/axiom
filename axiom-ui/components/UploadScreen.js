'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { API, listPatients, uploadDocument } from '../lib/api';
import { useMutation, useResource } from '../lib/useApi';
import { Chip, Notice, Spinner } from './Chrome';

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
 * Ingestion pipeline with visible stages, real elapsed time, honest attribution,
 * and provenance down to character offsets.
 */
export default function UploadScreen({ onSource }) {
  const [dragging, setDragging] = useState(false);
  const [patientId, setPatientId] = useState('');
  const [result, setResult] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [finalElapsedMs, setFinalElapsedMs] = useState(null);
  const inputRef = useRef(null);
  const startTimeRef = useRef(null);
  const mutation = useMutation();

  const patients = useResource(() => listPatients(), []);

  // Timer for tracking real elapsed time during upload & parse
  useEffect(() => {
    let timer = null;
    if (mutation.pending) {
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
  }, [mutation.pending]);

  const submit = useCallback(async (file) => {
    if (!file) return;
    setSelectedFile({ name: file.name, size: file.size });
    setResult(null);
    const res = await mutation.run(() => uploadDocument(file, patientId || undefined));
    if (res && res.data) {
      setResult(res.data);
    }
  }, [mutation, patientId]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) submit(file);
  }, [submit]);

  const targetPatient = useMemo(() => {
    if (!result?.patient_id) return null;
    return (patients.data || []).find((p) => p.id === result.patient_id) || null;
  }, [patients.data, result?.patient_id]);

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
              disabled={mutation.pending}
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
                disabled={mutation.pending}
              >
                <option value="">— unattributed —</option>
                {(patients.data || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.mrn} ({p.id})
                  </option>
                ))}
              </select>
              <div className="hint">
                Unattributed uploads are parsed and stored with provenance spans — they
                just do not join a patient graph.
              </div>
            </div>

            {/* In-flight extraction stages */}
            {mutation.pending && (
              <ExtractionPipelineTracker
                pending={true}
                file={selectedFile}
                patientId={patientId}
                elapsedMs={elapsedMs}
              />
            )}

            {/* Upload failed */}
            {mutation.error && (
              <div style={{ marginTop: 16 }}>
                <Notice tone="error" title="UPLOAD FAILED">
                  {mutation.error}
                  <div className="hint" style={{ marginTop: 6 }}>
                    AXIOM needs a text layer it can cite. Scanned images without text
                    and office formats are refused rather than guessed at, because a
                    character offset pointing into invented text is worse than no
                    offset at all.
                  </div>
                </Notice>
                {finalElapsedMs != null && (
                  <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--grey)' }}>
                    Failed after {(finalElapsedMs / 1000).toFixed(2)}s.
                  </div>
                )}
              </div>
            )}

            {/* Patients list unavailable */}
            {patients.error && (
              <div style={{ marginTop: 14 }}>
                <Notice tone="warn" title="PATIENT LIST UNAVAILABLE">
                  {patients.error}
                  <div style={{ marginTop: 6 }}>
                    You can still ingest documents as unattributed, but to attach them to
                    existing patients, start the backend with <code>uvicorn api.main:app --port 8000</code>.
                  </div>
                </Notice>
              </div>
            )}
          </section>

          {/* Succeeded upload result with completed stages breakdown */}
          {result && (
            <>
              <ExtractionPipelineTracker
                pending={false}
                result={result}
                file={selectedFile}
                patientId={patientId}
                targetPatient={targetPatient}
                elapsedMs={finalElapsedMs ?? elapsedMs}
              />
              <UploadResult
                result={result}
                targetPatient={targetPatient}
                elapsedMs={finalElapsedMs ?? elapsedMs}
                onSource={onSource}
              />
            </>
          )}
        </div>

        <div>
          <section className="card">
            <div className="card-title"><span>WHAT HAPPENS ON INGEST</span></div>
            <ol className="limit-ol">
              <li>
                <strong>Reading the text layer:</strong> Raw bytes become a per-page text layer.
                No OCR hallucination or office converter — character spans must point at
                real bytes.
              </li>
              <li>
                <strong>Detecting document layout:</strong> Document structure is classified
                (lab table, discharge narrative, medication printout) to select the appropriate parser.
              </li>
              <li>
                <strong>Extracting typed facts:</strong> Facts are mapped against the clinical
                Fact schema: analyte/drug, value, unit, LOINC, reference range, and abnormal flag.
              </li>
              <li>
                <strong>Patient attribution:</strong> Documents are either matched to a patient
                MRN or stored as unlinked records with full citation support.
              </li>
              <li>
                <strong>Updating clinical graph:</strong> If attributed, newly extracted facts
                join existing encounters, labs, and diagnoses to rebuild the patient graph.
              </li>
            </ol>
            <p className="noprovenance" style={{ marginTop: 14 }}>
              Contract 5 returns typed facts and page metadata. When you click a fact row,
              the document viewer fetches the verified characters directly from the source page.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ */

/**
 * Honest, observable pipeline tracker.
 *
 * Shows real named stages. During in-flight, it states plainly that the server
 * executes the pipeline atomically and updates in real-time. On completion,
 * it derives each stage's honest status and outcome from the server payload.
 */
function ExtractionPipelineTracker({ pending, result, file, patientId, targetPatient, elapsedMs }) {
  const seconds = (elapsedMs / 1000).toFixed(1);

  if (pending) {
    return (
      <div className="pipeline-card" style={{ marginTop: 16 }}>
        <div className="pipeline-head">
          <span className="pipeline-title">EXTRACTION PIPELINE IN PROGRESS</span>
          <Chip kind="info">{seconds}s elapsed</Chip>
        </div>

        <p className="pipeline-note">
          Processing <strong>{file?.name || 'document'}</strong> ({file ? `${(file.size / 1024).toFixed(1)} KB` : 'calculating size'}).
          The backend runs text parsing, layout classification, fact extraction, and graph rebuilding in an atomic transaction:
        </p>

        <div className="stage-list">
          <StageRow
            status="active"
            name="1. Reading text layer"
            detail="Extracting character stream and page boundaries from document bytes"
          />
          <StageRow
            status="waiting"
            name="2. Detecting document layout"
            detail="Classifying format (lab report, discharge summary, medication list)"
          />
          <StageRow
            status="waiting"
            name="3. Extracting typed facts & spans"
            detail="Identifying clinical entities, LOINC codes, values, and character offsets"
          />
          <StageRow
            status="waiting"
            name="4. Patient attribution"
            detail={patientId ? `Targeting patient ${patientId}` : 'Staging as unattributed upload'}
          />
          <StageRow
            status="waiting"
            name="5. Updating clinical graph"
            detail={patientId ? 'Rebuilding patient graph upon extraction' : 'Skipped (unattributed upload)'}
          />
        </div>
        <div style={{ marginTop: 12 }}>
          <Spinner label="Executing extraction pipeline on backend…" />
        </div>
      </div>
    );
  }

  if (!result) return null;

  const factsCount = (result.facts || []).length;
  const pagesCount = (result.pages || []).length;
  const totalChars = (result.pages || []).reduce((acc, p) => acc + (p.chars || 0), 0);
  const isAttributed = Boolean(result.patient_id);
  const layout = KIND_LABEL[result.kind] || result.kind || 'unrecognised';
  const hasZeroFacts = factsCount === 0;

  return (
    <section className="card" style={{ marginTop: 18 }}>
      <div className="card-title">
        <span>EXTRACTION PIPELINE OUTCOME</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <Chip kind="mute">{(elapsedMs / 1000).toFixed(2)}s real time</Chip>
          {hasZeroFacts ? (
            <Chip kind="medium">0 facts extracted</Chip>
          ) : isAttributed ? (
            <Chip kind="ok">attributed · {result.patient_id}</Chip>
          ) : (
            <Chip kind="info">unattributed</Chip>
          )}
        </div>
      </div>

      <div className="stage-list">
        <StageRow
          status="done"
          name="1. Reading text layer"
          detail={`Extracted text layer across ${pagesCount} page(s) (${totalChars.toLocaleString()} characters total)`}
        />
        <StageRow
          status={result.kind === 'unknown' ? 'warn' : 'done'}
          name="2. Detecting document layout"
          detail={result.kind === 'unknown' ? 'Layout unrecognised (generic text)' : `Detected layout: ${layout}`}
        />
        <StageRow
          status={hasZeroFacts ? 'warn' : 'done'}
          name="3. Extracting typed facts & spans"
          detail={
            hasZeroFacts
              ? 'No typed facts matched document schema (unrecognised or non-clinical layout)'
              : `Extracted ${factsCount} typed facts with exact page & character spans`
          }
        />
        <StageRow
          status={isAttributed ? 'done' : 'info'}
          name="4. Patient attribution"
          detail={
            isAttributed
              ? `Matched to patient ${result.patient_id}${targetPatient?.name ? ` (${targetPatient.name})` : ''}`
              : 'Unattributed document — not linked to any patient record'
          }
        />
        <StageRow
          status={isAttributed ? 'done' : 'mute'}
          name="5. Updating clinical graph"
          detail={
            isAttributed
              ? `Facts merged into patient graph for ${result.patient_id}; graph rebuilt`
              : 'Skipped graph rebuild — unattributed uploads do not join a patient graph'
          }
        />
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
    mute: '—',
  };

  const colors = {
    done: 'var(--green)',
    active: 'var(--gold)',
    waiting: 'var(--grey)',
    warn: 'var(--crit)',
    info: 'var(--blue)',
    mute: 'var(--grey)',
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

function UploadResult({ result, targetPatient, elapsedMs, onSource }) {
  const facts = result.facts || [];
  const pages = result.pages || [];
  const byKind = facts.reduce((acc, f) => {
    acc[f.kind] = (acc[f.kind] || 0) + 1;
    return acc;
  }, {});

  const isAttributed = Boolean(result.patient_id);

  return (
    <section className="card" style={{ marginTop: 18 }}>
      <div className="card-title">
        <span>DOCUMENT PROVENANCE & FACTS</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <Chip kind={facts.length === 0 ? 'mute' : 'ok'}>{facts.length} facts</Chip>
          <Chip kind="mute">{(elapsedMs / 1000).toFixed(2)}s</Chip>
        </div>
      </div>

      {/* Patient Attribution Announcement */}
      {isAttributed ? (
        <div style={{
          background: 'var(--blue-lt)',
          border: '1px solid #cfdcee',
          borderLeft: '4px solid var(--blue)',
          borderRadius: 5,
          padding: '12px 14px',
          marginBottom: 16,
        }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--blue)', letterSpacing: 0.5 }}>
            PATIENT ATTRIBUTION: {result.patient_id}
            {targetPatient?.name ? ` · ${targetPatient.name}` : ''}
            {targetPatient?.mrn ? ` (MRN ${targetPatient.mrn})` : ''}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--ink)', marginTop: 4, lineHeight: 1.5 }}>
            This document and its {facts.length} extracted facts are now integrated into{' '}
            <strong>{result.patient_id}</strong>&apos;s clinical chart. The clinical graph has been
            rebuilt with these findings.
          </div>
        </div>
      ) : (
        <div style={{
          background: 'var(--gold-lt)',
          border: '1px solid var(--line)',
          borderLeft: '4px solid var(--gold)',
          borderRadius: 5,
          padding: '12px 14px',
          marginBottom: 16,
        }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--gold-dim)', letterSpacing: 0.5 }}>
            UNATTRIBUTED DOCUMENT — NOT ATTACHED TO ANY PATIENT
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--grey-d)', marginTop: 4, lineHeight: 1.5 }}>
            This document was ingested without an attached patient ID. The {pages.length} pages
            and {facts.length} facts are stored in the document repository with full character-level
            provenance, but <strong>do not appear in any patient chart or graph</strong>.
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--grey-d)', marginTop: 6 }}>
            <strong>What to do next:</strong> To include these findings in a patient record, select a patient
            from the &quot;Attach to patient&quot; dropdown above and re-upload the file, or use the records API
            to assign document <code>{result.doc_id}</code> to an MRN.
          </div>
        </div>
      )}

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