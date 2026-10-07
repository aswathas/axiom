"""Canonical fact schema shared by extraction, storage and graph construction.

See docs/CONTRACTS.md Contract 1. Every extracted observation becomes a Fact
before it is allowed anywhere near the clinical graph.

The provenance fields (source_doc_id, source_page, source_char_start,
source_char_end) are not optional bookkeeping. They are the mechanism by which
every claim the system makes later resolves back to a region of an original
document. A fact without provenance is a fact we are not willing to publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

FACT_KINDS = ("lab", "med", "dx", "allergy", "note_stance", "vital", "imaging")

EXTRACTORS = ("regex", "llm")


@dataclass
class Fact:
    kind: str
    name: str
    value: Optional[Any] = None
    unit: Optional[str] = None
    timestamp: Optional[str] = None
    loinc: Optional[str] = None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    abnormal: Optional[bool] = None
    negated: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
    source_doc_id: str = ""
    source_page: int = 1
    source_char_start: int = 0
    source_char_end: int = 0
    extractor: str = "regex"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __post_init__(self) -> None:
        if self.kind not in FACT_KINDS:
            raise ValueError(f"invalid Fact.kind {self.kind!r}; expected one of {FACT_KINDS}")
        if self.extractor not in EXTRACTORS:
            raise ValueError(f"invalid Fact.extractor {self.extractor!r}")


def is_abnormal(value: Optional[float], low: Optional[float],
                high: Optional[float]) -> Optional[bool]:
    """Computed, never guessed. Returns None when the comparison is undefined."""
    if value is None:
        return None
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    if low is not None or high is not None:
        return False
    return None


def from_dict(d: dict[str, Any]) -> Fact:
    """Reconstruct a Fact from its serialised form, ignoring unknown keys."""
    known = {k: v for k, v in d.items() if k in Fact.__dataclass_fields__}
    return Fact(**known)