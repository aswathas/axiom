"""Document-kind detection.

The whole point is that detection never calls anything expensive: a string of
deterministic heuristics, so a wrong guess is debuggable.
"""

from axiom.extract.detect import detect_kind
from axiom.extract.tables import parse_document

LAB_TEXT = """                    QUEST DIAGNOSTICS
              8401 Wilson Boulevard, Tampa, FL 33618

Patient: Bergman, L.          MRN: MRN762900
DOB: 04/12/1964               Collected: 04/15/2025 09:42

CHEMISTRY - RENAL PANEL

Analyte                     Result     Units       Reference Range    Flag
--------------------------------------------------------------------------------
Creatinine                     1.48      mg/dL       0.60 - 1.30          H
eGFR                            41     mL/min/1.73m2  90 - 140           L

End of Report
"""

RX_TEXT = """HARBORVIEW PHARMACY
Prescription History

Patient: Bergman, L.     DOB: 04/12/1964     MRN: MRN762900

Medication            Strength     Directions              Start
------------------------------------------------------------------------------
Metformin             500 mg       Take 1 tablet PO BID     01/15/2025
Lisinopril             10 mg       Take 1 tablet PO daily   01/15/2025
"""

NOTE_TEXT = """ST. MARGARET'S MEDICAL CENTER
Department of Internal Medicine

DISCHARGE SUMMARY

Patient: Bergman, L.        DOB: 04/12/1964        MRN: MRN762900
Admit Date: 01/15/2025      Discharge Date: 01/22/2025
Attending: Ramanathan, K.

DIAGNOSIS
1. Chronic kidney disease, stage 3 (N18.3)

PRESENTING HISTORY
Patient is a 60-year-old female presenting with progressive fatigue.
"""


def test_detect_lab():
    assert detect_kind(LAB_TEXT) == "lab"


def test_detect_rx():
    assert detect_kind(RX_TEXT) == "rx"


def test_detect_note():
    assert detect_kind(NOTE_TEXT) == "note"


def test_detect_unknown_on_prose():
    assert detect_kind("The quick brown fox jumped over the lazy dog.") == "unknown"


def test_detect_unknown_on_empty():
    assert detect_kind("") == "unknown"


def test_detect_is_case_insensitive():
    assert detect_kind(LAB_TEXT.lower()) == "lab"
    assert detect_kind(NOTE_TEXT.upper()) == "note"


def test_detect_prefers_table_over_prose_when_both_present():
    """A discharge summary that also carries a lab table is a lab doc for
    regex purposes; the narrative extractor handles the prose."""
    mixed = NOTE_TEXT + "\n" + LAB_TEXT
    assert detect_kind(mixed) == "lab"
    kinds = [f.kind for f in parse_document(mixed, "d")]
    assert kinds.count("lab") == 2
    # The admission on the note side is still extracted: it is an exact date,
    # and dropping it would cost us the graph's only time anchor. See
    # axiom/extract/encounters.py.
    assert kinds.count("encounter") == 1


def test_detect_rx_beats_lab_on_rx_shaped_text():
    assert detect_kind(RX_TEXT + "\nAnalyte Result Units Reference Range\n") == "rx"