'use client';

import { useCallback, useState } from 'react';
import { locateTerm, nodeLabel, sourceOf } from '../lib/derive';

/**
 * A single citation chip, and the guarantee behind it.
 *
 * Resolution order:
 *   1. The node's own `source_doc_id` / `source_page` / char offsets. Exact.
 *   2. If Contract 2 left the node without provenance (labs and allergies are
 *      bare observations), search the text layer of the documents this record
 *      does reference for the node's own term and open the real offsets found.
 *
 * If neither works, the chip renders struck-through. That is the point: the
 * brief is that a claim is worthless if you cannot reach its source, so an
 * unreachable citation must be visible on screen rather than quietly clickable.
 */
export default function Cite({ node, graph, docIds, onSource, label, title }) {
  const [state, setState] = useState({ busy: false, unresolvable: false });

  const direct = sourceOf(node);

  const open = useCallback(async () => {
    if (direct) {
      onSource({
        docId: direct.docId,
        page: direct.page,
        charStart: direct.charStart,
        charEnd: direct.charEnd,
        label: nodeLabel(node),
        nodeId: node.id,
        raw: node,
      });
      return;
    }
    if (state.busy) return;
    setState({ busy: true, unresolvable: false });
    const term = searchTerm(node);
    const found = await locateTerm(docIds || [], term);
    setState({ busy: false, unresolvable: !found });
    if (found) {
      onSource({
        docId: found.docId,
        page: found.page,
        charStart: found.charStart,
        charEnd: found.charEnd,
        label: nodeLabel(node),
        nodeId: node.id,
        raw: node,
      });
    }
  }, [direct, docIds, node, onSource, state.busy]);

  const text = label
    || (node ? (String(node.time || '').slice(0, 10) || node.id) : 'unresolved');

  if (state.unresolvable) {
    return (
      <span className="cite dead" title="This term was not found in any document this record references">
        {text} ✕
      </span>
    );
  }

  return (
    <button
      type="button"
      className="cite"
      onClick={open}
      disabled={state.busy}
      title={title
        || (direct
          ? `${nodeLabel(node)} — ${direct.docId} page ${direct.page}`
          : `Locate "${searchTerm(node)}" in the referenced documents`)}
    >
      {state.busy ? 'locating…' : text}
    </button>
  );
}

/**
 * The string we look for in the document text.
 *
 * For a lab node that is the analyte display name, which is exactly how it is
 * printed in a lab report. For everything else the node's own label. Truncated
 * to the first word for multi-part labels so we search for "Chronic kidney
 * disease, stage 3" rather than a string the renderer never produced.
 */
function searchTerm(node) {
  if (!node) return '';
  if (node.display) return String(node.display);
  if (node.substance) return String(node.substance);
  if (node.name) return String(node.name);
  return String(nodeLabel(node)).split(/[\s,]/)[0] || '';
}

/** The dot on the other end: used when a cited node id is absent from the graph. */
export function DeadCite({ id, reason }) {
  return (
    <span className="cite dead" title={reason || 'no such node in this graph'}>
      {id} ✕
    </span>
  );
}