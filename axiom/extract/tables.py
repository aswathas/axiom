"""Deterministic table extraction for the Contract 3 layouts.

No LLM, no network, no guessing. Every fact carries offsets that slice back to
the exact analyte or medication name in the source string, and every
``abnormal`` value is computed by :func:`axiom.facts.is_abnormal`.

Layouts parsed here
-------------------
Layout A (lab report)  -> ``kind="lab"`` Facts
Layout C (Rx printout) -> ``kind="med"`` Facts

Layout B (discharge summary) is narrative and belongs to the LLM extractor; the
regex pass deliberately returns nothing for it rather than half-parsing prose.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from axiom.clinical import ANALYTES
from axiom.facts import Fact, is_abnormal

from .detect import detect_kind

__all__ = [
    "parse_lab_report",
    "parse_rx_report",
    "parse_document",
    "detect_kind",
    "loinc_for_analyte",
]  # parse_encounters lives in axiom.extract.encounters (see below)


# ---------------------------------------------------------------------------
# Column splitting
# ---------------------------------------------------------------------------

# A report is rendered as whitespace-aligned columns, so two or more spaces is
# the column separator. Two spaces specifically: "0.60  -  1.30" must survive
# as one cell.
_COLUMN_SPLIT = re.compile(r"\s{2,}")
_NUM = re.compile(r"^[<>]?\s*[-+]?\d+(?:\.\d+)?$")
_STRENGTH = re.compile(r"^\d+(?:\.\d+)?\s+\S")
_FLAG = re.compile(r"^[HLA]$", re.IGNORECASE)
_MM_DD_YYYY = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATE_CELL = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _cells(line: str) -> list[str]:
    """Split a rendered row into column cells, rejoining split reference ranges."""
    raw = [c.strip() for c in _COLUMN_SPLIT.split(line.strip()) if c.strip()]
    merged: list[str] = []
    for cell in raw:
        # "0.60  -  1.30" arrived as ["0.60", "-", "1.30"] or ["0.60", "-1.30"].
        if merged and _NUM.match(cell.lstrip("<>").strip()) and merged[-1] == "-":
            merged[-1] = f"{merged[-2]} {cell}".strip()
            merged.pop()
        elif merged and cell.startswith("-") and _NUM.match(cell[1:]) \
                and _NUM.match(merged[-1]):
            merged[-1] = f"{merged[-1]}{cell}"
        else:
            merged.append(cell)
    return merged


# ---------------------------------------------------------------------------
# Value / range helpers
# ---------------------------------------------------------------------------

def _to_float(text: str) -> Optional[float]:
    cleaned = text.strip().lstrip("<>").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_number(cell: str) -> bool:
    return bool(_NUM.match(cell))


def parse_reference_range(cell: str) -> Optional[tuple[Optional[float], Optional[float]]]:
    """Parse a reference-range cell.

    Returns ``None`` when the cell is not a range at all (a unit, a flag, prose
    such as "Negative"), otherwise a ``(low, high)`` pair where either side may
    be ``None`` for an open bound.
    """
    s = cell.strip()
    if not s or not re.search(r"\d", s):
        return None

    inclusive = s.startswith("<=") or s.startswith(">=")
    # Open bounds: "<5.0", ">1000". Equality is deliberately NOT treated as an
    # out-of-range comparison against the strict < / > in is_abnormal.
    m = re.match(r"^([<>]=?)\s*(\d+(?:\.\d+)?)$", s)
    if m:
        bound = float(m.group(2))
        return (bound, None) if m.group(1).startswith("<") else (None, bound)

    m = re.match(r"^(\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$", s)
    if m:
        low, high = float(m.group(1)), float(m.group(2))
        return (min(low, high), max(low, high)) if low > high else (low, high)

    # A bare number is a degenerate one-sided range; we do not guess which side
    # it bounds, so we refuse rather than fabricate a limit.
    return None


def to_iso_date(text: str) -> Optional[str]:
    """MM/DD/YYYY -> "YYYY-MM-DD". None when unparseable."""
    m = _MM_DD_YYYY.search(text)
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


# ---------------------------------------------------------------------------
# Analyte -> LOINC, built from the frozen ANALYTES dict (never a second copy)
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()


_ANALYTE_INDEX: dict[str, str] = {
    _normalise(display): loinc for loinc, (display, *_rest) in ANALYTES.items()
}


def loinc_for_analyte(name: str) -> Optional[str]:
    """Case- and whitespace-insensitive display name -> LOINC, or None.

    None means the analyte is not in the terminology subset. The caller must
    then skip the row: an unmappable analyte may not become a graph node.
    """
    return _ANALYTE_INDEX.get(_normalise(name))


# ---------------------------------------------------------------------------
# Layout A — lab report
# ---------------------------------------------------------------------------

_COLLECTED = re.compile(r"Collected:\s*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE)


def _lines_with_offsets(text: str) -> list[tuple[str, int]]:
    """Yield (line, absolute_start_offset) pairs.

    Walking a running offset rather than calling text.find() per line keeps
    duplicate rows honest: a second identical row must get its own offsets,
    not the first row's.
    """
    out: list[tuple[str, int]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        out.append((line, cursor))
        cursor += len(line)
    return out


def parse_lab_report(text: str, doc_id: str, page: int = 1) -> list[Fact]:
    """Parse a Contract 3 Layout A lab report into ``kind="lab"`` Facts."""
    collected = _COLLECTED.search(text)
    timestamp = to_iso_date(collected.group(1)) if collected else None

    facts: list[Fact] = []
    for line, offset in _lines_with_offsets(text):
        fact = _parse_lab_line(line, doc_id, page, timestamp, offset)
        if fact is not None:
            facts.append(fact)
    return facts


def _parse_lab_line(line: str, doc_id: str, page: int,
                    timestamp: Optional[str], offset: int) -> Optional[Fact]:
    if not line.strip() or set(line.strip()) <= {"-", "=", "_"}:
        return None

    cells = _cells(line)
    if len(cells) < 2:
        return None

    name = cells[0]
    loinc = loinc_for_analyte(name)
    if loinc is None:
        return None  # unmappable analyte -> no fact, no graph node

    # The result column is the first strictly numeric cell after the name; a
    # range cell like "0.60 - 1.30" is not a number and is skipped over.
    value_idx = next((i for i in range(1, len(cells)) if _is_number(cells[i])), None)
    if value_idx is None:
        return None
    value = _to_float(cells[value_idx])

    unit: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    for cell in cells[value_idx + 1:]:
        if _FLAG.match(cell) or (len(cell) <= 1 and cell.isalpha()):
            continue  # the H / L / A flag column
        rng = parse_reference_range(cell)
        if rng is not None and (rng[0] is not None or rng[1] is not None):
            ref_low, ref_high = rng
            continue
        if unit is None:
            unit = cell

    start = _offset_of(line, offset, name)
    if start is None:
        return None

    return Fact(
        kind="lab",
        name=name,
        value=value,
        unit=unit or None,
        timestamp=timestamp,
        loinc=loinc,
        ref_low=ref_low,
        ref_high=ref_high,
        abnormal=is_abnormal(value, ref_low, ref_high),
        extractor="regex",
        source_doc_id=doc_id,
        source_page=page,
        source_char_start=start,
        source_char_end=start + len(name),
    )


# ---------------------------------------------------------------------------
# Layout C — medication printout
# ---------------------------------------------------------------------------

def parse_rx_report(text: str, doc_id: str, page: int = 1) -> list[Fact]:
    """Parse a Contract 3 Layout C pharmacy printout into ``kind="med"`` Facts."""
    facts: list[Fact] = []
    for line, offset in _lines_with_offsets(text):
        fact = _parse_rx_line(line, doc_id, page, offset)
        if fact is not None:
            facts.append(fact)
    return facts


def _parse_rx_line(line: str, doc_id: str, page: int, offset: int) -> Optional[Fact]:
    stripped = line.strip()
    if not stripped or set(stripped) <= {"-", "=", "_"}:
        return None

    cells = _cells(line)
    if len(cells) < 2:
        return None

    name = cells[0]
    rest = cells[1:]

    timestamp: Optional[str] = None
    if rest and _DATE_CELL.match(rest[-1]):
        timestamp = to_iso_date(rest[-1])
        rest = rest[:-1]

    # A medication row always carries a strength ("500 mg"); header rows and
    # the patient-demographics line do not. That single rule is the whole row
    # filter, and it is why we can be this permissive about the rest.
    strength_idx = next((i for i, c in enumerate(rest) if _STRENGTH.match(c)), None)
    if strength_idx is None:
        return None
    dose = rest[strength_idx]
    directions = " ".join(rest[strength_idx + 1:]).strip()

    start = _offset_of(line, offset, name)
    if start is None:
        return None

    meta: dict[str, Any] = {"dose": dose, "frequency": directions or None,
                            "rxnorm": None}
    return Fact(
        kind="med",
        name=name,
        value=None,
        unit=None,
        timestamp=timestamp,
        meta=meta,
        extractor="regex",
        source_doc_id=doc_id,
        source_page=page,
        source_char_start=start,
        source_char_end=start + len(name),
    )


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

def _offset_of(line: str, offset: int, name: str) -> Optional[int]:
    """Absolute offset of ``name`` within this specific line of ``text``.

    Deliberately not ``text.find(name)``: a lab analyte is very often mentioned
    earlier in the narrative ("Creatinine rose from 0.85 to 1.48"), and a
    document-wide find would point the audit trail at the prose instead of the
    table row that actually produced the fact.
    """
    idx = line.find(name)
    if idx < 0:
        return None
    return offset + idx


def parse_document(text: str, doc_id: str, page: int = 1) -> list[Fact]:
    """Detect the document kind and run the matching deterministic parser.

    Encounters run for *every* document kind, not just the notes: a lab report
    is evidence of an outpatient encounter and a discharge summary is evidence
    of an admission. They are appended after the kind-specific facts, so an
    encounter is never mistaken for content of the document's primary type.
    """
    kind = detect_kind(text)
    facts: list[Fact] = []
    if kind == "lab":
        facts.extend(parse_lab_report(text, doc_id, page))
    elif kind == "rx":
        facts.extend(parse_rx_report(text, doc_id, page))
    # "note" is narrative (Contract 3 Layout B); its prose belongs to the LLM
    # extractor, but its admit/discharge dates are exact and belong here.
    #
    # Imported here rather than at the top of the module: encounters.py builds
    # on _lines_with_offsets and to_iso_date from this file, so a module-level
    # import in both directions is a cycle.
    from .encounters import parse_encounters

    facts.extend(parse_encounters(text, doc_id, page))

    # Contract 3 Layout B narrative. Off unless AXIOM_PROSE_LLM is switched on,
    # so a test run, a benchmark or an offline box never spends network quota or
    # waits on a rate-limited tier. On failure the LLM extractor returns [], so
    # a bad tier costs us facts and never the upload.
    if kind == "note" and _prose_enabled():
        from .prose import extract_prose

        facts.extend(extract_prose(text, doc_id, page))
    return facts


def _prose_enabled() -> bool:
    """True when LLM prose extraction is explicitly switched on."""
    import os

    return os.environ.get("AXIOM_PROSE_LLM", "").strip().lower() in {
        "1", "true", "yes", "on",
    }