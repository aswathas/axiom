'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getPage } from '../lib/api';
import { Spinner, Notice } from './Chrome';

/**
 * The source viewer: "resolves to source in two clicks".
 *
 * Given a doc_id / page / character range, it fetches the page text from
 * `/api/documents/{doc_id}/page/{n}` and highlights exactly that span. Every
 * other fact the backend attributes to the same page is highlighted too, so a
 * reviewer can see not just the cited line but its neighbours — which is how
 * you catch a citation that is technically in the document and pointed at the
 * wrong sentence.
 *
 * If the range cannot be resolved we say so. We never highlight the whole
 * page, because a fake highlight is worse than an honest gap.
 */
export default function SourceDrawer({ target, onClose }) {
  const [page, setPage] = useState(target.page || 1);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const closeRef = useRef(null);
  const panelRef = useRef(null);
  const textRef = useRef(null);

  /**
   * Modal focus behaviour.
   *
   * Two things a plain conditional render gets wrong, both of which strand a
   * keyboard or screen-reader user:
   *   1. focus is never returned to the citation that opened the drawer, so
   *      after closing, Tab resumes from the top of the document;
   *   2. Tab walks straight out of the dialog and into the page behind it,
   *      which is still visible and still focusable.
   * So: remember the trigger, cycle Tab within the panel, and put focus back.
   *
   * The trigger is captured and Close is focused in ONE effect on purpose.
   * Split across two, the ordering means the second effect reads
   * document.activeElement *after* the first has already moved focus into the
   * drawer, so it remembers the Close button — which is destroyed on unmount,
   * and focus lands on <body> instead of where the user left off.
   */
  const returnTo = useRef(null);

  useEffect(() => {
    returnTo.current = document.activeElement;
    closeRef.current?.focus();
    return () => {
      const el = returnTo.current;
      if (el && typeof el.focus === 'function' && document.contains(el)) el.focus();
    };
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), '
        + 'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    let live = true;
    setState({ loading: true, data: null, error: null });
    getPage(target.docId, page)
      .then((res) => {
        if (!live) return;
        if (!res.data) setState({ loading: false, data: null, error: 'no page text returned' });
        else setState({ loading: false, data: res.data, error: null, offline: res.offline });
      })
      .catch((e) => {
        if (live) setState({ loading: false, data: null, error: e.message });
      });
    return () => { live = false; };
  }, [target.docId, page]);

  const segments = useMemo(() => {
    if (!state.data || !state.data.text) return null;
    return segmentText(state.data, page, target);
  }, [state.data, page, target]);

  // Scroll the cited span into view once the page renders.
  useEffect(() => {
    if (!segments || !textRef.current) return;
    const el = textRef.current.querySelector('.hl-active');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
  }, [segments]);

  const goto = useCallback((n) => setPage(Math.max(1, n)), []);

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <div
        ref={panelRef}
        className="drawer drawer-wide"
        role="dialog"
        aria-modal="true"
        aria-label={`Source document ${target.docId} page ${page}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-head">
          <div>
            <div className="drawer-kicker">SOURCE DOCUMENT</div>
            <div className="drawer-title">{target.label || target.docId}</div>
            <div className="drawer-sub">
              {target.docId} · page {page}
              {state.data?.kind ? ` · ${String(state.data.kind).replace(/_/g, ' ')}` : ''}
              {state.data?.ocr_used ? ' · OCR' : ''}
            </div>
          </div>
          <button ref={closeRef} type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </div>

        <p className="drawer-blurb">
          This is the record behind the citation — the exact characters the
          engine pointed at. Nothing on a claim screen exists without a span
          like this one.
        </p>

        {target.raw && Object.keys(target.raw).length > 0 && (
          <div className="source">
            <div className="source-id">{target.nodeId} · typed node</div>
            {Object.entries(target.raw).map(([k, v]) => (
              <div key={k} className="source-row">
                <span className="source-k">{prettyKey(k)}</span>
                <span className="source-v">
                  {v === null || v === undefined ? '—' : String(v)}
                </span>
              </div>
            ))}
          </div>
        )}

        {state.loading && <Spinner label={`Loading page ${page}…`} />}

        {state.error && (
          <Notice tone="error" title="PAGE TEXT UNAVAILABLE">
            {state.error}
          </Notice>
        )}

        {segments && (
          <>
            <div className="page-legend">
              <span><span className="swatch cited" /> cited span</span>
              <span><span className="swatch other" /> other facts on this page</span>
              <span className="page-legend-off">
                {state.offline ? 'fallback text' : 'live API text'}
              </span>
            </div>
            <div className="page-view" ref={textRef} tabIndex={0}>
              {segments.map((s, i) =>
                s.active ? (
                  <mark key={i} className="hl hl-active" id="cited-span">{s.text}</mark>
                ) : s.alt ? (
                  <mark key={i} className="hl" title={s.title}>{s.text}</mark>
                ) : (
                  <span key={i}>{s.text}</span>
                ),
              )}
            </div>
            {/* Contract 5 gives no page-count endpoint, so page navigation is by
                explicit number rather than a "next" button that would have to
                guess when to disable. */}
            <div className="page-nav">
              <button
                type="button" className="btn ghost" onClick={() => goto(page - 1)}
                disabled={page <= 1}
              >
                ← Previous
              </button>
              <label htmlFor="page-no" className="page-nav-label">Page</label>
              <input
                id="page-no" className="page-nav-input" type="number" min={1}
                value={page}
                onChange={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isFinite(n) && n >= 1) setPage(Math.floor(n));
                }}
              />
              <button type="button" className="btn ghost" onClick={() => goto(page + 1)}>
                Next →
              </button>
            </div>
          </>
        )}

        {!segments && !state.loading && !state.error && (
          <p className="noprovenance">
            No page text was returned for this span, so nothing can be
            highlighted. The citation itself is still shown above.
          </p>
        )}

        <div className="drawer-foot">
          <strong>Claim → node → document → characters.</strong> Refusals are
          logged through the same chain. Data posture: 100% synthetic, no real
          PHI anywhere in this system.
        </div>
      </div>
    </div>
  );
}

/**
 * Slice the page text into plain / alternate-fact / cited spans.
 *
 * Ranges come from `fact_spans` on the API response (each carries its own
 * char_start/char_end) plus the requested citation range. Overlaps are
 * resolved by priority so the cited span always wins.
 */
function segmentText(data, page, target) {
  const text = data.text || '';
  const ranges = [];
  (data.fact_spans || []).forEach((s) => {
    const start = Number(s.char_start ?? 0);
    const end = Number(s.char_end ?? 0);
    if (end > start) {
      ranges.push({
        start, end, priority: 1,
        title: `${s.fact?.name || 'fact'}${s.fact?.value != null ? ` = ${s.fact.value}` : ''}`,
      });
    }
  });

  const cited = onPage(target, page)
    ? { start: Number(target.charStart) || 0, end: Number(target.charEnd) || 0 }
    : null;
  if (cited && cited.end > cited.start) ranges.push({ ...cited, priority: 2 });
  if (data.page === page && data.char_start != null && data.char_end != null
      && data.char_end - data.char_start < text.length) {
    // The API's own full-span hint is useful only when it is NOT the whole page.
    ranges.push({ start: Number(data.char_start), end: Number(data.char_end), priority: 1 });
  }

  if (!ranges.length) return [{ text, alt: false, active: false }];

  const clipped = ranges
    .map((r) => ({
      ...r,
      start: Math.max(0, Math.min(r.start, text.length)),
      end: Math.max(0, Math.min(r.end, text.length)),
    }))
    .filter((r) => r.end > r.start)
    .sort((a, b) => a.start - b.start || b.priority - a.priority);

  // Drop ranges fully contained in an earlier, higher-priority range.
  const kept = [];
  for (const r of clipped) {
    const covered = kept.find((k) => r.start >= k.start && r.end <= k.end);
    if (!covered) kept.push(r);
  }

  const out = [];
  let cursor = 0;
  for (const r of kept.sort((a, b) => a.start - b.start)) {
    if (r.start > cursor) out.push({ text: text.slice(cursor, r.start), alt: false, active: false });
    out.push({
      text: text.slice(r.start, r.end),
      alt: r.priority === 1,
      active: r.priority === 2,
      title: r.title,
    });
    cursor = r.end;
  }
  if (cursor < text.length) out.push({ text: text.slice(cursor), alt: false, active: false });
  return out;
}

/** True when the citation's recorded page is the page being displayed. */
function onPage(target, page) {
  return Number(target.page || 1) === Number(page);
}

const KEYS = {
  id: 'node id', type: 'type', time: 'time', code: 'code', display: 'display',
  value: 'value', unit: 'unit', ref_low: 'ref low', ref_high: 'ref high',
  drug: 'drug', dose: 'dose', substance: 'substance', reaction: 'reaction',
  severity: 'severity', observed_at: 'observed at', facility: 'facility',
  loinc: 'loinc', modality: 'modality', body_site: 'body site',
  name: 'name', start: 'start', end: 'end', active: 'active',
  frequency: 'frequency', rxnorm: 'rxnorm', category: 'category', onset: 'onset',
};

const prettyKey = (k) => KEYS[k] || k.replace(/_/g, ' ');