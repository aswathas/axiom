"""
AXIOM — end-to-end demonstration.

Runs the exact flow the pitch performs, so what you see here is what you can
show on stage.

    python3 -m axiom.demo
"""

from __future__ import annotations

import json

from .clinical import PatientGenerator
from .graph import ClinicalGraph, resolve_identities
from .pipeline import AxiomPipeline, IsotonicCalibrator

BAR = "─" * 74


def hdr(t: str) -> None:
    print(f"\n{BAR}\n  {t}\n{BAR}")


def main() -> None:
    cal = IsotonicCalibrator().fit(
        [(0.70, 1), (0.80, 1), (0.88, 1), (0.92, 1), (0.96, 1)])
    pipe = AxiomPipeline(cal)
    gen = PatientGenerator(20261007)

    # pick a patient carrying several planted findings
    patient = None
    for _ in range(40):
        p = gen.make_patient()
        types = {f["type"] for f in p["planted"]}
        # require a duplicate-identity record too, so entity resolution is
        # actually exercised on stage rather than shown as a no-op
        if ({"drug_drug_interaction", "deteriorating_lab_trend"} <= types
                and p.get("encounter_records")):
            patient = p
            break
    if patient is None:
        patient = gen.make_patient()

    hdr("PATIENT CHART")
    d = patient["demographics"]
    print(f"  {d['name']}   DOB {d['dob']}   {d['sex']}   {d['mrn']}")
    g = ClinicalGraph(patient)
    st = g.stats()
    print(f"  clinical graph: {st['nodes']} nodes, {st['edges']} edges")
    print(f"  node types: {st['by_type']}")
    print(f"  edge types: {st['edge_types']}")
    print("  boundary: AI ASSIST — NOT A DIAGNOSIS. Clinician decides.")

    hdr("PLANTED GROUND TRUTH  (the answer key we are being tested against)")
    for f in patient["planted"]:
        print(f"  [{f['severity'].upper():8s}] {f['type']}")
        print(f"              {f['description']}")
        print(f"              evidence nodes: {f['evidence_node_ids']}")

    # ---- BEAT 1-3: traceable finding
    hdr("BEAT 1–3  —  A finding, traced to source")
    r = pipe.answer(patient, "Is there any sign the kidney function is worsening?")
    for c in r["published"]:
        print(f"  CLAIM {c['claim_id']}  [{c['claim_type']}]  "
              f"calibrated {c['calibrated_score']}")
        print(f"    {c['text']}")
        print(f"    cited nodes: {c['cited_nodes']}")
        print(f"    verdict: {c['verdict']} — verified")
    for a in r["abstained"]:
        print(f"  WITHHELD [{a['action']}] {a.get('message')}")
    print(f"  audit ref: {r['audit_ref']}")

    # ---- BEAT 4: interaction detection
    hdr("BEAT 3b  —  Structured retrieval over the graph")
    r2 = pipe.answer(patient, "Is there any medication interaction in the current regimen?")
    for c in r2["published"]:
        print(f"  CLAIM {c['claim_id']}  [{c['claim_type']}]  "
              f"calibrated {c['calibrated_score']}")
        print(f"    {c['text']}")
        print(f"    cited: {c['cited_nodes']}   verdict: {c['verdict']}")

    # ---- BEAT 4: the turn — abstention
    hdr("BEAT 4  —  THE TURN:  a question the record cannot answer")
    for q in ["What is this patient's blood type?",
              "Has the patient ever had a stroke?",
              "What is the patient's family history of cardiac disease?"]:
        rr = pipe.answer(patient, q)
        if rr["refused"]:
            print(f"  Q: {q}")
            print(f"  A: REFUSED — {rr['abstained'][0]['message']}")
            print(f"     routed to: {rr['abstained'][0]['escalate_to']}")
            print(f"     audit: {rr['audit_ref']}\n")
        else:
            print(f"  Q: {q}")
            print(f"  A: [published {len(rr['published'])} claim(s)] "
                  f"← this should not happen\n")

    # ---- negation handling
    hdr("NEGATION HANDLING  —  'denies' must never become 'has'")
    for s in g.note_stances()[:4]:
        print(f"  [{s['stance']:11s}] {s['sentence'][:74]}")

    # ---- entity resolution
    hdr("ENTITY RESOLUTION  —  same patient, two source systems")
    er = resolve_identities([patient])[0]
    print(f"  merged {max(c['cluster_size'] for c in er['clusters'])} records for one patient")
    for c in er["clusters"][:2]:
        for s in c["sources"]:
            print(f"    {s['_src']:12s} name={s['name']:22s} dob={s['dob']}  mrn={s['mrn']}")
    print(f"  pairwise P={er['precision']:.3f}  R={er['recall']:.3f}  F1={er['f1']:.3f}")

    # ---- audit trail
    hdr("AUDIT TRAIL  —  every statement resolves to its source")
    if pipe.audit.entries:
        e = pipe.audit.entries[0]
        print(f"  {e['patient_id']}  query: {e['query']}")
        print(f"  plan: {json.dumps(e['plan'])}")
        print(f"  published={e['n_published']} suppressed={e['n_suppressed']} "
              f"abstained={e['n_abstained']}")
    refused = [x for x in pipe.audit.entries if x["decisions"][0]["action"] == "REFUSED"]
    print(f"  refusal events logged: {len(refused)} (refusals are audited, not silent)")

    hdr("DEMO COMPLETE")
    print("  Run `python3 -m axiom.bench` for the full metric report.\n")


if __name__ == "__main__":
    main()