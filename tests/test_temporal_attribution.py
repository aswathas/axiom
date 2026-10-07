"""Lab/medication attribution to encounters.

ClinicalGraph gates `occurs_during` edges on a node carrying an `encounter_id`
(`graph.py:313`). Encounter extraction put the anchors in place but nothing
joined observations to them, so every edge was `precedes` and three of the four
temporal question classes stayed dead:

- "what changed since the last visit"   needs occurs_during
- "which diagnoses have no follow-up"    needs occurs_during
- "was this already known"               needs Allergy nodes we do not extract

This module's job is that join. Attribution is deliberately conservative: an
observation we cannot place is left unattributed rather than snapped to the
nearest plausible encounter, because a wrong attribution produces a confidently
wrong clinical claim.
"""

from __future__ import annotations

from axiom.graph import ClinicalGraph
from axiom.patient import build_patient


def _encounter(eid, start, end=None, kind="outpatient"):
    return {"id": eid, "start": start, "type": kind,
            "source_doc_id": "doc_a", "source_page": 1,
            "admit": start, "discharge": end}


class TestEncounterAttribution:
    def test_lab_inside_an_inpatient_stay_attaches_to_it(self):
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Inpatient stay",
                 timestamp="2026-01-15", meta={"discharge": "2026-01-22"},
                 source_doc_id="doc_a"),
            Fact(kind="lab", name="Creatinine", value=1.48, unit="mg/dL",
                 timestamp="2026-01-18", loinc="2160-0",
                 ref_low=0.6, ref_high=1.3, source_doc_id="doc_a"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_x"))

        lab = g.by_type["LabResult"][0]
        assert g.nodes[lab].get("encounter_id"), "lab must attach to its stay"
        assert any(e[2] == "occurs_during" for e in g.edges), (
            "occurs_during edges must exist once labs are attributed"
        )

    def test_outpatient_draw_attaches_to_that_days_visit(self):
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Lab draw",
                 timestamp="2025-04-15", source_doc_id="doc_a"),
            Fact(kind="lab", name="Potassium", value=5.2, unit="mmol/L",
                 timestamp="2025-04-15", loinc="2823-3",
                 ref_low=3.5, ref_high=5.1, source_doc_id="doc_a"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_y"))
        lab = g.by_type["LabResult"][0]
        enc = g.nodes[g.by_type["Encounter"][0]]
        assert g.nodes[lab]["encounter_id"] == enc["id"]

    def test_lab_before_any_encounter_is_left_unattributed(self):
        """We do not snap an orphan observation forward to a later visit.

        That would manufacture a clinical claim — 'this value was found during
        the January admission' — out of nothing.
        """
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Later visit",
                 timestamp="2025-06-01", source_doc_id="doc_a"),
            Fact(kind="lab", name="Sodium", value=140.0, unit="mmol/L",
                 timestamp="2025-01-01", loinc="2951-2",
                 ref_low=135.0, ref_high=145.0, source_doc_id="doc_a"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_z"))
        lab = g.by_type["LabResult"][0]
        assert "encounter_id" not in g.nodes[lab], (
            "an observation predating every encounter must not be attributed"
        )

    def test_lab_after_the_last_encounter_is_left_unattributed(self):
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Earlier visit",
                 timestamp="2025-01-15", source_doc_id="doc_a"),
            Fact(kind="lab", name="Sodium", value=140.0, unit="mmol/L",
                 timestamp="2025-09-01", loinc="2951-2",
                 ref_low=135.0, ref_high=145.0, source_doc_id="doc_a"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_w"))
        lab = g.by_type["LabResult"][0]
        assert "encounter_id" not in g.nodes[lab]

    def test_lab_with_no_timestamp_is_never_attributed(self):
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Visit",
                 timestamp="2025-01-15", source_doc_id="doc_a"),
            Fact(kind="lab", name="Creatinine", value=1.4, unit="mg/dL",
                 timestamp=None, loinc="2160-0", ref_low=0.6, ref_high=1.3,
                 source_doc_id="doc_a"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_v"))
        lab = g.by_type["LabResult"][0]
        assert "encounter_id" not in g.nodes[lab]

    def test_inpatient_stay_takes_precedence_over_a_same_day_draw(self):
        """An admission window is a stronger claim than a same-day outpatient
        encounter, and must win so the observation lands on the real stay."""
        from axiom.facts import Fact
        facts = [
            Fact(kind="encounter", name="Lab draw",
                 timestamp="2026-01-16", source_doc_id="doc_a"),
            Fact(kind="encounter", name="Admission",
                 timestamp="2026-01-15",
                 meta={"discharge": "2026-01-22"}, source_doc_id="doc_b"),
            Fact(kind="lab", name="Creatinine", value=1.48, unit="mg/dL",
                 timestamp="2026-01-16", loinc="2160-0",
                 ref_low=0.6, ref_high=1.3, source_doc_id="doc_b"),
        ]
        g = ClinicalGraph(build_patient(facts, pid="pat_u"))
        lab = g.by_type["LabResult"][0]
        attached = g.nodes[lab]["encounter_id"]
        # Identify the stay by its discharge window rather than by position —
        # by_type is insertion-ordered and carries no clinical ordering.
        stay_ids = {g.nodes[e]["id"] for e in g.by_type["Encounter"]
                    if g.nodes[e].get("discharge")}
        assert attached in stay_ids, (
            "an admission window must win over a same-day outpatient draw"
        )