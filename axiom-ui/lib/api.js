/**
 * The entire HTTP surface (Contract 5) lives behind this one module.
 *
 * Two rules this file exists to enforce:
 *
 * 1. **A refusal is never an exception.** `/api/ask` answers 200 for every
 *    question that names an existing patient, including every refusal. The
 *    only things that throw here are transport failures and genuine 4xx
 *    (unknown patient, malformed upload). Conflating "I won't answer" with
 *    "your request was wrong" would defeat the product.
 *
 * 2. **Fallback data is always labelled.** When the backend is down we serve
 *    inline fixtures so the demo does not show a blank screen — and every
 *    response comes back tagged `offline: true` so the UI can say so out loud
 *    rather than passing off canned data as live.
 */

import {
  PATIENTS, PATIENT_DETAIL, buildGraph, DOCS,
  ASK_REFUSED,
} from './fixtures';

/**
 * Base URL shown in the chrome and used for direct calls.
 *
 * Requests are issued against same-origin `/api/...` by default, which Next
 * rewrites to this upstream (see next.config.js). That keeps the browser out
 * of the CORS conversation entirely. Set NEXT_PUBLIC_API_DIRECT=1 to call this
 * URL directly instead.
 */
export const API = process.env.NEXT_PUBLIC_API || 'http://localhost:8000';

const DIRECT = process.env.NEXT_PUBLIC_API_DIRECT === '1';
const base = () => (DIRECT ? API : '');

export const HEALTH = { ok: true, llm: 'none' };

/** Error carrying enough context for the UI to say something useful. */
export class ApiError extends Error {
  constructor(message, { status = 0, kind = 'transport', body = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind; // 'transport' | 'http' | 'parse' | 'unsupported'
    this.body = body;
  }

  /** True when we never reached the backend at all. */
  get isOffline() {
    return this.kind === 'transport';
  }
}

const TIMEOUT_MS = 8000;

async function raw(path, init = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(`${base()}${path}`, { ...init, signal: ctrl.signal });
    const text = await res.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    return { ok: res.ok, status: res.status, body };
  } finally {
    clearTimeout(timer);
  }
}

const offlineMessage = (path) =>
  new ApiError(
    `AXIOM backend is not reachable at ${API} (${path}). Start it with ` +
    `"uvicorn api.main:app --port 8000".`,
    { kind: 'transport' },
  );

/**
 * Try the network, fall back to fixtures. Never throws for the read paths —
 * a 4xx from the backend (e.g. unknown patient) throws, because that is a
 * real answer the clinician needs to see, not a missing backend.
 */
async function withFallback(path, init, fallback) {
  let res;
  try {
    res = await raw(path, init);
  } catch (e) {
    return {
      data: fallback(),
      offline: true,
      offlineReason: String(e.message || e),
    };
  }
  if (!res.ok) {
    // A 5xx on a same-origin request usually means the proxy could not reach
    // the backend, not that our request was wrong. Treat it as transport so
    // the UI says "backend down" rather than inventing an application error.
    if (res.status >= 500) {
      return {
        data: fallback(),
        offline: true,
        offlineReason: `backend responded ${res.status} (treated as unreachable)`,
      };
    }
    const detail =
      (res.body && (res.body.detail || res.body.message)) || `HTTP ${res.status}`;
    throw new ApiError(
      typeof detail === 'string' ? detail : JSON.stringify(detail),
      { status: res.status, kind: 'http', body: res.body },
    );
  }
  if (res.body === null || res.body === undefined) {
    return {
      data: fallback(),
      offline: true,
      offlineReason: 'empty response body',
    };
  }
  return { data: res.body, offline: false };
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export async function getHealth() {
  try {
    const { ok, body } = await raw('/api/health');
    if (ok && body) return { data: body, offline: false };
  } catch { /* fall through — a demo with one process down is expected */ }
  return { data: HEALTH, offline: true };
}

/* ------------------------------------------------------------------ */
/* Patients                                                            */
/* ------------------------------------------------------------------ */

export async function listPatients() {
  return withFallback(
    '/api/patients',
    { cache: 'no-store' },
    () => PATIENTS,
  );
}

export async function getPatient(id) {
  return withFallback(
    `/api/patients/${encodeURIComponent(id)}`,
    { cache: 'no-store' },
    () => {
      const p = PATIENT_DETAIL[id];
      if (!p) throw new ApiError(`unknown patient ${id}`, { status: 404, kind: 'http' });
      return p;
    },
  );
}

export async function getGraph(id) {
  return withFallback(
    `/api/patients/${encodeURIComponent(id)}/graph`,
    { cache: 'no-store' },
    () => {
      const p = PATIENT_DETAIL[id];
      if (!p) throw new ApiError(`unknown patient ${id}`, { status: 404, kind: 'http' });
      return buildGraph(p);
    },
  );
}

/* ------------------------------------------------------------------ */
/* Upload                                                              */
/* ------------------------------------------------------------------ */

export async function uploadDocument(file, patientId) {
  const fd = new FormData();
  fd.append('file', file, file.name);
  if (patientId) fd.append('patient_id', patientId);

  let res;
  try {
    res = await raw('/api/upload', { method: 'POST', body: fd });
  } catch (e) {
    // Upload has no honest fallback: pretending a document was parsed when it
    // was not would be a fabricated provenance record, which is the one thing
    // this app must never do.
    throw offlineMessage('/api/upload');
  }
  if (!res.ok) {
    if (res.status >= 500) throw offlineMessage('/api/upload');
    const detail =
      (res.body && (res.body.detail || res.body.message)) || `HTTP ${res.status}`;
    throw new ApiError(
      typeof detail === 'string' ? detail : JSON.stringify(detail),
      { status: res.status, kind: 'http', body: res.body },
    );
  }
  return { data: res.body, offline: false };
}

/* ------------------------------------------------------------------ */
/* Ask — the refusal is a success payload, not an error                */
/* ------------------------------------------------------------------ */

export async function ask(patientId, query) {
  const payload = JSON.stringify({ patient_id: patientId, query });

  let res;
  try {
    res = await raw('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
    });
  } catch {
    return { ...refusalFallback(patientId, query), offline: true,
             offlineReason: 'backend unreachable — showing the refusal this record would produce' };
  }
  if (!res.ok) {
    // Same rule as withFallback: behind the Next proxy a dead backend surfaces
    // as a 5xx rather than a transport failure. Without this branch a backend
    // outage rendered as a red REQUEST FAILED box — telling the clinician
    // AXIOM crashed, when the truth is that it had no evidence to work with
    // and declined for exactly that reason.
    if (res.status >= 500) {
      return {
        ...refusalFallback(patientId, query),
        offline: true,
        offlineReason: `backend responded ${res.status} (treated as unreachable)`,
      };
    }
    const detail =
      (res.body && (res.body.detail || res.body.message)) || `HTTP ${res.status}`;
    throw new ApiError(
      typeof detail === 'string' ? detail : JSON.stringify(detail),
      { status: res.status, kind: 'http', body: res.body },
    );
  }
  return { data: res.body, offline: false };
}

/**
 * The offline refusal is deliberately a REFUSAL, not an answer. If the backend
 * is down we do not have evidence for anything, so the honest payload is the
 * one the pipeline would emit for an unanswerable question.
 */
function refusalFallback(patientId, query) {
  return {
    data: {
      ...ASK_REFUSED,
      patient_id: patientId,
      query,
      refusal_reason:
        'the analysis service is unreachable, so no evidence could be retrieved; ' +
        ASK_REFUSED.refusal_reason,
      audit_ref: null,
      degraded: true,
    },
    offline: true,
  };
}

/* ------------------------------------------------------------------ */
/* Source pages                                                        */
/* ------------------------------------------------------------------ */

export async function getPage(docId, pageNo) {
  return withFallback(
    `/api/documents/${encodeURIComponent(docId)}/page/${pageNo}`,
    { cache: 'no-store' },
    () => {
      const doc = DOCS[docId];
      if (!doc) throw new ApiError(`unknown document ${docId}`, { status: 404, kind: 'http' });
      const text = doc.pages[pageNo];
      if (text === undefined) {
        throw new ApiError(`document ${docId} has no page ${pageNo}`, { status: 404, kind: 'http' });
      }
      return {
        doc_id: docId, page: pageNo, text, kind: doc.kind,
        char_start: 0, char_end: text.length, ocr_used: false, fact_spans: [],
      };
    },
  );
}

/* ------------------------------------------------------------------ */
/* Audit                                                               */
/* ------------------------------------------------------------------ */

export async function listAudit(patientId) {
  const qs = patientId ? `?patient_id=${encodeURIComponent(patientId)}&limit=25` : '?limit=25';
  const { ok, body } = await raw(`/api/audit${qs}`, { cache: 'no-store' }).catch(() => ({
    ok: false, body: null,
  }));
  return { data: ok && Array.isArray(body) ? body : [], offline: !ok };
}

