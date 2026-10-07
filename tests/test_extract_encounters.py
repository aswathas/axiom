"""Encounter extraction — the missing time anchors for the temporal graph.

Without Encounter nodes ``ClinicalGraph._build`` emits no ``precedes`` edges and
no ``occurs_during`` edges, so all four temporal question classes are dead. These
tests pin the deterministic behaviour: admit/discharge pairs, lab collections,
honest offsets, and no guessing.
"""

from __future__ import annotations

import re

import pytest

from axiom.extract.encounters import parse_admit_discharge, parse_encounters
from axiom.extract.tables import parse_document
from axiom.facts import FACT_KINDS, Fact
from axiom.graph import ClinicalGraph
from axiom.patient import build_patient

# --- fixtures (transcribed from demo_docs/pat_001, real pypdf text) ---------

DISCHARGE_TEXT = (
    "ST. MARGARET'S MEDICAL CENTER\n"
    "Department of Internal Medicine\n"
    "DISCHARGE SUMMARY\n"
    "Patient: Silva, A.                    DOB: 12/04/1984      MRN: MRN954934\n"
    "Admit Date: 01/15/2026                 Discharge Date: 01/22/2026\n"
    "Attending: Ramanathan, K.\n"
    "DIAGNOSIS\n"
    "1. Chronic kidney disease stage 3 (N18.3)\n"
)

LAB_TEXT = (
    "QUEST DIAGNOSTICS\n"
    "8401 Wilson Boulevard, Tampa, FL 33618\n"
    "Patient: Silva, A.                    MRN: MRN954934\n"
    "DOB: 12/04/1984                       Collected: 04/15/2025 08:15\n"
    "Accession: 2518474057                 Ordering Physician: Ramanathan, K.\n"
    "CHEMISTRY - RENAL PANEL\n"
    "Analyte          Result     Units          Reference Range    Flag\n"
    "----------------------------------------------------------------\n"
    "Creatinine       1.06       mg/dL          0.60 - 1.30\n"
    "End of Report\n"
)


def _by_kind(facts, kind):
    return [f for f in facts if f.kind == kind]


# --- Contract 1 -------------------------------------------------------------

def test_encounter_is_a_declared_fact_kind():
    assert "encounter" in FACT_KINDS


def test_encounter_fact_is_constructible():
    Fact(kind="encounter", name="x")  # does not raise


# --- Layout B: admit / discharge --------------------------------------------

def test_admit_discharge_pair_yields_one_inpatient_encounter():
    facts = parse_admit_discharge(DISCHARGE_TEXT, "doc_ds", 1)
    assert len(facts) == 1
    f = facts[0]
    assert f.kind == "encounter"
    assert f.timestamp == "2026-01-15"          # start = admit date
    assert f.meta["admit"] == "2026-01-15"
    assert f.meta["discharge"] == "2026-01-22"
    assert f.meta["type"] == "inpatient"
    assert f.meta["service"] == "Internal Medicine"
    assert f.meta["facility"] == "ST. MARGARET'S MEDICAL CENTER"


def test_admit_date_only_still_yields_an_encounter():
    text = "DISCHARGE SUMMARY\nAdmit Date: 03/04/2025\nAttending: X, Y.\n"
    facts = parse_admit_discharge(text, "doc_ds")
    assert len(facts) == 1
    assert facts[0].timestamp == "2025-03-04"
    assert facts[0].meta["discharge"] is None


def test_discharge_date_only_still_yields_an_encounter():
    text = "DISCHARGE SUMMARY\nDischarge Date: 03/09/2025\n"
    facts = parse_admit_discharge(text, "doc_ds")
    assert len(facts) == 1
    assert facts[0].meta["admit"] is None
    # start falls back to the discharge date; never invented.
    assert facts[0].timestamp == "2025-03-09"


def test_no_dates_no_encounter():
    assert parse_admit_discharge("DISCHARGE SUMMARY\nPatient denies chest pain.\n", "d") == []


def test_unparseable_date_is_skipped_not_guessed():
    text = "DISCHARGE SUMMARY\nAdmit Date: 15 Jan 2025\nDischarge Date: n/a\n"
    assert parse_admit_discharge(text, "d") == []


def test_impossible_month_is_rejected():
    text = "DISCHARGE SUMMARY\nAdmit Date: 13/45/2025\n"
    assert parse_admit_discharge(text, "d") == []


def test_facility_only_from_the_banner():
    # A lab report has an all-caps banner but no admission; it must not be
    # turned into an inpatient encounter with a guessed facility.
    assert parse_admit_discharge(LAB_TEXT, "d") == []


# --- Layout A: lab collection -----------------------------------------------

def test_lab_collected_yields_one_outpatient_encounter():
    facts = parse_encounters(LAB_TEXT, "doc_lab", 2)
    assert len(facts) == 1
    f = facts[0]
    assert f.kind == "encounter"
    assert f.timestamp == "2025-04-15"
    assert f.meta["type"] == "outpatient"
    assert f.source_page == 2


def test_lab_without_collected_date_yields_nothing():
    text = "QUEST DIAGNOSTICS\nAnalyte   Result\nCreatinine   1.06 mg/dL\n"
    assert parse_encounters(text, "d") == []


def test_visit_line_is_honoured():
    text = "VISIT: 07/09/2025\nPatient: Silva, A.\n"
    facts = parse_encounters(text, "d")
    assert len(facts) == 1
    assert facts[0].timestamp == "2025-07-09"
    assert facts[0].meta["type"] == "outpatient"


def test_encounter_date_label_is_honoured():
    text = "Encounter Date: 09/30/2025\n"
    assert parse_encounters(text, "d")[0].timestamp == "2025-09-30"


def test_admit_discharge_wins_over_collected():
    text = DISCHARGE_TEXT + "\nCollected: 04/15/2025\n"
    facts = parse_encounters(text, "d")
    assert len(facts) == 1
    assert facts[0].meta["type"] == "inpatient"


def test_visit_line_wins_over_collected():
    text = "VISIT: 07/09/2025\nCollected: 04/15/2025\n"
    facts = parse_encounters(text, "d")
    assert len(facts) == 1
    assert facts[0].timestamp == "2025-07-09"


# --- provenance: real offsets, duplicates distinct ---------------------------

def test_offsets_slice_back_to_the_admit_date():
    f = parse_admit_discharge(DISCHARGE_TEXT, "d")[0]
    assert DISCHARGE_TEXT[f.source_char_start:f.source_char_end] == "01/15/2026"


def test_offsets_slice_back_to_the_collected_date():
    f = parse_encounters(LAB_TEXT, "d")[0]
    assert LAB_TEXT[f.source_char_start:f.source_char_end] == "04/15/2025"


def test_offsets_slice_back_to_the_visit_date():
    text = "VISIT: 07/09/2025\nPatient: Silva, A.\n"
    f = parse_encounters(text, "d")[0]
    assert text[f.source_char_start:f.source_char_end] == "07/09/2025"


def test_identical_dates_get_distinct_offsets():
    """text.find() would return the first hit for both. A running walk must not."""
    line = "VISIT: 05/05/2025\n"
    text = line * 4
    facts = parse_encounters(text, "d")
    assert len(facts) == 4
    starts = [f.source_char_start for f in facts]
    assert len(set(starts)) == 4
    for f in facts:
        assert text[f.source_char_start:f.source_char_end] == "05/05/2025"
    assert starts == sorted(starts)


def test_identical_admit_dates_across_two_blocks_are_distinct():
    text = "Admit Date: 05/05/2025\nDischarge Date: 05/06/2025\n" * 2
    facts = parse_admit_discharge(text, "d")
    assert len(facts) == 2
    assert facts[0].source_char_start != facts[1].source_char_start


def test_facts_carry_document_provenance():
    for f in parse_encounters(DISCHARGE_TEXT, "doc_1", page=7):
        assert f.source_doc_id == "doc_1"
        assert f.source_page == 7
        assert f.extractor == "regex"
        assert f.source_char_end > f.source_char_start


def test_empty_text():
    assert parse_encounters("", "d") == []


# --- dispatch ---------------------------------------------------------------

def test_parse_document_emits_encounters_for_lab():
    kinds = [f.kind for f in parse_document(LAB_TEXT, "d")]
    assert kinds.count("encounter") == 1


def test_parse_document_emits_encounters_for_discharge_summary():
    facts = parse_document(DISCHARGE_TEXT, "d")
    assert [f.kind for f in facts] == ["encounter"]


def test_parse_document_on_dateless_narrative_still_returns_nothing():
    assert parse_document("DISCHARGE SUMMARY\n\nPatient denies chest pain.\n", "d") == []


# --- Contract 2 + the graph --------------------------------------------------

def test_build_patient_maps_encounters_to_contract_2_shape():
    p = build_patient(parse_encounters(LAB_TEXT, "doc_lab", 1), pid="pat_x")
    assert len(p["encounters"]) == 1
    e = p["encounters"][0]
    assert set(e) >= {"id", "start", "type", "source_doc_id", "source_page"}
    assert e["start"] == "2025-04-15"
    assert e["type"] == "outpatient"


def test_build_patient_encounters_are_time_ordered():
    facts = parse_encounters("VISIT: 09/30/2025\n", "b") + \
            parse_encounters("VISIT: 01/02/2025\n", "a")
    p = build_patient(facts, pid="pat_x")
    assert [e["start"] for e in p["encounters"]] == ["2025-01-02", "2025-09-30"]


def test_encounter_node_type_is_not_shadowed_by_visit_kind():
    p = build_patient(parse_encounters(LAB_TEXT, "d"), pid="pat_x")
    g = ClinicalGraph(p)
    nid = p["encounters"][0]["id"]
    assert g.nodes[nid]["type"] == "Encounter"
    assert g.nodes[nid]["encounter_type"] == "outpatient"


def test_two_encounters_produce_a_precedes_edge():
    facts = parse_encounters("VISIT: 01/02/2025\n", "a") + \
            parse_encounters("VISIT: 09/30/2025\n", "b")
    g = ClinicalGraph(build_patient(facts, pid="pat_x"))
    assert len(g.edges) > 0
    assert g.edges[0][2] == "precedes"


# --- the real generated PDFs --------------------------------------------------

def _pdf_text(path):
    pypdf = pytest.importorskip("pypdf")
    return pypdf.PdfReader(path).pages[0].extract_text()


def test_real_pat_001_documents_produce_a_non_empty_graph():
    from pathlib import Path
    docs = sorted(Path("demo_docs/pat_001").glob("*.pdf"))
    if not docs:
        pytest.skip("demo_docs/pat_001 not generated")
    facts = []
    for path in docs:
        facts.extend(parse_document(_pdf_text(str(path)), path.stem, 1))
    encounters = _by_kind(facts, "encounter")
    assert len(encounters) >= 6, "one per generated document"

    p = build_patient(facts, pid="pat_001")
    g = ClinicalGraph(p)
    assert len(g.by_type["Encounter"]) == len(p["encounters"])
    assert len(g.edges) > 0
    assert any(t == "precedes" for _a, _b, t in g.edges)
    assert g.latest_encounter() is not None
