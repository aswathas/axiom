/**
 * Pure derivations over API payloads. No fetching, no React — so the same
 * functions back the chart screen, the upload screen and the offline path.
 *
 * The two things that live here are the ones the browser must NOT invent:
 * a lab trajectory (computed from typed nodes, never scraped from prose) and a
 * source locator (doc_id + page + char range, always derived from provenance
 * fields the pipeline wrote, never guessed).
 */

import { getPage } from './api';

/* ------------------------------------------------------------------ */
/* Lab trends                                                          */
/* ------------------------------------------------------------------ */

/**
 * Group LabResult nodes by LOINC into TrendChart-shaped series.
 *
 * `TrendChart` expects `{series:[{t,v,unit,id}], display, unit, ref_low,
 * ref_high, summary:{change_pct}}` — the same shape the Python
 * `ClinicalGraph.trend` returns, so the component works unchanged against
 * either. Only series with at least two points are returned; a single draw is
 * a value, not a trend, and drawing a line through one point would imply a
 * trajectory that does not exist.
 */
export function computeTrends(graph) {
  const byLoinc = new Map();
  (graph?.nodes || [])
    .filter((n) => n.type === 'LabResult')
    .forEach((n) => {
      const key = n.loinc || n.display || n.id;
      if (!byLoinc.has(key)) byLoinc.set(key, []);
      byLoinc.get(key).push(n);
    });

  const out = [];
  byLoinc.forEach((nodes) => {
    const pts = nodes
      .filter((n) => n.value !== null && n.value !== undefined && !Number.isNaN(Number(n.value)))
      .sort((a, b) => (String(a.time) < String(b.time) ? -1 : 1));
    if (pts.length < 2) return;
    const first = pts[0];
    const last = pts[pts.length - 1];
    const delta = Number(last.value) - Number(first.value);
    const changePct = Number(first.value)
      ? Math.round((100 * delta) / Number(first.value) * 10) / 10
      : 0;
    out.push({
      loinc: first.loinc,
      display: first.display || first.loinc,
      unit: first.unit || '',
      ref_low: first.ref_low ?? null,
      ref_high: first.ref_high ?? null,
      hi_is_worse: first.hi_is_worse !== false,
      series: pts.map((p) => ({ t: String(p.time).slice(0, 10), v: Number(p.value), unit: p.unit, id: p.id })),
      summary: {
        change_pct: changePct,
        delta: Math.round(delta * 1000) / 1000,
        deteriorated: first.hi_is_worse === false ? delta < 0 : delta > 0,
      },
      node_ids: pts.map((p) => p.id),
    });
  });

  // Most points first: that is the series a clinician most wants to see.
  return out.sort((a, b) => b.series.length - a.series.length);
}

/* ------------------------------------------------------------------ */
/* Provenance                                                          */
/* ------------------------------------------------------------------ */

/** Every doc_id this record can point at, in encounter order. */
export function docIdsFor(patient) {
  const ids = [];
  const push = (d) => {
    const id = d && (d.source_doc_id || d.doc_id);
    if (id && !ids.includes(id)) ids.push(id);
  };
  (patient?.encounters || []).forEach(push);
  (patient?.diagnoses || []).forEach(push);
  (patient?.meds || []).forEach(push);
  (patient?.labs || []).forEach(push);
  (patient?.notes || []).forEach(push);
  return ids;
}

/**
 * Where a node came from, without touching the network.
 *
 * Returns null when the node carries no provenance. Contract 2 only puts
 * `source_doc_id` on encounters, diagnoses, meds and notes — labs and allergies
 * are bare observations, so for those we fall back to locating the term inside
 * the document text (see `locateTerm`). A null here is rendered as an explicit
 * "no document provenance recorded", never as a link that goes nowhere.
 */
export function sourceOf(item) {
  if (!item) return null;
  const docId = item.source_doc_id || item.doc_id;
  if (!docId) return null;
  return {
    docId,
    page: Number(item.source_page || item.page || 1),
    charStart: Number(item.source_char_start || 0) || 0,
    charEnd: Number(item.source_char_end || 0) || 0,
  };
}

/** Human label for a node, used in evidence cards and citations. */
export function nodeLabel(node) {
  if (!node) return '';
  switch (node.type) {
    case 'LabResult':
      return `${node.display || node.loinc} ${node.value}${node.unit ? ` ${node.unit}` : ''}`;
    case 'MedicationOrder':
      return `${node.name}${node.dose ? ` ${node.dose}` : ''} ${node.frequency || ''}`.trim();
    case 'Diagnosis':
      return node.display || node.code;
    case 'Allergy':
      return `${node.substance} — ${node.reaction}`;
    case 'Note':
      return node.text;
    case 'Encounter':
      return `${node.type || 'encounter'} ${String(node.start).slice(0, 10)}`;
    default:
      return node.display || node.name || node.id;
  }
}

/**
 * Find a term in the pages of the documents this record knows about.
 *
 * This is the honest way to reach a source for a node that carries no
 * character offsets of its own: we look in the real text layer and report the
 * real offsets we found. If it is not found we say so instead of highlighting
 * the whole document, which would be a fake citation.
 *
 * Long labels are matched on a ladder: the full string first, then
 * progressively shorter prefixes. A renderer may print "Chronic kidney
 * disease, stage 3" where the label says "Chronic kidney disease", and
 * searching only the first word would resolve "Chronic" to whatever sentence
 * happens to contain it — technically a highlight, practically a wrong
 * citation. The ladder stops at the longest prefix that actually appears.
 */
export async function locateTerm(docIds, term, maxPages = 3) {
  const full = String(term || '').trim();
  if (!full) return null;

  const needles = [full];
  const words = full.split(/\s+/);
  for (const n of [4, 2, 1]) {
    if (words.length > n) {
      const shorter = words.slice(0, n).join(' ').replace(/[,;]$/, '');
      if (shorter && !needles.includes(shorter)) needles.push(shorter);
    }
  }

  // Page text is fetched once per document and reused across the ladder,
  // otherwise a five-candidate search would re-request every page five times.
  const pages = [];
  for (const docId of docIds) {
    for (let p = 1; p <= maxPages; p += 1) {
      try {
        const res = await getPage(docId, p);
        if (!res.data || !res.data.text) break;
        pages.push({ docId, text: res.data.text, page: res.data.page });
      } catch {
        break; // this document has no such page
      }
    }
  }
  if (!pages.length) return null;

  for (const needle of needles) {
    for (const pg of pages) {
      const idx = pg.text.indexOf(needle);
      if (idx >= 0) {
        return {
          docId: pg.docId, page: pg.page,
          charStart: idx, charEnd: idx + needle.length,
          resolvedBy: 'text-search', term: needle,
        };
      }
    }
  }
  return null;
}