"""
AXIOM — clinical document rendering (Contract 3 layouts A, B, C).

Three renderers, one idea: every line of a document is drawn as a SINGLE
``drawString`` call, and every column inside a line is space-padded to a fixed
x anchor. That matters more than it looks. A PDF text layer is a bag of
positioned glyph runs, and most extractors (pypdf, pdfminer, the browser's own
copy-paste) rebuild reading order from those runs. If a table row is drawn as
seven separate strings, the extractor sees seven runs whose inter-word spacing is
a guess -- two adjacent numbers end up separated by one space, sometimes zero,
sometimes a newline. Splitting the row on whitespace then silently merges the
result column with the units column.

So: one string per line, real spaces between columns. Extraction gets the line
back byte-for-byte as written, and the parser's column assumptions hold.

Typeface is Helvetica, one of the PDF base-14 fonts. No TTF embedding. Embedded
TrueType subsets get re-encoded differently across reportlab versions and pypdf
revisions, which is a genuinely unpleasant way to lose a hardcoded anchor string.
Base-14 is encoded by the format itself, so the text layer is stable.

Determinism: canvases are opened with ``invariant=1``, which pins the
``/CreationDate`` and producer string. Without it reportlab stamps wall-clock
time into every file and two runs of the same input differ byte-for-byte, which
would make the reproducibility test fail for reasons that have nothing to do with
this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas as rl_canvas

__all__ = [
    "LabAnalyte",
    "extract_text",
    "render_lab_report",
    "render_discharge_summary",
    "render_pharmacy_printout",
]

# --------------------------------------------------------------------------
# Institutions. Fictional. "Quest Diagnostics" appears in Contract 3 as the
# literal Layout A anchor and is used here as a specimen-lab label only.
# --------------------------------------------------------------------------
LAB_NAME = "QUEST DIAGNOSTICS"
LAB_ADDRESS = "8401 Wilson Boulevard, Tampa, FL 33618"
HOSP_LAB_NAME = "ST. MARGARET'S MEDICAL CENTER LABORATORY"
HOSP_LAB_ADDRESS = "1200 Harborview Road, Tampa, FL 33606"
HOSPITAL_NAME = "ST. MARGARET'S MEDICAL CENTER"
HOSPITAL_DEPT = "Department of Internal Medicine"
PHARMACY_NAME = "HARBORVIEW PHARMACY"

PAGE_W, PAGE_H = LETTER
MARGIN = 54.0
TOP = PAGE_H - MARGIN

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
SIZE = 9.0
LEADING = 13.0

# Table column x anchors (Layout A). Chosen so the widest plausible cell in each
# column does not run into the next one.
COL_ANALYTE = MARGIN
COL_RESULT = 208.0
COL_UNITS = 274.0
COL_RANGE = 352.0
COL_FLAG = 520.0


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _decimals(span: float) -> int:
    """Pick a reference-range precision from the width of the range.

    Contract 3 is internally inconsistent about decimals -- "0.60 - 1.30",
    "90 - 140", "135.0 - 145.0" -- and reproducing that literally per analyte
    would mean hardcoding three magic formats. This rule reproduces all three:
    a wide range gets no decimals, a middling one gets one, a narrow one gets
    two, which is also how reference ranges are actually printed.
    """
    if span >= 20:
        return 0
    if span >= 5:
        return 1
    return 2


def _fmt(value: float, dp: int) -> str:
    return f"{value:.{dp}f}"


def _fmt_range(lo: float, hi: float, dp: int) -> str:
    return f"{_fmt(lo, dp)} - {_fmt(hi, dp)}"


def _fmt_dob(dob: str) -> str:
    """ISO "1964-04-12" -> "04/12/1964". Layouts print US dates."""
    y, m, d = dob.split("-")
    return f"{m}/{d}/{y}"


def _fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def _pad(text: str, x_start: float, x_end: float, font=FONT, size=SIZE) -> str:
    """Pad `text` with real spaces so the next field starts at `x_end`."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    avail = x_end - x_start
    used = stringWidth(text, font, size)
    n = max(1, int((avail - used) / stringWidth(" ", font, size)))
    return text + " " * n


# --------------------------------------------------------------------------
# the page primitive
# --------------------------------------------------------------------------

class _Page:
    """A monospaced-by-construction text page: one drawString per line."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.c = rl_canvas.Canvas(str(self.path), pagesize=LETTER, invariant=1)
        # Fixed metadata: a title derived from the filename would make the bytes
        # depend on where the file happens to be written.
        self.c.setTitle("Clinical Document")
        self.c.setAuthor("AXIOM synthetic document generator")
        self.c.setSubject("Synthetic clinical record")
        self.y = TOP
        self._font = FONT
        self._size = SIZE

    def line(self, text: str = "", font: str | None = None, size: float | None = None,
             x: float = MARGIN, leading: float | None = None) -> None:
        font = font or self._font
        size = size if size is not None else self._size
        self.c.setFont(font, size)
        # A single drawString per line: the extractor returns this string intact.
        self.c.drawString(x, self.y, text)
        self.y -= leading if leading is not None else LEADING

    def blank(self, n: int = 1) -> None:
        self.y -= LEADING * n

    def rule(self, dashes: int = 80) -> None:
        self.line("-" * dashes)

    def close(self) -> None:
        self.c.showPage()
        self.c.save()


# --------------------------------------------------------------------------
# public value types
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class LabAnalyte:
    """One result row in Layout A.

    `flag` is precomputed ("H"/"L"/"A"/"") rather than inferred here: Layout A
    is a faithful printout of a lab system, and lab systems apply their own
    critical-value logic. Recomputing it in the renderer would mean the renderer
    silently disagreeing with the upstream result.
    """
    loinc: str
    display: str
    value: float
    unit: str
    ref_low: float
    ref_high: float
    flag: str = ""


# --------------------------------------------------------------------------
# Layout A -- Quest-style chemistry report
# --------------------------------------------------------------------------

def render_lab_report(path: Path, *, patient: dict[str, Any], collected: str,
                      accession: str, ordering_physician: str, panel: str,
                      analytes: Sequence[LabAnalyte],
                      lab_name: str = LAB_NAME,
                      lab_address: str = LAB_ADDRESS) -> Path:
    """`lab_name`/`lab_address` default to the Layout A anchors. They are
    overridable so a conflicting pair can genuinely come from two systems."""
    p = _Page(path)

    p.line(lab_name, font=FONT_BOLD, size=13, leading=16)
    p.line(lab_address, leading=15)
    p.blank()

    p.line("Patient: " + _pad(patient["name"], 0, 300)
           + "MRN: " + patient["mrn"])
    p.line("DOB: " + _pad(_fmt_dob(patient["dob"]), 0, 300)
           + "Collected: " + collected)
    p.line("Accession: " + _pad(accession, 0, 300)
           + "Ordering Physician: " + ordering_physician)
    p.blank()

    p.line(panel, font=FONT_BOLD, leading=16)
    p.blank()

    # header row, padded onto the same x anchors as the data rows below it
    head = (_pad("Analyte", COL_ANALYTE - MARGIN, COL_RESULT - MARGIN)
            + _pad("Result", COL_RESULT - MARGIN, COL_UNITS - MARGIN)
            + _pad("Units", COL_UNITS - MARGIN, COL_RANGE - MARGIN)
            + _pad("Reference Range", COL_RANGE - MARGIN, COL_FLAG - MARGIN)
            + "Flag")
    p.line(head, font=FONT_BOLD, leading=11)
    p.rule()
    p.blank(0)

    for a in analytes:
        dp = _decimals(abs(a.ref_high - a.ref_low))
        row = (_pad(a.display, 0, COL_RESULT - MARGIN)
               + _pad(_fmt(a.value, dp), COL_RESULT - MARGIN, COL_UNITS - MARGIN)
               + _pad(a.unit, COL_UNITS - MARGIN, COL_RANGE - MARGIN)
               + _pad(_fmt_range(a.ref_low, a.ref_high, dp), COL_RANGE - MARGIN,
                      COL_FLAG - MARGIN)
               + a.flag)
        p.line(row)

    p.blank()
    p.line("End of Report")
    p.close()
    return path


# --------------------------------------------------------------------------
# Layout B -- discharge summary
# --------------------------------------------------------------------------

def _wrap(text: str, width: int = 88) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def render_discharge_summary(path: Path, *, patient: dict[str, Any], admit: str,
                             discharge: str, attending: str,
                             diagnoses: Sequence[tuple[str, str]],
                             history: Sequence[str],
                             meds: Sequence[tuple[str, str, str]],
                             disposition: Sequence[str]) -> Path:
    """`history` / `disposition` arrive as paragraphs; each is wrapped here.

    Sentences are kept on one line where possible so the parser's negation scope
    ("She denies chest pain.") is not split across a line break mid-clause.
    """
    p = _Page(path)

    p.line(HOSPITAL_NAME, font=FONT_BOLD, size=13, leading=16)
    p.line(HOSPITAL_DEPT, leading=15)
    p.blank()
    p.line("DISCHARGE SUMMARY", font=FONT_BOLD, size=11, leading=16)
    p.blank()

    p.line("Patient: " + _pad(patient["name"], 0, 210)
           + "DOB: " + _pad(_fmt_dob(patient["dob"]), 0, 180)
           + "MRN: " + patient["mrn"])
    p.line("Admit Date: " + _pad(_fmt_date(admit), 0, 300)
           + "Discharge Date: " + _fmt_date(discharge))
    p.line("Attending: " + attending)
    p.blank()

    p.line("DIAGNOSIS", font=FONT_BOLD, leading=15)
    for i, (display, code) in enumerate(diagnoses, 1):
        p.line(f"{i}. {display} ({code})")
    p.blank()

    p.line("PRESENTING HISTORY", font=FONT_BOLD, leading=15)
    for para in history:
        for ln in _wrap(para):
            p.line(ln)
    p.blank()

    p.line("MEDICATIONS ON DISCHARGE", font=FONT_BOLD, leading=15)
    for name, dose, directions in meds:
        p.line(f"- {name} {dose} {directions}")
    p.blank()

    p.line("DISPOSITION", font=FONT_BOLD, leading=15)
    for para in disposition:
        for ln in _wrap(para):
            p.line(ln)

    p.close()
    return path


# --------------------------------------------------------------------------
# Layout C -- pharmacy prescription history
# --------------------------------------------------------------------------

def render_pharmacy_printout(path: Path, *, patient: dict[str, Any],
                            meds: Sequence[tuple[str, str, str, str]],
                            subtitle: str = "Prescription History") -> Path:
    """`meds` rows are (name, strength, directions, start MM/DD/YYYY)."""
    p = _Page(path)

    p.line(PHARMACY_NAME, font=FONT_BOLD, size=13, leading=16)
    p.line(subtitle)
    p.blank()

    p.line("Patient: " + _pad(patient["name"], 0, 230)
           + "DOB: " + _pad(_fmt_dob(patient["dob"]), 0, 190)
           + "MRN: " + patient["mrn"])
    p.blank()

    c_name, c_strength, c_dir, c_start = MARGIN, 200.0, 280.0, 470.0
    head = (_pad("Medication", 0, c_strength - MARGIN)
            + _pad("Strength", c_strength - MARGIN, c_dir - MARGIN)
            + _pad("Directions", c_dir - MARGIN, c_start - MARGIN)
            + "Start")
    p.line(head, font=FONT_BOLD, leading=11)
    p.rule()
    p.blank(0)

    for name, strength, directions, start in meds:
        row = (_pad(name, 0, c_strength - MARGIN)
               + _pad(strength, c_strength - MARGIN, c_dir - MARGIN)
               + _pad(directions, c_dir - MARGIN, c_start - MARGIN)
               + start)
        p.line(row)

    p.close()
    return path


# --------------------------------------------------------------------------
# text extraction, used by the tests and by anyone verifying a round trip
# --------------------------------------------------------------------------

def extract_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)