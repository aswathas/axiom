"""Document kind detection — deterministic string heuristics, nothing else.

A wrong guess here is cheap to debug (it is a list of ``in`` checks) which is
the only property that matters for a classifier this simple.
"""

from __future__ import annotations

# Ordered most-specific first. The order is load-bearing and covered by
# tests/test_extract_detect.py: an Rx printout that happens to include the
# words "Analyte"/"Reference Range" is still an Rx printout, and a discharge
# summary that embeds a lab table is handled as a lab table here because the
# prose belongs to the narrative extractor, not to this one.
_RX_MARKERS = (
    "prescription history",
    "pharmacy",
    "directions",
    "take 1 tablet",
)

_LAB_MARKERS = (
    "reference range",
    "analyte",
    "collected:",
    "accession:",
    "chemistry",
    "end of report",
)

_NOTE_MARKERS = (
    "discharge summary",
    "admit date",
    "discharge date",
    "attending:",
    "presenting history",
    "department of",
)


def _has(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in text for m in markers)


def detect_kind(text: str) -> str:
    """Classify a document's text layer as "lab" | "rx" | "note" | "unknown"."""
    if not text or not text.strip():
        return "unknown"
    lowered = text.lower()
    if _has(lowered, _RX_MARKERS):
        return "rx"
    if _has(lowered, _LAB_MARKERS):
        return "lab"
    if _has(lowered, _NOTE_MARKERS):
        return "note"
    return "unknown"