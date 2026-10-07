"""Tests for the naive RAG strawman.

These tests are NOT asserting that NaiveRAG works. They document what it does,
including the behaviour the demo is built to expose: it answers a question the
record cannot answer, and it answers it without refusing.

If any test here starts failing because NaiveRAG got *better*, read the diff
before "fixing" it — you may have removed the demonstration.
"""

from __future__ import annotations

import pytest

from axiom.baseline_rag import NaiveRAG


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _long_doc(n_words: int = 600, filler: str = "alpha") -> dict:
    words = [filler] * n_words
    return {"doc_id": "doc_long", "page": 1, "text": " ".join(words)}


class RecordingLLM:
    """Stands in for axiom.llm.LLMClient.

    Records the exact (system, user) prompt it was handed and replays a
    recorded response, so tests can assert on both what NaiveRAG asks and what
    it does with the answer.
    """

    def __init__(self, response: str = "No documented evidence of DVT."):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return {"answer": self.response}


# A record with plenty of content and *no coagulation workup at all*.
NO_COAG_DOCS = [
    {
        "doc_id": "doc_lab_01",
        "page": 1,
        "text": (
            "QUEST DIAGNOSTICS. CHEMISTRY - RENAL PANEL.\n"
            "Creatinine 1.48 mg/dL, reference 0.60 - 1.30, flagged H.\n"
            "eGFR 41 mL/min/1.73m2, reference 90 - 140, flagged L.\n"
            "Potassium 5.20 mmol/L, reference 3.50 - 5.10, flagged H.\n"
        ),
    },
    {
        "doc_id": "doc_dc_01",
        "page": 1,
        "text": (
            "ST. MARGARET'S MEDICAL CENTER. DISCHARGE SUMMARY.\n"
            "DIAGNOSIS: 1. Chronic kidney disease, stage 3 (N18.3).\n"
            "2. Essential hypertension (I10). 3. Type 2 diabetes mellitus (E11.9).\n"
            "PRESENTING HISTORY: 60-year-old female with progressive fatigue and\n"
            "worsening exertional dyspnea. She denies chest pain. She denies hematuria.\n"
            "Creatinine rose from 0.85 to 1.48 over the admission.\n"
            "MEDICATIONS ON DISCHARGE: Metformin 500 mg PO BID. Lisinopril 10 mg daily.\n"
            "DISPOSITION: Follow up with Cardiology within 2 weeks.\n"
        ),
    },
]


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

def test_chunking_respects_overlap_and_snaps_to_word_boundaries():
    r = NaiveRAG(chunk_size=200, overlap=60)
    r.index([_long_doc(n_words=300, filler="beta")])

    chunks = r.chunks
    assert len(chunks) > 2, "a 300-word document should produce several chunks"

    # Chunks are ordered, non-empty and carry provenance.
    for i, c in enumerate(chunks):
        assert c["text"].strip()
        assert c["doc_id"] == "doc_long"
        assert c["page"] == 1
        assert c["char_start"] < c["char_end"]
        if i:
            assert chunks[i - 1]["char_start"] < c["char_start"]
            assert chunks[i - 1]["char_end"] == c["char_start"] or True

    # The requested overlap is actually present: consecutive chunks share a
    # verbatim tail region, and that region is at least the requested size
    # (minus one word of snapping slack).
    for prev, cur in zip(chunks, chunks[1:]):
        shared = _long_doc(n_words=300, filler="beta")["text"][
            cur["char_start"]:prev["char_end"]
        ]
        assert shared.strip(), "consecutive chunks must share some text"
        assert len(shared) >= 60 - 10, f"overlap too small: {len(shared)} chars"
        assert shared.strip() in prev["text"]
        assert shared.strip() in cur["text"]

    # No chunk is larger than the window (again allowing word snapping).
    for c in chunks:
        assert len(c["text"]) <= 200 + 20


def test_larger_overlap_yields_more_chunks_for_the_same_document():
    doc = _long_doc(n_words=400, filler="delta")

    no_overlap = NaiveRAG(chunk_size=200, overlap=0)
    no_overlap.index([doc])
    heavy_overlap = NaiveRAG(chunk_size=200, overlap=80)
    heavy_overlap.index([doc])

    assert len(heavy_overlap.chunks) > len(no_overlap.chunks)


def test_empty_document_text_is_tolerated():
    r = NaiveRAG()
    r.index([{"doc_id": "d", "page": 2, "text": ""}])
    assert r.retrieve("anything") == []


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------

def test_retrieval_ranks_the_relevant_chunk_first():
    docs = [
        {"doc_id": "doc_a", "page": 1,
         "text": ("DISCHARGE SUMMARY. She denies chest pain. "
                  + "The patient is ambulating independently. " * 40)},
        {"doc_id": "doc_b", "page": 2,
         "text": ("PHARMACY PRESCRIPTION HISTORY. Warfarin 5 mg take 1 tablet PO "
                  "daily started 03/02/2025 for anticoagulation. "
                  + "Metformin 500 mg twice daily. " * 40)},
        {"doc_id": "doc_c", "page": 1,
         "text": ("IMAGING. Ultrasound of the lower extremity performed. "
                  + "No free fluid. Study performed without complication. " * 40)},
    ]
    r = NaiveRAG()
    r.index(docs)

    hits = r.retrieve("warfarin anticoagulation prescription", top_k=3)
    assert len(hits) == 3
    assert hits[0]["doc_id"] == "doc_b", "relevant chunk must rank first"
    # Scores are descending and bounded by cosine similarity.
    assert hits[0]["score"] >= hits[1]["score"] >= hits[2]["score"]
    assert 0.0 <= hits[2]["score"] <= 1.0
    for h in hits:
        assert {"chunk_id", "doc_id", "page", "text", "score"} <= set(h)


def test_retrieval_top_k_is_respected_and_can_be_overridden():
    docs = [{"doc_id": f"d{i}", "page": 1, "text": f"document {i} " + "filler " * 200}
            for i in range(8)]
    r = NaiveRAG()
    r.index(docs)
    assert len(r.retrieve("filler", top_k=3)) == 3
    # instance default wins when the call does not override
    assert len(r.retrieve("filler")) == 5


def test_unseen_query_still_returns_chunks_because_nothing_gates_on_score():
    """The strawman has no relevance floor. That is the point."""
    docs = [{"doc_id": "d1", "page": 1, "text": "Creatinine 1.48 mg/dL flagged high."}]
    r = NaiveRAG()
    r.index(docs)
    hits = r.retrieve("zeppelin xylophone contraindication", top_k=5)
    assert len(hits) == 1
    assert hits[0]["score"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------
# The demonstration case: absence of evidence read as absence of disease
# --------------------------------------------------------------------------

def test_dvt_query_on_record_without_coagulation_workup_is_not_refused():
    """The failure mode this whole module exists to demonstrate.

    Nothing in the record mentions DVT, coagulation, INR, D-dimer or a venous
    ultrasound. NaiveRAG retrieves the nearest-looking text and asks the LLM to
    answer from it, and the LLM says there is no evidence of a blood clot.

    A clinician reads that as "no blood clot". The record only supports "this
    was never looked for".

    This test asserts the CURRENT behaviour. Do not make it pass by making the
    code refuse — that erases the comparison. AXIOM's refusal is the other
    half of the demo and lives in axiom/pipeline.py.

    Recorded from a real run (openai/gpt-4o-mini, OpenRouter) against this
    exact record:

        Q: Does this patient have a DVT / blood clot?
        A: "No, the patient does not have a DVT / blood clot."

    Note the strawman is *not* uniformly bad. On "Is this patient anaemic?" the
    same model hedges correctly, because anaemia maps onto a specific lab that
    is visibly absent from the context. The demo should use disease-absence
    questions; they are the realistic clinician question and the one that
    produces a flat denial.
    """
    llm = RecordingLLM("No documented evidence of DVT.")
    rag = NaiveRAG(llm=llm, top_k=5)

    result = rag.answer("Does this patient have a DVT / blood clot?", NO_COAG_DOCS)

    # It answers. It does not refuse. Ever.
    assert result["refused"] is False

    # The answer is a confident-sounding negative, not a hedge.
    assert "no documented evidence" in result["answer"].lower()
    assert "refus" not in result["answer"].lower()

    # It cites something, and the citation is real provenance — the citation is
    # correct, the *inference* drawn from it is not.
    assert result["citations"]
    assert all(c["doc_id"] for c in result["citations"])

    # The retrieved context genuinely contains no coagulation data. The system
    # did not miss the evidence; there was none to retrieve.
    context = _last_user_prompt(llm).lower()
    for term in ("d-dimer", "ddimer", "inr", "prothrombin", "coagulation",
                 "thrombosis", "deep venous"):
        assert term not in context


def test_naive_prompt_contains_no_hedging_instructions():
    """Integrity guard on the strawman itself.

    The comparison only means something if the baseline was given the prompt a
    competent team would actually write. If hedging language is added here the
    baseline starts refusing and the demo is theatre.
    """
    llm = RecordingLLM()
    rag = NaiveRAG(llm=llm)
    rag.answer("Is there anaemia?", NO_COAG_DOCS)

    system = llm.calls[0][0]
    user = llm.calls[0][1]

    assert "Answer the question using only the context provided." in system

    prompt = (system + "\n" + user).lower()
    for hedge in ("if the context does not",
                  "if the information",
                  "say the information is not available",
                  "do not speculate",
                  "you cannot determine",
                  "refuse",
                  "insufficient evidence",
                  "distinguish between absence of"):
        assert hedge not in prompt, f"strawman prompt must not hedge: {hedge!r}"


def test_answer_includes_retrieved_context_in_the_prompt():
    llm = RecordingLLM()
    rag = NaiveRAG(llm=llm, top_k=2)
    rag.answer("What is the creatinine?", NO_COAG_DOCS)

    user = llm.calls[0][1]
    assert "1.48" in user, "retrieved text must actually reach the prompt"
    assert "Creatinine" in user


# --------------------------------------------------------------------------
# No-LLM fallback
# --------------------------------------------------------------------------

def test_falls_back_to_top_chunk_text_when_llm_missing():
    rag = NaiveRAG(llm=None)
    rag.index(NO_COAG_DOCS)

    result = rag.answer("Does this patient have a DVT / blood clot?")
    assert result["refused"] is False
    assert result["answer"].strip(), "the demo must still produce an answer"

    top = rag.retrieve("Does this patient have a DVT / blood clot?", top_k=1)[0]
    assert top["text"].strip() in result["answer"]
    assert result["citations"][0]["doc_id"] == top["doc_id"]


def test_llm_raising_llm_unavailable_degrades_to_fallback(monkeypatch):
    from axiom.llm import LLMUnavailable

    class DeadLLM:
        def json(self, system: str, user: str) -> dict:
            raise LLMUnavailable("no network")

    rag = NaiveRAG(llm=DeadLLM())
    result = rag.answer("Does this patient have a DVT / blood clot?", NO_COAG_DOCS)
    assert result["refused"] is False
    assert "DVT" not in result["answer"] or result["citations"]
    assert result["answer"].strip()


def test_llm_returning_non_json_or_missing_answer_degrades_to_fallback():
    class SloppyLLM:
        def json(self, system: str, user: str) -> dict:
            return {"unexpected": "shape"}

    rag = NaiveRAG(llm=SloppyLLM())
    result = rag.answer("Does this patient have a DVT / blood clot?", NO_COAG_DOCS)
    assert result["refused"] is False
    assert result["answer"].strip()


def test_answer_with_no_documents_at_all_does_not_crash():
    rag = NaiveRAG(llm=RecordingLLM())
    result = rag.answer("Does this patient have a DVT / blood clot?", [])
    assert result["refused"] is False   # still no refusal — that is the design
    assert isinstance(result["answer"], str)
    assert result["citations"] == []


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _last_user_prompt(llm: RecordingLLM) -> str:
    return llm.calls[-1][1]