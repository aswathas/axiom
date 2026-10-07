"""Tests for the LLM prose extractor.

The LLM is mocked everywhere. Nothing in this file touches the network: a test
suite that spends money or burns a rate-limited tier is a test suite nobody runs.

The properties under test are the ones that protect the clinical graph:

  * negation is never silently dropped, and a denied symptom never becomes a
    positive one;
  * every accepted fact's offsets really slice back to the phrase that supports
    it;
  * an unavailable or malformed model costs us facts, never an exception.
"""

from __future__ import annotations

import pytest

from axiom.extract.prose import extract_prose
from axiom.llm import LLMUnavailable

# The Contract 3 Layout B discharge summary, verbatim from docs/CONTRACTS.md.
NOTE = """ST. MARGARET'S MEDICAL CENTER
Department of Internal Medicine

DISCHARGE SUMMARY

Patient: Bergman, L.        DOB: 04/12/1964        MRN: MRN762900
Admit Date: 01/15/2025      Discharge Date: 01/22/2025
Attending: Ramanathan, K.

DIAGNOSIS
1. Chronic kidney disease, stage 3 (N18.3)
2. Essential hypertension (I10)
3. Type 2 diabetes mellitus (E11.9)

PRESENTING HISTORY
Patient is a 60-year-old female presenting with progressive fatigue and
worsening exertional dyspnea. She denies chest pain. She denies hematuria.
Creatinine rose from 0.85 to 1.48 over the admission.

MEDICATIONS ON DISCHARGE
- Metformin 500 mg PO BID
- Lisinopril 10 mg PO daily
- Warfarin 5 mg PO daily

DISPOSITION
Follow up with Cardiology within 2 weeks. Renal nephrology referral placed.
"""


class FakeLLM:
    """Stands in for ``LLMClient``. Records prompts, replays a canned answer."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def json(self, system, user):
        self.calls.append((system, user))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _fact_payload(**overrides):
    item = {
        "kind": "dx",
        "name": "Chronic kidney disease, stage 3",
        "phrase": "Chronic kidney disease, stage 3 (N18.3)",
        "meta": {"code": "N18.3"},
    }
    item.update(overrides)
    return item


def _ok(*items):
    return FakeLLM({"facts": list(items)})


# ---------------------------------------------------------------------------
# Happy path: diagnoses
# ---------------------------------------------------------------------------

def test_extracts_diagnosis_with_code_and_category():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(_fact_payload()))
    assert len(facts) == 1
    f = facts[0]
    assert f.kind == "dx"
    assert f.name == "Chronic kidney disease, stage 3"
    assert f.meta["code"] == "N18.3"
    assert f.meta["category"] == "renal"   # resolved from the frozen ICD table
    assert f.extractor == "llm"


def test_diagnosis_code_inferred_from_the_phrase_when_model_omits_it():
    """The document carries (N18.3); we read it, we do not take the model's word."""
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        _fact_payload(meta={})))
    assert facts[0].meta["code"] == "N18.3"
    assert facts[0].meta["category"] == "renal"


def test_known_codes_resolve_to_display_names():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        _fact_payload(name="I10", phrase="Essential hypertension (I10)")))
    assert facts[0].name == "Essential hypertension"


# ---------------------------------------------------------------------------
# Medications
# ---------------------------------------------------------------------------

def test_extracts_discharge_medication_with_dose_and_frequency():
    facts = extract_prose(NOTE, "doc_1", llm=_ok({
        "kind": "med",
        "name": "Metformin",
        "phrase": "Metformin 500 mg PO BID",
        "meta": {"dose": "500 mg", "frequency": "BID"},
    }))
    f = facts[0]
    assert (f.kind, f.name) == ("med", "Metformin")
    assert f.meta["dose"] == "500 mg"
    assert f.meta["frequency"] == "BID"
    assert f.meta["active"] is True
    # axiom/patient.py reads meta["name"] -> graph "drug" if we put one here,
    # which collides. The drug name lives on Fact.name and nowhere else.
    assert "name" not in f.meta


# ---------------------------------------------------------------------------
# Negation — the highest-value property in this module
# ---------------------------------------------------------------------------

def test_denied_symptom_is_negated():
    facts = extract_prose(NOTE, "doc_1", llm=_ok({
        "kind": "note_stance",
        "name": "chest pain",
        "phrase": "She denies chest pain",
        "negated": True,
    }))
    assert len(facts) == 1
    assert facts[0].negated is True
    assert facts[0].kind == "note_stance"


def test_a_denied_symptom_is_never_emitted_as_positive():
    """Even a model that forgets the flag must not get a positive chest pain.

    This is the assertion that matters: a positive "chest pain" node on this
    patient's chart is a clinically wrong claim, not a cosmetic bug.
    """
    facts = extract_prose(NOTE, "doc_1", llm=_ok({
        "kind": "note_stance",
        "name": "chest pain",
        "phrase": "She denies chest pain",
        "negated": False,          # the model got it wrong
    }))
    assert facts[0].negated is True
    assert not any(f.name == "chest pain" and not f.negated for f in facts)


def test_negation_scope_covers_the_clause_not_only_the_word():
    """'No evidence of sepsis' negates sepsis even though 'sepsis' is the phrase."""
    text = "Admission impression: No evidence of sepsis during this admission."
    facts = extract_prose(text, "doc_1", llm=_ok({
        "kind": "note_stance",
        "name": "sepsis",
        "phrase": "sepsis",
        "negated": False,
    }))
    assert facts[0].negated is True


def test_asserted_symptom_is_not_negated():
    text = "Patient reports worsening exertional dyspnea."
    facts = extract_prose(text, "doc_1", llm=_ok({
        "kind": "note_stance",
        "name": "dyspnea",
        "phrase": "dyspnea",
        "negated": False,
    }))
    assert facts[0].negated is False


def test_negation_is_stamped_on_every_kind_not_just_stances():
    """The model calls denials all kinds of things. None may escape positive.

    Found by a live call: the model typed "She denies chest pain" as kind="dx"
    with no negation flag, and the guard's verdict was computed correctly and then
    thrown away by the dx shaper. A fact is only as negated as its kind allows.
    """
    for kind in ("dx", "med", "lab", "vital", "imaging", "allergy", "note_stance"):
        facts = extract_prose(NOTE, "doc_1", llm=_ok({
            "kind": kind, "name": "chest pain",
            "phrase": "She denies chest pain", "negated": False,
        }))
        assert len(facts) == 1, kind
        assert facts[0].negated is True, kind


def test_a_denial_typed_as_a_diagnosis_never_becomes_a_diagnosis():
    """The model really does emit kind="dx" for "denies chest pain".

    axiom/patient.py turns a dx fact into a problem-list Diagnosis node. A
    Diagnosis node for a symptom the patient explicitly denied is a fabricated
    condition, so a negated non-stance is demoted to a stance about the record.
    """
    facts = extract_prose(NOTE, "doc_1", llm=_ok({
        "kind": "dx", "name": "Chest pain", "phrase": "She denies chest pain",
    }))
    f = facts[0]
    assert f.negated is True
    assert f.kind == "note_stance"
    assert f.meta["reported_as"] == "dx"


def test_a_real_diagnosis_is_untouched_by_the_demotion_rule():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(_fact_payload()))
    assert facts[0].kind == "dx"
    assert facts[0].negated is False


def test_speculative_findings_are_dropped_not_asserted():
    text = "Chest film possible left lower lobe infiltrate."
    facts = extract_prose(text, "doc_1", llm=_ok({
        "kind": "note_stance",
        "name": "left lower lobe infiltrate",
        "phrase": "possible left lower lobe infiltrate",
        "negated": False,
    }))
    assert facts == []


def test_two_denials_in_one_note_both_survive():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        {"kind": "note_stance", "name": "chest pain",
         "phrase": "She denies chest pain", "negated": True},
        {"kind": "note_stance", "name": "hematuria",
         "phrase": "She denies hematuria", "negated": True},
    ))
    assert {f.name for f in facts} == {"chest pain", "hematuria"}
    assert all(f.negated for f in facts)


# ---------------------------------------------------------------------------
# Temporal trends stated in prose
# ---------------------------------------------------------------------------

def test_trend_values_become_lab_facts_with_timestamps():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        {"kind": "lab", "name": "Creatinine", "value": 0.85,
         "unit": "mg/dL", "phrase": "rose from 0.85",
         "timestamp": "2025-01-15"},
        {"kind": "lab", "name": "Creatinine", "value": 1.48,
         "unit": "mg/dL", "phrase": "to 1.48",
         "timestamp": "2025-01-22"},
    ))
    assert [f.value for f in facts] == [0.85, 1.48]
    assert [f.timestamp for f in facts] == ["2025-01-15", "2025-01-22"]
    assert facts[0].loinc == "2160-0"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_offsets_slice_back_to_the_supporting_phrase():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(_fact_payload()))
    f = facts[0]
    assert NOTE[f.source_char_start:f.source_char_end] == \
        "Chronic kidney disease, stage 3 (N18.3)"


def test_provenance_fields_are_always_populated():
    facts = extract_prose(NOTE, "doc_9", page=3, llm=_ok(
        _fact_payload(),
        {"kind": "med", "name": "Lisinopril", "phrase": "Lisinopril 10 mg PO daily"},
    ))
    for f in facts:
        assert f.source_doc_id == "doc_9"
        assert f.source_page == 3
        assert f.source_char_start > 0
        assert f.source_char_end > f.source_char_start
        assert f.source_char_end <= len(NOTE)
        assert f.extractor == "llm"


def test_duplicate_phrases_get_their_own_offsets():
    """Running-offset scan, not text.find(): two identical mentions, two spans."""
    text = "Metformin 500 mg daily. Patient reports rash. Metformin 500 mg daily."
    facts = extract_prose(text, "doc_1", llm=_ok(
        {"kind": "med", "name": "Metformin", "phrase": "Metformin 500 mg daily"},
        {"kind": "med", "name": "Metformin", "phrase": "Metformin 500 mg daily"},
    ))
    assert len(facts) == 2
    starts = [f.source_char_start for f in facts]
    assert starts[0] != starts[1]
    assert starts[0] < starts[1]
    for f in facts:
        assert text[f.source_char_start:f.source_char_end] == \
            "Metformin 500 mg daily"


def test_fact_whose_phrase_is_nowhere_in_the_text_is_dropped():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        _fact_payload(),
        _fact_payload(name="Pulmonary embolism", phrase="massive pulmonary embolism"),
    ))
    assert [f.name for f in facts] == ["Chronic kidney disease, stage 3"]


def test_a_hallucinated_fabrication_never_becomes_a_graph_node():
    facts = extract_prose(NOTE, "doc_1", llm=_ok(
        _fact_payload(name="Acute myocardial infarction",
                      phrase="Acute myocardial infarction")))
    assert facts == []


def test_empty_text_returns_no_facts_and_never_calls_the_model():
    llm = _ok(_fact_payload())
    assert extract_prose("", "doc_1", llm=llm) == []
    assert llm.calls == []


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------

def test_llm_unavailable_degrades_to_empty_list():
    llm = FakeLLM(LLMUnavailable("openrouter unavailable after 3 attempts"))
    assert extract_prose(NOTE, "doc_1", llm=llm) == []


def test_no_client_configured_degrades_to_empty_list(monkeypatch):
    """LLMClient() raises when no key is set; the upload path must survive it.

    The client is patched out rather than allowed to construct itself: a test
    that builds a real LLMClient is a test that hits the network.
    """
    def _boom(*a, **k):
        raise LLMUnavailable("No LLM provider configured")

    monkeypatch.setattr("axiom.llm.LLMClient", _boom)
    assert extract_prose(NOTE, "doc_1", llm=None) == []


@pytest.mark.parametrize("payload", [
    {"facts": "not a list"},
    {"facts": [{"kind": "dx"}]},                       # no name
    {"facts": [{"name": "CKD", "phrase": "x"}]},        # no kind
    {"facts": [{"kind": "banana", "name": "CKD", "phrase": "x"}]},
    {"facts": [{"kind": "dx", "name": "CKD"}]},         # no phrase
    {"facts": [{"kind": "dx", "name": "CKD", "phrase": "x", "negated": "yes"}]},
    {"no_facts_key": []},
])
def test_malformed_output_rejects_the_whole_batch(payload):
    """Half a batch is never published: a malformed answer means no answer."""
    assert extract_prose(NOTE, "doc_1", llm=_ok(payload)) == []


def test_malformed_output_does_not_take_valid_facts_down_with_it():
    good = _fact_payload()
    bad = {"kind": "dx", "name": "Missing phrase key"}
    assert extract_prose(NOTE, "doc_1", llm=_ok(good, bad)) == []


def test_unexpected_model_exceptions_degrade_too():
    assert extract_prose(NOTE, "doc_1", llm=FakeLLM(RuntimeError("boom"))) == []


# ---------------------------------------------------------------------------
# Prompt hygiene
# ---------------------------------------------------------------------------

def test_prompt_carries_the_document_and_asks_for_verbatim_phrases():
    llm = _ok(_fact_payload())
    extract_prose(NOTE, "doc_1", llm=llm)
    system, user = llm.calls[0]
    assert "She denies chest pain" in user
    assert "phrase" in system
    assert "verbatim" in system.lower()


def test_no_api_key_material_ever_reaches_the_prompt():
    llm = _ok(_fact_payload())
    system, user = llm.calls[0] if llm.calls else ("", "")
    extract_prose(NOTE, "doc_1", llm=llm)
    system, user = llm.calls[0]
    for blob in (system, user):
        assert "sk-" not in blob
        assert "Bearer" not in blob
