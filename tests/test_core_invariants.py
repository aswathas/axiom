"""Regression tests for two defects found during integration.

Both were reported by agents building against the frozen contracts and were
confirmed before fixing. They share a theme: the type of failure this project
exists to prevent — a plausible-looking record that is quietly wrong.
"""

from __future__ import annotations

from axiom.graph import ClinicalGraph
from axiom.patient import build_patient


def _patient_with_encounter() -> dict:
    from axiom.facts import Fact
    f = Fact(
        kind="note_stance",
        name="Patient presents for renal follow-up.",
        timestamp="2025-01-15",
        source_doc_id="doc_a",
        extractor="regex",
    )
    return build_patient([f], pid="pat_001", name="Bergman, L.")


class TestNodeTypeIsStructural:
    """graph.py `_add` spread payload *after* the structural keys, so a
    payload carrying its own `type` silently overwrote the node type.

    Encounter payloads carry `type: "outpatient"` / "inpatient" (the visit
    kind), so every Encounter node reported `type == "outpatient"` instead of
    `"Encounter"`. `by_type` stayed correct because it indexes before the
    spread, which is why the pipeline never noticed — but any consumer
    filtering `nodes` by `type` misses every encounter in the chart.
    """

    def test_encounter_node_reports_its_structural_type(self):
        p = _patient_with_encounter()
        p["encounters"].append({
            "id": "enc_0001", "start": "2025-01-15",
            "type": "inpatient", "source_doc_id": "doc_a", "source_page": 1,
        })
        g = ClinicalGraph(p)

        assert "enc_0001" in g.nodes, "encounter should have become a node"
        assert g.nodes["enc_0001"]["type"] == "Encounter", (
            "a node's structural type must not be overwritable by payload data"
        )
        assert g.nodes["enc_0001"]["type"] != "inpatient"

    def test_visit_kind_is_still_reachable(self):
        """The clinical field the payload carried must survive, under a name
        that cannot collide with the structural type."""
        p = _patient_with_encounter()
        p["encounters"].append({
            "id": "enc_0002", "start": "2025-01-15",
            "type": "inpatient", "source_doc_id": "doc_a", "source_page": 1,
        })
        g = ClinicalGraph(p)

        assert g.nodes["enc_0002"].get("encounter_type") == "inpatient", (
            "visit kind must remain queryable after the collision is resolved"
        )

    def test_by_type_index_is_unaffected(self):
        p = _patient_with_encounter()
        p["encounters"].append({
            "id": "enc_0003", "start": "2025-01-15",
            "type": "inpatient", "source_doc_id": "doc_a", "source_page": 1,
        })
        g = ClinicalGraph(p)
        assert g.nodes["enc_0003"]["type"] == "Encounter"
        assert "enc_0003" in g.by_type["Encounter"]


class TestCanonicalPatientId:
    """Contract 2 originally specified the key `id`, but axiom.clinical emits
    `patient_id` (clinical.py:256) and pipeline.py indexes `patient["patient_id"]`
    in three places. The engine is canonical; the contract was wrong.
    """

    def test_build_patient_emits_patient_id(self):
        p = build_patient([], pid="pat_042")
        assert p["patient_id"] == "pat_042"
        assert "id" not in p, "the ambiguous alias should not be emitted at all"

    def test_pipeline_can_consume_a_built_patient(self):
        from axiom.pipeline import AxiomPipeline
        p = build_patient([], pid="pat_043", name="Test, P.")
        result = AxiomPipeline().answer(p, "What changed since the last visit?")

        assert result["patient_id"] == "pat_043", (
            "an empty chart should refuse, but it must refuse with the "
            "patient's own identity attached"
        )