"""Silence is not an answer.

Two defects, both found by running the real ingested chart rather than
fixtures, and both of the same species: the system produced no claim and let
that read as "nothing to report".

1. `new_since_last_visit` compared a string timestamp against None. Prose
   extraction can yield undated facts — "Creatinine rose from 0.85 to 1.48"
   states no dates — and the TypeError surfaced as a spurious refusal on a
   question the record genuinely supports.

2. `/api/ask` returned `refused: false` with an empty `published` list. To a
   clinician that is silence, and silence reads as a normal result. An empty
   answer must be a refusal, never a success with nothing in it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import api.main as main_module
    monkeypatch.setattr(main_module, "_DB_PATH", str(tmp_path / "silence.db"))
    from api.main import app
    with TestClient(app) as c:
        yield c


def _ingest_pat_001(client):
    import pathlib
    from axiom.render.synthea import generate
    docs = pathlib.Path("demo_docs")
    if not docs.exists():
        generate(out_dir=str(docs), patients=5)
    for d in sorted((docs / "pat_001").glob("*.pdf")):
        client.post("/api/upload",
                    files={"file": (d.name, d.read_bytes(), "application/pdf")},
                    params={"patient_id": "pat_001"})
    return "pat_001"


class TestUndatedNodesDoNotCrashTemporalQueries:
    def test_new_since_last_visit_tolerates_undated_nodes(self):
        from axiom.graph import ClinicalGraph
        from axiom.patient import build_patient
        from axiom.facts import Fact

        facts = [
            Fact(kind="encounter", name="Visit A", timestamp="2026-01-15",
                 source_doc_id="d"),
            Fact(kind="encounter", name="Visit B", timestamp="2026-01-22",
                 source_doc_id="d"),
            # A prose-extracted lab with no stated date.
            Fact(kind="lab", name="Creatinine", value=1.48, unit="mg/dL",
                 timestamp=None, loinc="2160-0", ref_low=0.6, ref_high=1.3,
                 source_doc_id="d", extractor="llm"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_t"))
        out = g.new_since_last_visit()          # must not raise
        assert isinstance(out, list)

    def test_the_undated_lab_is_still_in_the_graph(self):
        """Skipping a node from a temporal query is not the same as dropping it.
        The observation remains available; it simply cannot be placed on a
        timeline."""
        from axiom.graph import ClinicalGraph
        from axiom.patient import build_patient
        from axiom.facts import Fact

        facts = [
            Fact(kind="lab", name="Creatinine", value=1.48, unit="mg/dL",
                 timestamp=None, loinc="2160-0", ref_low=0.6, ref_high=1.3,
                 source_doc_id="d", extractor="llm"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_u"))
        assert g.by_type["LabResult"], "an undated observation must not vanish"


class TestEmptyAnswerIsARefusal:
    def test_empty_published_list_becomes_a_refusal(self, client):
        pid = _ingest_pat_001(client)
        r = client.post("/api/ask", json={
            "patient_id": pid,
            "query": "Does this patient have a pulmonary embolism?",
        })
        assert r.status_code == 200
        body = r.json()
        assert not body.get("published"), "fixture assumption: nothing published"
        assert body["refused"] is True, (
            "an answer with no claims must be a refusal, not a silent success"
        )
        assert body["status"] == "refused"
        assert body.get("refusal_reason")

    def test_a_real_refusal_is_unchanged(self, client):
        pid = _ingest_pat_001(client)
        r = client.post("/api/ask", json={
            "patient_id": pid,
            "query": "Does this patient have a DVT / blood clot?",
        })
        body = r.json()
        assert body["refused"] is True
        assert "blood clot" not in str(body.get("refusal_reason", "")).lower()

    def test_a_genuine_answer_still_returns_claims(self, client):
        pid = _ingest_pat_001(client)
        r = client.post("/api/ask", json={
            "patient_id": pid,
            "query": "Is the kidney function actually deteriorating?",
        })
        body = r.json()
        assert body["published"], "a supported question must still be answered"
        assert body["refused"] is False