"""
Fixture export — pipeline → one JSON file the UI renders.

    python3 -m axiom.export            →  axiom-ui/public/fixture.json

Design rule enforced here: the UI computes NO clinical numbers. Everything it
shows is either copied from this file or is a bar width derived from a number
in this file. If a value is worth showing, it gets exported here.

All data is synthetic. No real PHI. This file is safe to publish.
"""

from __future__ import annotations

import json
from typing import Any

from .bench import QUERIES, UNANSWERABLE, run_benchmark
from .clinical import PatientGenerator
from .graph import ClinicalGraph
from .pipeline import AxiomPipeline, IsotonicCalibrator

# the scripted demo path, in pitch order
SCENES = [
    {"id": "s1", "beat": "0:00", "screen": "Patient chart",
     "query": None, "narration": "Three findings warrant attention. Click the top one."},
    {"id": "s2", "beat": "0:10", "screen": "Evidence card",
     "query": "Is there any sign the kidney function is worsening?",
     "narration": "Every claim is cited. The citation resolves to the source node."},
    {"id": "s3", "beat": "0:25", "screen": "Interaction check",
     "query": "Is there any medication interaction in the current regimen?",
     "narration": "Structured retrieval over the temporal graph, not chunk similarity."},
    {"id": "s4", "beat": "0:40", "screen": "THE TURN — refusal",
     "query": "What is this patient's blood type?",
     "narration": "The record cannot support an answer. It says so, and routes it."},
    {"id": "s5", "beat": "0:55", "screen": "Benchmark & audit",
     "query": None, "narration": "Planted findings, measured honestly — including what we missed."},
]


def _pick_patient(seed: int = 20261007) -> dict[str, Any]:
    """Choose a patient that exercises every pitch beat.

    Requires all three high-signal planted findings — drug interaction, renal
    trend and allergy contraindication — plus a duplicate identity record so
    entity resolution is demonstrable, and >=4 encounters so the timeline has
    something to show.
    """
    g = PatientGenerator(seed)
    required = {"drug_drug_interaction", "deteriorating_lab_trend",
                "allergy_contraindication"}
    for _ in range(120):
        p = g.make_patient()
        types = {f["type"] for f in p["planted"]}
        if (required <= types and p.get("encounter_records")
                and len(p["encounters"]) >= 4):
            return p
    return g.make_patient()


def build_fixture(seed: int = 20261007) -> dict[str, Any]:
    cal = IsotonicCalibrator().fit(
        [(0.70, 1), (0.80, 1), (0.88, 1), (0.92, 1), (0.96, 1)])
    pipe = AxiomPipeline(cal)
    patient = _pick_patient(seed)
    g = ClinicalGraph(patient)

    # ---- graph for the timeline scrubber
    nodes = []
    for nid, n in g.nodes.items():
        nodes.append({
            "id": nid, "type": n["type"], "time": n["time"],
            "label": n.get("display") or n.get("drug") or n.get("substance")
                      or n.get("facility") or n.get("body_site") or n["type"],
            "value": n.get("value"),
            "unit": n.get("unit"),
        })
    edges = [{"from": a, "to": b, "type": t} for a, b, t in g.edges]

    # ---- scenes
    scenes = []
    for sc in SCENES:
        entry: dict[str, Any] = dict(sc)
        if sc["query"] is None:
            entry.update({"published": [], "abstained": [], "refused": False,
                          "audit_ref": None, "answer": None})
            scenes.append(entry)
            continue

        res = pipe.answer(patient, sc["query"])

        # attach the RAW source record behind every citation, so the UI never
        # has to derive it — click-through is data, not logic
        published = []
        for c in res["published"]:
            srcs = []
            for nid in c["cited_nodes"]:
                n = g.nodes.get(nid)
                if n:
                    srcs.append({"id": nid, "type": n["type"], "time": n["time"],
                                 "label": n.get("display") or n.get("drug")
                                         or n.get("substance") or n["type"],
                                 "value": n.get("value"), "unit": n.get("unit"),
                                 "raw": {k: v for k, v in n.items()
                                         if k in ("code", "display", "value",
                                                  "unit", "ref_low", "ref_high",
                                                  "drug", "dose", "substance",
                                                  "reaction", "severity",
                                                  "observed_at", "facility")}})
            published.append({**c, "source_records": srcs})

        abstained = []
        for a in res["abstained"]:
            abstained.append({
                "claim_id": a.get("claim_id") or (a.get("claim") or {}).get("claim_id"),
                "text": (a.get("claim") or {}).get("text"),
                "action": a["action"],
                "message": a.get("message"),
                "escalate_to": a.get("escalate_to"),
            })

        entry.update({
            "published": published,
            "abstained": abstained,
            "refused": res.get("refused", False),
            "refusal_reason": res.get("refusal_reason"),
            "audit_ref": res.get("audit_ref"),
            "plan": res.get("plan"),
            "evidence": res.get("evidence"),
        })
        scenes.append(entry)

    # ---- lab series for the trend chart (S2)
    trend = g.trend("2160-0")
    from .clinical import ANALYTES
    _, _, ref_lo, ref_hi, _ = ANALYTES["2160-0"]
    series = []
    if trend:
        for nid in trend["node_ids"]:
            n = g.nodes[nid]
            series.append({"id": nid, "t": n["time"][:10], "v": n["value"],
                           "unit": n["unit"]})

    bench = run_benchmark(n_patients=40, seed=seed)

    return {
        "meta": {
            "product": "AXIOM",
            "district": "DISTRICT 04 — AI-Native EMR for Intelligent Clinical Assistance",
            "thesis": "A clinical AI that always answers is unsafe. Ours refuses when "
                      "the evidence does not support an answer — and we measure how "
                      "often that happens.",
            "boundary": "AI ASSIST — NOT A DIAGNOSIS. Clinician decides.",
            "data_posture": "100% synthetic. No real PHI at any point.",
            "generated_from": "axiom.export — regenerate, never hand-edit",
        },
        "patient": {
            "demographics": patient["demographics"],
            "encounters": len(patient["encounters"]),
            "labs": len(patient["labs"]),
            "meds": len(patient["meds"]),
            "diagnoses": len(patient["diagnoses"]),
            "notes": len(patient["notes"]),
            "planted": patient["planted"],
        },
        "graph": {"nodes": nodes, "edges": edges,
                  "stats": g.stats(),
                  "interaction_edges": [
                      {"a": a, "b": b, "drug_a": da, "drug_b": db}
                      for a, b, da, db in g.interaction_edges],
                  "contraindications": [
                      {"allergy": a, "med": b,
                       "substance": g.nodes[a]["substance"],
                       "severity": g.nodes[a]["severity"],
                       "reaction": g.nodes[a]["reaction"]}
                      for a, b, t in g.edges
                      if t == "contraindicated_with"
                      and g.nodes[a]["type"] == "Allergy"],
                  },
        "trend": {"loinc": "2160-0", "display": "Creatinine",
                  "unit": "mg/dL", "ref_low": ref_lo, "ref_high": ref_hi,
                  "series": series,
                  "summary": ({k: trend[k] for k in
                               ("first", "last", "change_pct", "monotonicity",
                                "deteriorated")} if trend else None)},
        "scenes": scenes,
        "benchmark": {
            "detection_rate": bench["detection_rate"],
            "planted_total": bench["planted_total"],
            "planted_detected": bench["planted_detected"],
            "by_type": bench["by_type"],
            "unsupported_claim_rate": bench["unsupported_claim_rate"],
            "claims_examined": bench["claims_examined"],
            "citation_validity": bench["citation_validity"],
            "false_positive_rate": bench["false_positive_rate"],
            "clean_patients_examined": bench["clean_patients_examined"],
            "abstention_recall": bench["abstention_recall"],
            "negation_accuracy": bench["negation_accuracy"],
            "entity_resolution": bench["entity_resolution"],
            "robustness_sweep": bench["robustness_sweep"],
            "MISSED": bench["planted_total"] - bench["planted_detected"],
        },
        "limitations": bench["limitations"],
    }


if __name__ == "__main__":
    fx = build_fixture()
    out = "/workspace/axiom-ui/public/fixture.json"
    with open(out, "w") as f:
        json.dump(fx, f, indent=1)
    print("wrote", out)
    print("scenes:", len(fx["scenes"]),
          "| nodes:", len(fx["graph"]["nodes"]),
          "| edges:", len(fx["graph"]["edges"]))
    for s in fx["scenes"]:
        print(f"  {s['beat']}  {s['screen']:28s} "
              f"published={len(s['published'])} refused={s['refused']}")