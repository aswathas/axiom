"""LLM extraction from narrative prose — Contract 3 Layout B.

The regex pass in :mod:`axiom.extract.tables` deliberately returns nothing for a
discharge summary: a numbered diagnosis list is machine-readable, but a history
of present illness is not, and a regex that half-parses prose produces a chart
full of confident nonsense. This module is the one place in AXIOM where the LLM
is load-bearing rather than cosmetic.

Three properties are enforced here, in this order, and each one is worth more
than the facts themselves:

1. **The model may not assert provenance.** Every fact must be backed by a
   phrase we locate ourselves in the source text with a running-offset scan. A
   citation we cannot verify is worse than no citation, because it is a lie
   about where a claim came from.
2. **The model may not assert negation, only suggest it.** Its ``negated`` flag
   is OR-ed with a deterministic NegEx scope check over the containing clause.
   A model that forgets to negate "She denies chest pain" still cannot get a
   positive chest-pain node onto the chart.
3. **The model may not take the upload path down.** Any failure — no key,
   rate limit, network, malformed JSON — degrades to an empty list.

Nothing here logs or raises anything that could carry the API key.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from axiom.clinical import CONDITIONS, detect_stance
from axiom.facts import FACT_KINDS, Fact

from .tables import loinc_for_analyte

__all__ = ["extract_prose", "SYSTEM_PROMPT"]

log = logging.getLogger("axiom.extract.prose")

# A discharge summary page is a few kilobytes. The cap only protects against a
# pathological upload; truncating the tail cannot corrupt an offset because every
# offset we publish is resolved against the *full* text afterwards.
MAX_CHARS = 12000

# Model vocabulary -> Fact.kind. "symptom" and friends are clinical findings
# about the patient, not structured chart entities; Contract 1 spells that kind
# "note_stance" and graph.py renders its negated flag as the ASSERTED/NEGATED
# stance, so a denied symptom lands exactly where a cited stance belongs.
_KIND_ALIASES = {
    "symptom": "note_stance",
    "finding": "note_stance",
    "negation": "note_stance",
    "observation": "note_stance",
    "condition": "dx",
    "diagnosis": "dx",
    "medication": "med",
    "drug": "med",
    "lab": "lab",
    "laboratory": "lab",
    "result": "lab",
    "vital": "vital",
    "allergy": "allergy",
    "imaging": "imaging",
    "note_stance": "note_stance",
    "dx": "dx",
    "med": "med",
}

SYSTEM_PROMPT = """\
You extract structured clinical facts from a discharge summary.

Return a single JSON object of the form {"facts": [ ... ]}. Nothing else.

Each element of "facts" is an object with:
  "kind"    one of: dx, med, lab, vital, allergy, imaging, note_stance
  "name"    the finding exactly as the document names it, without any
            parenthetical code, e.g. "Chronic kidney disease, stage 3"
  "phrase"  a VERBATIM substring of the document, copied character for character,
            that contains the finding together with the words that qualify it.
            Never paraphrase, never reformat, never invent. Every "phrase" you
            emit must appear literally in the text you were given; if you cannot
            quote a phrase, do not emit the fact.
  "value"   for lab and vital facts only: the number. Omit otherwise.
  "unit"    for lab and vital facts only: the unit if the document states one.
  "timestamp" ISO date "YYYY-MM-DD" if the document dates this observation,
            otherwise null.
  "negated" true when the document DENIES or rules out the finding
            ("denies chest pain", "no evidence of sepsis", "ruled out"). A
            finding that the document merely lacks is NOT negated.
  "meta"    for dx: {"code": "<ICD-10 code if the document prints one>"};
            for med: {"dose": "...", "frequency": "..."}.

Rules that are not negotiable:
  * A denial is a finding. Emit it with "negated": true. Never omit it, and
    never emit it as positive. "She denies chest pain" is a chest pain fact
    with "negated": true.
  * One lab trend stated in prose ("creatinine rose from 0.85 to 1.48") is two
    lab facts, one per value, each quoting its own phrase.
  * Speculation ("possible infiltrate", "consider PE") is not a fact. Skip it.
  * Never add a finding the document does not state. A missing phrase means a
    missing fact.
"""

# "Chronic kidney disease, stage 3 (N18.3)" -> code "N18.3"
_PAREN_CODE = re.compile(r"\(([A-Z]\d{2}(?:\.\d+)?)\)\s*$")

# A code the document prints anywhere in the phrase, even mid-sentence.
_ANY_CODE = re.compile(r"\b([A-Z]\d{2}(?:\.\d+)?)\b")

# Straddles the end of a sentence in rendered PDF text ("pain. She" / "pain.  She").
_SENTENCE_BOUNDARY = re.compile(r"[.!?;:\n]")


# ---------------------------------------------------------------------------
# Provenance — the running-offset scan
# ---------------------------------------------------------------------------

def _locate(text: str, phrase: str, cursor: int) -> Optional[int]:
    """Absolute offset of ``phrase`` at or after ``cursor``, or None.

    Scanning forward from the previous fact's offset rather than calling
    ``text.find`` is what makes a document with the same phrase twice produce two
    distinct, correct spans. When the model returns its items out of document
    order we fall back to a document-wide search — a span found out of order is
    still a real span, and refusing it would lose a true fact.
    """
    idx = text.find(phrase, cursor)
    if idx >= 0:
        return idx
    idx = text.find(phrase)
    return idx if idx >= 0 else None


def _clause_around(text: str, start: int, end: int) -> str:
    """The sentence-like span of ``text`` containing ``[start, end)``.

    Bounded left and right by sentence punctuation, so "No evidence of sepsis"
    reaches the negation cue that sits three words before the finding.
    """
    left = 0
    for m in _SENTENCE_BOUNDARY.finditer(text, 0, start):
        left = m.end()
    right = len(text)
    m = _SENTENCE_BOUNDARY.search(text, end)
    if m is not None:
        right = m.start()
    return text[left:right]


# ---------------------------------------------------------------------------
# Item validation — whole-batch rejection
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().lstrip("<>"))
        except ValueError:
            return None
    return None


def _validate_item(item: Any) -> Optional[dict]:
    """Normalise one model item, or return None if the batch must be rejected.

    None here means *malformed output*, not *an unusable fact*: a missing kind,
    a missing phrase, a non-boolean negation flag. Those are protocol failures
    and the whole response is discarded, because a model that gets the envelope
    wrong will get the contents wrong too.

    A fact that is well-formed but whose phrase we cannot find is a different
    case and is handled by the caller, which drops that fact alone.
    """
    if not isinstance(item, dict):
        return None

    raw_kind = item.get("kind")
    if not isinstance(raw_kind, str):
        return None
    kind = _KIND_ALIASES.get(raw_kind.strip().lower())
    if kind is None or kind not in FACT_KINDS:
        return None

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    phrase = item.get("phrase")
    if not isinstance(phrase, str) or not phrase.strip():
        return None

    negated = item.get("negated", False)
    if not isinstance(negated, bool):
        return None

    meta = item.get("meta")
    if meta is not None and not isinstance(meta, dict):
        return None
    meta = dict(meta or {})

    timestamp = item.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        timestamp = None

    unit = item.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        unit = None

    return {
        "kind": kind,
        "name": name.strip(),
        "phrase": phrase.strip(),
        "value": _as_float(item.get("value")),
        "unit": unit,
        "timestamp": timestamp.strip() if timestamp else None,
        "negated": negated,
        "meta": meta,
    }


def _validate_batch(payload: Any) -> Optional[list[dict]]:
    """Validated items, or None if the response as a whole must be rejected."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("facts")
    if not isinstance(items, list):
        return None
    out: list[dict] = []
    for item in items:
        normalised = _validate_item(item)
        if normalised is None:
            return None
        out.append(normalised)
    return out


# ---------------------------------------------------------------------------
# Per-kind shaping
# ---------------------------------------------------------------------------

def _shape_dx(item: dict, start: int, end: int) -> Fact:
    code = item["meta"].get("code")
    if not isinstance(code, str) or not code.strip():
        code = None
    name = item["name"]

    if code is None:
        # The document is the authority on its own codes. Prefer a code printed
        # at the end of the quoted phrase, which is where this layout puts it.
        tail = _PAREN_CODE.search(name)
        if tail is None:
            tail = _PAREN_CODE.search(item["phrase"])
        if tail is not None:
            code = tail.group(1)
            name = _PAREN_CODE.sub("", name).strip() or name
    if code is None:
        found = _ANY_CODE.findall(item["phrase"])
        code = found[0] if found else None

    # The document's own wording wins: it is the source every fact cites. The
    # frozen ICD table is used for the category, and to expand a name the model
    # returned as a bare code ("I10") into something a clinician can read.
    if name.strip().upper() in CONDITIONS:
        name = CONDITIONS[name.strip().upper()][0]
    if name.strip().upper() == (code or "").upper() and code in CONDITIONS:
        name = CONDITIONS[code][0]

    category = CONDITIONS.get(code, (None, None))[1] if code else None
    declared = item["meta"].get("category")
    if category is None and isinstance(declared, str) and declared.strip():
        category = declared.strip()

    meta = {"code": code, "category": category or "unspecified"}
    return Fact(kind="dx", name=name, timestamp=item["timestamp"],
                meta=meta, extractor="llm",
                source_char_start=start, source_char_end=end)


def _shape_med(item: dict, start: int, end: int) -> Fact:
    meta = {
        "dose": item["meta"].get("dose") or None,
        "frequency": item["meta"].get("frequency") or None,
        "rxnorm": item["meta"].get("rxnorm") or None,
        "active": True,
    }
    # No "name" key: axiom/patient.py maps meta["name"] onto the graph's `drug`
    # key, and the drug name belongs on Fact.name alone.
    return Fact(kind="med", name=item["name"], timestamp=item["timestamp"],
                meta=meta, extractor="llm",
                source_char_start=start, source_char_end=end)


def _shape_lab(item: dict, start: int, end: int) -> Fact:
    name = item["name"]
    loinc = loinc_for_analyte(name)
    return Fact(kind="lab", name=name, value=item["value"],
                unit=item["unit"], timestamp=item["timestamp"],
                loinc=loinc, extractor="llm",
                meta={} if loinc else {"loinc_unmapped": True},
                source_char_start=start, source_char_end=end)


def _shape_stance(item: dict, start: int, end: int) -> Fact:
    return Fact(kind="note_stance", name=item["name"],
                timestamp=item["timestamp"], negated=item["negated"],
                extractor="llm", source_char_start=start, source_char_end=end)


def _shape_fact(item: dict, doc_id: str, page: int,
                start: int, end: int) -> Fact:
    """Build the Fact, then stamp provenance on it in exactly one place.

    Shaping helpers deliberately do not know the document they came from. A fact
    that forgot its own provenance would be caught, but a fact that could only
    ever have provenance because one function sets it is a stronger property.
    """
    kind = item["kind"]
    if kind == "dx":
        fact = _shape_dx(item, start, end)
    elif kind == "med":
        fact = _shape_med(item, start, end)
    elif kind == "lab":
        fact = _shape_lab(item, start, end)
    elif kind == "note_stance":
        fact = _shape_stance(item, start, end)
    else:
        meta = {k: v for k, v in item["meta"].items() if k != "name"}
        fact = Fact(kind=kind, name=item["name"], value=item["value"],
                    unit=item["unit"], timestamp=item["timestamp"],
                    negated=item["negated"], meta=meta, extractor="llm",
                    source_char_start=start, source_char_end=end)

    fact.source_doc_id = doc_id
    fact.source_page = page
    fact.negated = item["negated"]

    # A denial is never a problem-list entry. The model routinely types
    # "She denies chest pain" as kind="dx"; accepting that at face value would
    # put a Diagnosis node for chest pain on a patient who never had it, which
    # is precisely the invented-symptom failure this module exists to prevent.
    # A negated dx/med/lab/imaging/allergy is a stance about the record, so it
    # is demoted to note_stance and keeps its payload in meta.
    if fact.negated and fact.kind != "note_stance":
        fact.meta = {**fact.meta, "reported_as": fact.kind, **item["meta"]}
        fact.kind = "note_stance"
    return fact


# ---------------------------------------------------------------------------
# Client plumbing
# ---------------------------------------------------------------------------

def _default_client(cache_dir: str):
    """Construct the configured client, or None when there is nothing to talk to."""
    try:
        from axiom.llm import LLMClient, LLMUnavailable
    except Exception:  # pragma: no cover - axiom.llm is always importable here
        return None
    try:
        return LLMClient(cache_dir=cache_dir)
    except LLMUnavailable as exc:
        log.warning("prose extraction disabled: no LLM provider available (%s)", exc)
        return None
    except Exception:  # pragma: no cover - defensive
        log.warning("prose extraction disabled: LLM client could not be built",
                    exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_prose(text: str, doc_id: str, page: int = 1,
                  llm=None, cache_dir: str = ".llm_cache") -> list[Fact]:
    """Extract Contract 3 Layout B narrative facts. Never raises.

    Returns ``[]`` when the model is unavailable, when its output is malformed,
    or when no candidate fact survives provenance verification.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    if llm is None:
        llm = _default_client(cache_dir)
        if llm is None:
            return []

    body = text if len(text) <= MAX_CHARS else text[:MAX_CHARS]
    user = (
        "Extract the clinical facts from this discharge summary. Quote every "
        '"phrase" verbatim from the text below.\n\n'
        f"--- BEGIN DOCUMENT ---\n{body}\n--- END DOCUMENT ---"
    )

    try:
        payload = llm.json(SYSTEM_PROMPT, user)
    except Exception as exc:  # noqa: BLE001 - the upload path must survive this
        log.warning("prose extraction skipped for %s p%d: %s",
                    doc_id, page, type(exc).__name__)
        return []

    items = _validate_batch(payload)
    if items is None:
        log.warning("prose extraction rejected for %s p%d: malformed model output",
                    doc_id, page)
        return []

    facts: list[Fact] = []
    dropped = 0
    speculative = 0
    cursor = 0
    for item in items:
        phrase = item["phrase"]
        start = _locate(text, phrase, cursor)
        if start is None:
            dropped += 1
            continue
        end = start + len(phrase)
        cursor = end

        # Negation is OR-ed with a deterministic scope check over the clause the
        # phrase sits in. Monotone in the safe direction: this can only ever turn
        # a positive into a negative, never the reverse, so a model that forgets
        # a denial still cannot get a positive symptom onto the chart.
        stance = detect_stance(_clause_around(text, start, end))
        if stance == "SPECULATIVE":
            speculative += 1
            continue
        item["negated"] = bool(item["negated"]) or stance == "NEGATED"

        facts.append(_shape_fact(item, doc_id, page, start, end))

    if dropped or speculative:
        log.info("prose %s p%d: %d facts, %d dropped (no phrase in source), "
                 "%d dropped (speculative)", doc_id, page, len(facts),
                 dropped, speculative)
    return facts
