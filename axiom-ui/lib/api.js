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
 * 2. **Transport failures are loud; no fake data is ever served.** When the
 *    backend is unreachable, AXIOM never falls back to canned fixture data.
 *    Serving invented patients under the guise of an offline demo would be
 *    the exact failure of accountability this product exists to prevent.
 *    Unreachable endpoints fail loudly with an unmissable error directing
 *    the clinician to start the backend with `uvicorn api.main:app --port 8000`.
 *    The single exception is the ask path: an offline backend produces an
 *    honest coverage refusal ("no evidence could be retrieved because the
 *    analysis service is unreachable"), matching the product's own refusal
 *    contract rather than crashing or inventing claims.
 */

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

// Default client timeout for standard metadata requests.
const DEFAULT_TIMEOUT_MS = 15000;

// Ask requests involve graph compilation, LLM-backed claim generation, and
// formal claim verification against patient evidence. On local models or
// slower hardware, this pipeline routinely requires 15–30s. The former 8000ms
// timeout caused premature client-side aborts during legitimate verification
// passes; 45s gives ample headroom for multi-pass reasoning and verification.
const ASK_TIMEOUT_MS = 45000;

// Upload involves PDF parsing, layout classification, and fact extraction.
const UPLOAD_TIMEOUT_MS = 30000;

async function raw(path, init = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
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
  } catch (err) {
    if (ctrl.signal.aborted) {
      throw new ApiError(
        `Request to ${API}${path} timed out after ${timeoutMs / 1000}s. The backend may be busy running verification or waiting on model inference.`,
        { kind: 'transport', status: 408 },
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export const offlineMessage = (path) =>
  new ApiError(
    `AXIOM backend is not reachable at ${API} (${path}). Start it with ` +
    `"uvicorn api.main:app --port 8000".`,
    { kind: 'transport' },
  );

/**
 * Perform a network request without fallback. Unreachable backends and 5xx
 * responses throw transport errors loudly instead of returning canned data.
 */
async function request(path, init = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  let res;
  try {
    res = await raw(path, init, timeoutMs);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw offlineMessage(path);
  }
  if (!res.ok) {
    // A 5xx on a same-origin request usually means the proxy could not reach
    // the backend. Treat it as transport so the UI says "backend down" with the
    // exact startup command rather than inventing an application error.
    if (res.status >= 500) {
      throw offlineMessage(path);
    }
    const detail =
      (res.body && (res.body.detail || res.body.message)) || `HTTP ${res.status}`;
    throw new ApiError(
      typeof detail === 'string' ? detail : JSON.stringify(detail),
      { status: res.status, kind: 'http', body: res.body },
    );
  }
  if (res.body === null || res.body === undefined) {
    throw new ApiError('empty response body', { status: res.status, kind: 'parse' });
  }
  return { data: res.body, offline: false };
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export async function getHealth() {
  try {
    const { ok, body } = await raw('/api/health', { cache: 'no-store' }, 5000);
    if (ok && body) return { data: body, offline: false };
  } catch {
    // Health probe failed — backend is offline
  }
  return { data: null, offline: true };
}

/* ------------------------------------------------------------------ */
/* Patients                                                            */
/* ------------------------------------------------------------------ */

export async function listPatients() {
  return request('/api/patients', { cache: 'no-store' });
}

export async function getPatient(id) {
  return request(`/api/patients/${encodeURIComponent(id)}`, { cache: 'no-store' });
}

export async function getGraph(id) {
  return request(`/api/patients/${encodeURIComponent(id)}/graph`, { cache: 'no-store' });
}

export async function createPatient({ mrn, name, dob, ...rest } = {}) {
  const res = await request('/api/patients', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mrn, name, dob, ...rest }),
  });
  const data = res.data;
  if (data && typeof data === 'object') {
    Object.defineProperty(data, 'data', { value: data, enumerable: false, writable: true });
    Object.defineProperty(data, 'offline', { value: false, enumerable: false, writable: true });
  }
  return data;
}

export async function updatePatient(id, patch) {
  const res = await request(`/api/patients/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch || {}),
  });
  if (res.data && typeof res.data === 'object' && !Array.isArray(res.data)) {
    for (const key of Object.keys(res.data)) {
      if (!(key in res)) {
        Object.defineProperty(res, key, {
          get: () => res.data[key],
          enumerable: false,
          configurable: true,
        });
      }
    }
  }
  return res;
}

export async function listPatientDocuments(id) {
  return request(`/api/patients/${encodeURIComponent(id)}/documents`, { cache: 'no-store' });
}

export async function attachDocumentToPatient(patientId, docId) {
  const res = await request(
    `/api/patients/${encodeURIComponent(patientId)}/documents/${encodeURIComponent(docId)}`,
    { method: 'POST' },
  );
  if (res.data && typeof res.data === 'object' && !Array.isArray(res.data)) {
    for (const key of Object.keys(res.data)) {
      if (!(key in res)) {
        Object.defineProperty(res, key, {
          get: () => res.data[key],
          enumerable: false,
          configurable: true,
        });
      }
    }
  }
  return res;
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
    res = await raw('/api/upload', { method: 'POST', body: fd }, UPLOAD_TIMEOUT_MS);
  } catch (e) {
    if (e instanceof ApiError) throw e;
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
/* Ask — refusal is a success payload, not an error                    */
/* ------------------------------------------------------------------ */

export async function ask(patientId, query) {
  const payload = JSON.stringify({ patient_id: patientId, query });

  let res;
  try {
    res = await raw(
      '/api/ask',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
      },
      ASK_TIMEOUT_MS,
    );
  } catch (e) {
    const isTimeout = e instanceof ApiError && e.status === 408;
    return {
      ...refusalFallback(
        patientId,
        query,
        isTimeout
          ? `query timed out after ${ASK_TIMEOUT_MS / 1000}s — backend did not answer`
          : `AXIOM backend is not reachable at ${API}. Start it with "uvicorn api.main:app --port 8000".`,
        isTimeout ? 'timeout' : 'unreachable',
      ),
      offline: true,
      offlineReason: isTimeout
        ? `Request timed out after ${ASK_TIMEOUT_MS / 1000}s`
        : `Backend unreachable at ${API}`,
    };
  }
  if (!res.ok) {
    if (res.status >= 500) {
      return {
        ...refusalFallback(
          patientId,
          query,
          `backend responded ${res.status} (treated as unreachable)`,
          'server_error',
        ),
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
 * An offline or timed-out query produces an honest REFUSAL, never invented claims.
 * Refusing when no backend is available communicates the truth: no evidence
 * could be retrieved from the clinical graph, so no claim is asserted.
 */
function refusalFallback(patientId, query, reasonDetail, kind = 'unreachable') {
  const isTimeout = kind === 'timeout';
  const reason = isTimeout
    ? `the query timed out after ${ASK_TIMEOUT_MS / 1000}s without a completed verification pass from the analysis service`
    : `the analysis service is unreachable at ${API} (start it with "uvicorn api.main:app --port 8000"); no evidence could be retrieved from the record graph`;

  const missing = isTimeout
    ? ['timely verification response from analysis service']
    : ['live backend service (uvicorn api.main:app --port 8000)'];

  const escalation = isTimeout
    ? 'retry with simpler query or check backend service performance'
    : 'service operator — start backend with "uvicorn api.main:app --port 8000"';

  return {
    data: {
      patient_id: patientId,
      query,
      plan: { intent: isTimeout ? 'timeout' : 'offline', entity: null, window_months: null },
      refused: true,
      status: 'refused',
      refusal_reason: reason,
      missing,
      missing_evidence: missing[0],
      published: [],
      abstained: [
        {
          claim_id: '__refusal__',
          action: 'REFUSED',
          message: `This record cannot support an answer to that question: ${reason}.`,
          escalate_to: escalation,
        },
      ],
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
  return request(
    `/api/documents/${encodeURIComponent(docId)}/page/${pageNo}`,
    { cache: 'no-store' },
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
