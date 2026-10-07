"""Contract 3 Layout A (lab) and Layout C (Rx) parsing.

Every assertion here is against the exact document text in docs/CONTRACTS.md,
because the whole point of this module is that it is deterministic and that its
provenance offsets are real.
"""

import pytest

from axiom.clinical import ANALYTES
from axiom.extract.tables import (parse_document, parse_lab_report,
                                  parse_rx_report)
from axiom.facts import is_abnormal


# --- Contract 3 Layout A ----------------------------------------------------

LAB_TEXT = """                    QUEST DIAGNOSTICS
              8401 Wilson Boulevard, Tampa, FL 33618

Patient: Bergman, L.          MRN: MRN762900
DOB: 04/12/1964               Collected: 04/15/2025 09:42
Accession: 2518473920         Ordering Physician: Ramanathan, K.

CHEMISTRY - RENAL PANEL

Analyte                     Result     Units       Reference Range    Flag
--------------------------------------------------------------------------------
Creatinine                     1.48      mg/dL       0.60 - 1.30          H
eGFR                            41     mL/min/1.73m2  90 - 140           L
Potassium                      5.20      mmol/L      3.50 - 5.10          H
Sodium                        131.0      mmol/L      135.0 - 145.0       L

End of Report
"""

# INR has NO unit column, and an analyte that is not in ANALYTES at all.
LAB_NOUNIT_TEXT = """                    QUEST DIAGNOSTICS

Patient: Bergman, L.          MRN: MRN762900
DOB: 04/12/1964               Collected: 04/15/2025 09:42

COAGULATION PANEL

Analyte                     Result     Units       Reference Range    Flag
--------------------------------------------------------------------------------
INR                             1.35                   0.80 - 1.20         H
Hemoglobin                     11.2       g/dL        12.0 - 17.5         L
Unobtainium Assay                7.00      arb units     1.00 - 2.00

End of Report
"""


def _by_name(facts, name):
    got = [f for f in facts if f.name.lower() == name.lower()]
    assert got, f"no fact named {name!r} in {[f.name for f in facts]}"
    return got[0]


def test_parse_lab_report_finds_every_mapped_row():
    facts = parse_lab_report(LAB_TEXT, doc_id="doc_lab_1")
    assert [f.name for f in facts] == ["Creatinine", "eGFR", "Potassium", "Sodium"]


def test_lab_fact_values_units_and_loinc():
    cr = _by_name(parse_lab_report(LAB_TEXT, "d"), "Creatinine")
    assert cr.kind == "lab"
    assert cr.value == 1.48
    assert cr.unit == "mg/dL"
    assert cr.loinc == "2160-0"
    assert cr.timestamp == "2025-04-15"

    egfr = _by_name(parse_lab_report(LAB_TEXT, "d"), "eGFR")
    assert egfr.value == 41
    assert egfr.unit == "mL/min/1.73m2"
    assert egfr.loinc == "33914-3"


def test_lab_reference_range_and_abnormal_are_computed_not_guessed():
    facts = parse_lab_report(LAB_TEXT, "d")
    cr = _by_name(facts, "Creatinine")
    assert (cr.ref_low, cr.ref_high) == (0.60, 1.30)
    assert cr.abnormal is True
    # The flag column says H; the computed value must agree, and it must be
    # derived from the range rather than read off the flag.
    assert cr.abnormal == is_abnormal(cr.value, cr.ref_low, cr.ref_high)

    egfr = _by_name(facts, "eGFR")
    assert (egfr.ref_low, egfr.ref_high) == (90.0, 140.0)
    assert egfr.abnormal is True

    na = _by_name(facts, "Sodium")
    assert (na.ref_low, na.ref_high) == (135.0, 145.0)
    assert na.abnormal is True
    assert na.value == 131.0


def test_in_range_value_is_not_abnormal():
    text = LAB_TEXT.replace("Creatinine                     1.48",
                            "Creatinine                     0.95")
    cr = _by_name(parse_lab_report(text, "d"), "Creatinine")
    assert cr.abnormal is False


def test_provenance_offsets_are_the_real_offsets_in_the_text():
    text = LAB_TEXT
    for f in parse_lab_report(text, doc_id="doc_lab_9", page=4):
        assert f.source_doc_id == "doc_lab_9"
        assert f.source_page == 4
        assert f.extractor == "regex"
        assert f.source_char_end > f.source_char_start
        assert text[f.source_char_start:f.source_char_end] == f.name, (
            f"offsets do not slice back to {f.name!r}: "
            f"{text[f.source_char_start:f.source_char_end]!r}")


def test_provenance_is_not_a_whole_document_find():
    """`Creatinine` also appears in narrative text earlier; the offsets must
    point at the table row, not the first occurrence anywhere in the document."""
    text = ("Creatinine rose from 0.85 to 1.48 over the admission.\n"
            + LAB_TEXT)
    f = _by_name(parse_lab_report(text, "d"), "Creatinine")
    assert text[f.source_char_start:f.source_char_end] == "Creatinine"
    assert f.source_char_start > text.index("Creatinine rose")


def test_missing_unit_column_still_parses_inr():
    facts = parse_lab_report(LAB_NOUNIT_TEXT, doc_id="doc_lab_2")
    inr = _by_name(facts, "INR")
    assert inr.value == 1.35
    assert inr.unit is None
    assert inr.loinc == "6301-6"
    assert (inr.ref_low, inr.ref_high) == (0.80, 1.20)
    assert inr.abnormal is True


def test_unmappable_analyte_produces_no_fact():
    facts = parse_lab_report(LAB_NOUNIT_TEXT, doc_id="doc_lab_2")
    names = [f.name for f in facts]
    assert "Unobtainium Assay" not in names
    assert "Unobtainium" not in " ".join(names)
    assert all(f.loinc for f in facts)


def test_header_and_rule_lines_are_not_parsed_as_rows():
    text = LAB_TEXT
    assert "Analyte" not in [f.name for f in parse_lab_report(text, "d")]
    # 2160-0 is the Creatinine LOINC; ensure no numeric-only row leaked through
    for f in parse_lab_report(text, "d"):
        assert f.name in ANALYTES.values() or f.loinc is not None


def test_multiword_analyte_name_with_spaced_range():
    text = (
        "CHEMISTRY - CBC\n\n"
        "Analyte                     Result     Units       Reference Range    Flag\n"
        "-----------------------------------------------------------------\n"
        "Urea Nitrogen                 28.0      mg/dL       7.0 - 20.0          H\n"
        "Hemoglobin                   11.2       g/dL      12.0 - 17.5         L\n"
    )
    facts = parse_lab_report(text, "d")
    un = _by_name(facts, "Urea Nitrogen")
    assert un.value == 28.0
    assert un.loinc == "3094-0"
    assert (un.ref_low, un.ref_high) == (7.0, 20.0)
    assert un.abnormal is True


def test_reference_range_without_spaces_around_dash():
    text = (
        "Analyte      Result   Units   Reference Range   Flag\n"
        "Creatinine    1.48    mg/dL   0.60-1.30          H\n"
    )
    cr = _by_name(parse_lab_report(text, "d"), "Creatinine")
    assert (cr.ref_low, cr.ref_high) == (0.60, 1.30)


def test_row_without_flag_column():
    text = (
        "Analyte        Result   Units   Reference Range\n"
        "Glucose          142    mg/dL   70.0 - 99.0\n"
    )
    g = _by_name(parse_lab_report(text, "d"), "Glucose")
    assert g.value == 142
    assert g.abnormal is True


def test_row_without_reference_range_leaves_abnormal_none():
    text = (
        "Analyte        Result   Units\n"
        "Glucose          142    mg/dL\n"
    )
    g = _by_name(parse_lab_report(text, "d"), "Glucose")
    assert g.value == 142
    assert g.ref_low is None and g.ref_high is None
    assert g.abnormal is None


def test_duplicate_rows_get_distinct_offsets():
    """Two identical rows must not both resolve to the first one's offsets."""
    row = "Creatinine      1.48    mg/dL   0.60-1.30\n"
    text = "Analyte      Result   Units   Reference Range\n" + row + row
    facts = parse_lab_report(text, "d")
    assert len(facts) == 2
    starts = {f.source_char_start for f in facts}
    assert len(starts) == 2
    assert starts == {text.index(row), text.rindex(row)}


def test_missing_collected_date_leaves_timestamp_none():
    text = ("Analyte        Result   Units   Reference Range\n"
            "Glucose          142    mg/dL   70.0 - 99.0\n")
    assert _by_name(parse_lab_report(text, "d"), "Glucose").timestamp is None


def test_empty_text_returns_no_facts():
    assert parse_lab_report("", "d") == []


def test_date_formats_accepted():
    for stamp, iso in (("Collected: 04/15/2025 09:42", "2025-04-15"),
                       ("Collected: 4/5/2025", "2025-04-05"),
                       ("Collected: 12/31/2025", "2025-12-31")):
        text = (f"{stamp}\n\n"
                "Analyte      Result   Units   Reference Range\n"
                "Creatinine    1.48    mg/dL   0.60-1.30\n")
        assert _by_name(parse_lab_report(text, "d"), "Creatinine").timestamp == iso


def test_rows_are_column_aligned_or_nothing():
    """A report that has lost its column alignment (single-space separated) is
    not silently half-parsed. Contract 3 Layout A is a fixed-width table; if
    the alignment is gone we would rather drop the row than invent a unit."""
    text = "Creatinine 1.48 mg/dL 0.60-1.30 H\n"
    assert parse_lab_report(text, "d") == []


# --- Contract 3 Layout C ----------------------------------------------------

RX_TEXT = """HARBORVIEW PHARMACY
Prescription History

Patient: Bergman, L.     DOB: 04/12/1964     MRN: MRN762900

Medication            Strength     Directions              Start
------------------------------------------------------------------------------
Metformin             500 mg       Take 1 tablet PO BID     01/15/2025
Lisinopril             10 mg       Take 1 tablet PO daily   01/15/2025
Warfarin                5 mg       Take 1 tablet PO daily   03/02/2025
"""


def test_parse_rx_report_rows():
    facts = parse_rx_report(RX_TEXT, doc_id="doc_rx_1", page=2)
    assert [f.name for f in facts] == ["Metformin", "Lisinopril", "Warfarin"]
    assert all(f.kind == "med" for f in facts)


def test_rx_meta_dose_frequency_and_null_rxnorm():
    m = _by_name(parse_rx_report(RX_TEXT, "doc_rx_1"), "Metformin")
    assert m.meta["dose"] == "500 mg"
    assert m.meta["frequency"] == "Take 1 tablet PO BID"
    assert m.meta["rxnorm"] is None
    assert m.value is None
    assert m.unit is None


def test_rx_timestamp_from_start_column():
    facts = parse_rx_report(RX_TEXT, "doc_rx_1")
    assert _by_name(facts, "Warfarin").timestamp == "2025-03-02"
    assert _by_name(facts, "Lisinopril").timestamp == "2025-01-15"


def test_rx_provenance_offsets():
    text = RX_TEXT
    for f in parse_rx_report(text, doc_id="doc_rx_2", page=1):
        assert f.source_doc_id == "doc_rx_2"
        assert f.source_page == 1
        assert text[f.source_char_start:f.source_char_end] == f.name


def test_rx_skips_header_and_rule_lines():
    assert "Medication" not in [f.name for f in parse_rx_report(RX_TEXT, "d")]
    assert "HARBORVIEW PHARMACY" not in [f.name for f in parse_rx_report(RX_TEXT, "d")]


def test_rx_row_without_start_date():
    text = ("Medication    Strength   Directions   Start\n"
            "Metformin     500 mg     Take 1 tablet PO BID\n")
    m = _by_name(parse_rx_report(text, "d"), "Metformin")
    assert m.timestamp is None


def test_rx_empty_text():
    assert parse_rx_report("", "d") == []


# --- dispatch ---------------------------------------------------------------

def test_parse_document_dispatches_lab():
    # A lab report is also evidence of an outpatient encounter, so the
    # encounter fact is appended after the analytes rather than replacing one.
    assert [f.kind for f in parse_document(LAB_TEXT, "d")] == ["lab"] * 4 + ["encounter"]


def test_parse_document_dispatches_rx():
    assert [f.kind for f in parse_document(RX_TEXT, "d")] == ["med"] * 3


def test_parse_document_on_narrative_returns_no_regex_facts(monkeypatch):
    # These assert the *regex* path. The prose extractor is opt-in via
    # AXIOM_PROSE_LLM, so pin it off — otherwise running the suite with
    # that variable set turns a deterministic assertion into a network
    # call against a rate-limited free tier.
    monkeypatch.delenv("AXIOM_PROSE_LLM", raising=False)
    narrative = "DISCHARGE SUMMARY\n\nPatient denies chest pain.\n"
    assert parse_document(narrative, "d") == []


def test_parse_document_never_invents_provenance():
    for f in parse_document(LAB_TEXT, "doc_x"):
        assert f.source_doc_id == "doc_x"
        assert f.extractor == "regex"