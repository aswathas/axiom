"""Deterministic encounter extraction — the time anchors the graph needs.

An encounter is the only node in ``ClinicalGraph`` that carries a *start* time
and a *duration*. Without them ``_build`` emits no ``precedes`` edges and no
``occurs_during`` edges, and the four temporal question classes — the whole
technical moat — cannot fire at all. This module manufactures them from the
text layer, with no LLM and no guessing.

Sources handled, in priority order per document
-----------------------------------------------
1. Contract 3 **Layout B** discharge summary — ``Admit Date:`` /
   ``Discharge Date:``. Yields one ``inpatient`` encounter whose ``start`` is
   the admit date. The all-caps banner line becomes ``meta["facility"]`` and a
   ``Department of ...`` line becomes ``meta["service"]``.
2. A ``VISIT:`` / ``Encounter Date:`` line.
3. Contract 3 **Layout A** lab report — ``Collected: MM/DD/YYYY``. Lab
   collection is a genuine clinical event and is what gives outpatient patients
   any time anchor at all.

Two ambiguities in Layout B were decided deliberately, and both are recorded
here because they are judgement calls, not facts:

* **Discharge date with no admit date.** The stay still happened, so it is
  emitted with ``start`` = the discharge date and ``meta["admit"] = None``.
  Dropping it would lose a node; inventing an admit date would be a lie.
* **Two identical dates in one document.** Offsets come from a running walk
  over the lines, never ``text.find()``, so a second ``VISIT: 05/05/2025`` gets
  its own offset. (Agent A hit that bug; see ``tables._offset_of``.)
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple, Optional

from axiom.facts import Fact

from .tables import _lines_with_offsets, to_iso_date

__all__ = ["parse_encounters", "parse_admit_discharge"]


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

_ADMIT = re.compile(r"Admit(?:ted)?\s*(?:Date)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_DISCHARGE = re.compile(
    r"Discharg(?:e|ed)\s*(?:Date)?\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_COLLECTED = re.compile(r"Collected\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_VISIT = re.compile(
    r"(?:VISIT|Encounter\s+Date|Visit\s+Date|Service\s+Date)\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{4})", re.I)

_SERVICE = re.compile(r"^\s*Department\s+of\s+(\S.*?)\s*$", re.I | re.M)
# The banner is the first line that reads as an all-caps proper name: at least
# two words, every word starting upper case, no digits.
_FACILITY = re.compile(r"^\s*([A-Z][A-Z'.&-]*(?:[ ][A-Z][A-Z'.&-]*)+)\s*$", re.M)


class Anchor(NamedTuple):
    """A date found in the text: its ISO form, its absolute offset, and the
    source spelling, so the audit trail slices to what the reader sees."""
    iso: str
    offset: int
    raw: str


def _anchor(line: str, offset: int, rx: re.Pattern[str]) -> Optional[Anchor]:
    m = rx.search(line)
    if not m:
        return None
    iso = to_iso_date(m.group(1))
    if iso is None:
        return None
    return Anchor(iso, offset + m.start(1), m.group(1))


def _service(text: str) -> Optional[str]:
    m = _SERVICE.search(text)
    return m.group(1).strip() if m else None


def _facility(text: str) -> Optional[str]:
    m = _FACILITY.search(text)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_encounters(text: str, doc_id: str, page: int = 1) -> list[Fact]:
    """Every encounter this document evidences, most-specific source first.

    A discharge summary that happens to embed a lab collection line still
    yields one encounter — the admission, not the draw. Within the chosen
    source, *every* anchor yields a fact: a note that lists three visits
    evidences three encounters, and each must carry its own offsets.
    """
    if not text or not text.strip():
        return []

    for source in (_inpatient_facts, _visit_facts, _collected_facts):
        facts = source(text, doc_id, page)
        if facts:
            return facts
    return []


def parse_admit_discharge(text: str, doc_id: str, page: int = 1) -> list[Fact]:
    """Only the inpatient admissions, if this document has them.

    Narrower than :func:`parse_encounters` on purpose: a caller that only cares
    about stays must not be handed a lab draw it never asked for.
    """
    if not text or not text.strip():
        return []
    return _inpatient_facts(text, doc_id, page)


def _inpatient_facts(text: str, doc_id: str, page: int) -> list[Fact]:
    lines = _lines_with_offsets(text)
    admits = [a for a in (_anchor(l, o, _ADMIT) for l, o in lines) if a is not None]

    facts: list[Fact] = []
    orphan_discharges: list[Anchor] = []
    paired: set[int] = set()
    for line, offset in lines:
        discharge = _anchor(line, offset, _DISCHARGE)
        if discharge is None:
            continue
        same_line = _anchor(line, offset, _ADMIT)
        if same_line is not None:
            paired.add(same_line.offset)
            facts.append(_inpatient(text, doc_id, page, same_line, discharge,
                                    len(facts)))
        else:
            orphan_discharges.append(discharge)

    if not admits:
        # No admit anywhere: each discharge date is the sole evidence of a stay,
        # and the stay is still real. Keep it, with admit=None rather than a
        # fabricated one.
        for discharge in orphan_discharges:
            facts.append(_inpatient(text, doc_id, page, None, discharge,
                                    len(facts)))
        return facts

    # A discharge on its own line pairs with the most recent preceding admit.
    # In Layout B the two sit side by side, but a wrapped PDF text layer can
    # split them; pairing to the *next* admit would invent a stay that never
    # happened, so an unpairable discharge is dropped rather than guessed.
    for discharge in orphan_discharges:
        prior = [a for a in admits if a.offset <= discharge.offset]
        if not prior:
            continue
        admit = max(prior, key=lambda a: a.offset)
        paired.add(admit.offset)
        facts.append(_inpatient(text, doc_id, page, admit, discharge, len(facts)))

    # An admission with no discharge is still an admission. Emitting it is what
    # keeps a truncated or still-open stay visible in the timeline.
    for admit in admits:
        if admit.offset not in paired:
            facts.append(_inpatient(text, doc_id, page, admit, None, len(facts)))

    facts.sort(key=lambda f: (f.timestamp or "", f.source_char_start))
    return facts


def _visit_facts(text: str, doc_id: str, page: int) -> list[Fact]:
    facts: list[Fact] = []
    for line, offset in _lines_with_offsets(text):
        visit = _anchor(line, offset, _VISIT)
        if visit is not None:
            facts.append(_outpatient(text, doc_id, page, visit, len(facts)))
    return facts


def _collected_facts(text: str, doc_id: str, page: int) -> list[Fact]:
    facts: list[Fact] = []
    for line, offset in _lines_with_offsets(text):
        collected = _anchor(line, offset, _COLLECTED)
        if collected is not None:
            facts.append(_outpatient(text, doc_id, page, collected, len(facts)))
    return facts


# ---------------------------------------------------------------------------
# Fact construction
# ---------------------------------------------------------------------------

def _name(doc_id: str, page: int, kind: str, iso: str, ordinal: int = 0) -> str:
    """A stable per-document-page identity.

    Document-scoped on purpose. The date alone is not an identity — two lab
    draws on the same day are two events in this system, and collapsing them
    would delete ``precedes`` edges we need. Re-uploading the same page still
    dedupes, because ``build_patient`` keys on this name. The ordinal only
    appears when one page really does evidence the same visit kind and date
    more than once, so those stay distinct facts.
    """
    base = f"{doc_id}#p{page}:{kind}:{iso}"
    return base if ordinal == 0 else f"{base}#{ordinal}"


def _inpatient(text: str, doc_id: str, page: int,
               admit: Optional[Anchor], discharge: Optional[Anchor],
               ordinal: int = 0) -> Fact:
    if admit is None and discharge is None:  # caller guarantees one of them
        raise ValueError("inpatient encounter requires an admit or discharge date")
    anchor = admit or discharge
    meta: dict[str, Any] = {
        "admit": admit.iso if admit else None,
        "discharge": discharge.iso if discharge else None,
        "type": "inpatient",
        "facility": _facility(text),
        "service": _service(text),
    }
    return Fact(
        kind="encounter",
        name=_name(doc_id, page, "inpatient", anchor.iso, ordinal),
        timestamp=anchor.iso,
        meta=meta,
        extractor="regex",
        source_doc_id=doc_id,
        source_page=page,
        source_char_start=anchor.offset,
        source_char_end=anchor.offset + len(anchor.raw),
    )


def _outpatient(text: str, doc_id: str, page: int, anchor: Anchor,
                ordinal: int = 0) -> Fact:
    meta: dict[str, Any] = {
        # A point visit admits and discharges on the same day. Stating that
        # explicitly keeps the inpatient/outpatient distinction in the data
        # rather than leaving `discharge` undefined for consumers to guess.
        "admit": anchor.iso,
        "discharge": anchor.iso,
        "type": "outpatient",
        "facility": _facility(text),
        "service": _service(text),
    }
    return Fact(
        kind="encounter",
        name=_name(doc_id, page, "outpatient", anchor.iso, ordinal),
        timestamp=anchor.iso,
        meta=meta,
        extractor="regex",
        source_doc_id=doc_id,
        source_page=page,
        source_char_start=anchor.offset,
        source_char_end=anchor.offset + len(anchor.raw),
    )
