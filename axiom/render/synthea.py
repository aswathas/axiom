"""
AXIOM — synthetic clinical document corpus.

Five patients, each with 4-8 documents spanning 12-24 months, rendered as PDFs in
the three Contract 3 layouts. The point is not to make pretty paper: it is to
give the upload path genuine PDFs with genuine clinical text underneath, so the
extractor is exercised on the formats it will actually meet.

Nothing is downloaded. Every record is generated in-process from a fixed seed,
so two runs produce byte-identical files.

WHAT IS REUSED FROM axiom.clinical
----------------------------------
This module does not define a second patient model. It imports the real thing:

    ANALYTES     LOINC -> (display, unit, ref_low, ref_high, higher_is_worse)
    CONDITIONS   ICD-10 -> (display, category)
    DRUGS        drug -> {rxnorm, class}
    INTERACTIONS (a, b, severity, rationale)
    PatientGenerator  the longitudinal record generator itself

The generator produces the encounters, notes, allergies, vitals and comorbid
structure; this module only decides which of those records become documents, and
overrides a handful of values to plant the three scenarios the demo asks about.

WHAT HAD TO BE ADDED
--------------------
Everything between a record and a page: the plan of which document carries
which facts, the analyst-free sequencing of creatinine over time, the second
result that disagrees with the first, and the manifest. None of that belongs in
axiom.clinical -- clinical.py models a record, this models a filing cabinet.

The conflict scenario is the clearest example of the split. A conflicting pair is
not a clinical fact about a patient, it is a defect in a source system, so
injecting one into the record generator would poison every other consumer of
PatientGenerator with data-quality noise.

SCENARIOS (fixed patient ids so demo fixtures can reference them)
    pat_001  renal_deterioration   creatinine rises monotonically
    pat_002  drug_interaction      warfarin + NSAID, bleeding risk
    pat_003  conflicting_results   two reports disagree on haemoglobin
    pat_004  --                    ordinary record
    pat_005  --                    ordinary record

All institutions are fictional. "Quest Diagnostics" is used as a specimen-lab
label because Contract 3 fixes it as the Layout A anchor text.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from axiom.clinical import (
    ANALYTES,
    CONDITIONS,
    DRUGS,
    INTERACTIONS,
    PatientGenerator,
)
from axiom.render.templates import (
    LAB_ADDRESS,
    LAB_NAME,
    HOSP_LAB_ADDRESS,
    HOSP_LAB_NAME,
    LabAnalyte,
    render_discharge_summary,
    render_lab_report,
    render_pharmacy_printout,
)

__all__ = [
    "CREATININE_LOINC",
    "HAEMOGLOBIN_LOINC",
    "INTERACTION_DRUGS",
    "NSAIDS",
    "RENAL_PATIENT_ID",
    "SCENARIOS",
    "build_corpus",
    "generate",
    "ROLE_LABEL",
    "scenario_of",
]

SEED = 20261007

CREATININE_LOINC = "2160-0"
EGFR_LOINC = "33914-3"
HAEMOGLOBIN_LOINC = "718-7"
WARFARIN = "warfarin"
NSAIDS = ("ibuprofen", "naproxen")
INTERACTION_DRUGS = (WARFARIN,) + NSAIDS

RENAL_PATIENT_ID = "pat_001"

SCENARIOS: dict[str, dict[str, Any]] = {
    "renal_deterioration": {"patient_id": RENAL_PATIENT_ID,
                            "label": "renal_deterioration"},
    "interaction": {"patient_id": "pat_002", "drugs": (WARFARIN, NSAIDS[0]),
                    "label": "drug_interaction"},
    "conflict": {"patient_id": "pat_003", "loinc": HAEMOGLOBIN_LOINC,
                 "label": "conflicting_results"},
}

# SCENARIOS keys name the scenario; labels name it as the demo talks about it.
ROLE_LABEL = {k: v["label"] for k, v in SCENARIOS.items()}

PATIENT_COUNT = 5

# The window the corpus spans. 18 months sits inside the 12-24 month brief.
CORPUS_START = datetime(2024, 10, 1)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _age_on(dob: str, when: str) -> int:
    born = datetime.strptime(dob, "%Y-%m-%d").date()
    at = datetime.strptime(when, "%Y-%m-%d").date()
    return at.year - born.year - ((at.month, at.day) < (born.month, born.day))


def _describe(patient: dict[str, Any], when: str) -> str:
    """'a 61-year-old female'. Derived from the record so the narrative cannot
    contradict the demographics printed in the header."""
    sex = {"F": "female", "M": "male"}.get(patient.get("sex", ""), "patient")
    return f"a {_age_on(patient['dob'], when)}-year-old {sex}"


def _pronoun(patient: dict[str, Any]) -> str:
    return {"F": "She", "M": "He"}.get(patient.get("sex", ""), "They")


def _us_date(iso: str) -> str:
    """Any ISO-ish date/datetime string -> "MM/DD/YYYY". Generators in this repo
    are not consistent about whether a date carries a time component."""
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%m/%d/%Y")


# ---------------------------------------------------------------------------
# corpus construction
# ---------------------------------------------------------------------------

def _analyte(loinc: str, value: float) -> LabAnalyte:
    """Build a printable row from the real LOINC metadata in axiom.clinical."""
    display, unit, lo, hi, _ = ANALYTES[loinc]
    if value > hi:
        flag = "H"
    elif value < lo:
        flag = "L"
    else:
        flag = ""
    return LabAnalyte(loinc, display, round(value, 3), unit, lo, hi, flag)


def _renal_series() -> list[tuple[datetime, float, float]]:
    """Five creatinine values, strictly increasing, with eGFR falling.

    Strictly monotonic, not "monotonic on average" -- a trend question that can
    be answered by a single pair of points is not a trend question.
    """
    return [
        (datetime(2025, 1, 15, 9, 42), 0.85, 78),
        (datetime(2025, 4, 15, 8, 15), 1.06, 63),
        (datetime(2025, 7, 15, 9, 5), 1.27, 52),
        (datetime(2025, 10, 15, 8, 50), 1.39, 46),
        (datetime(2026, 1, 15, 9, 30), 1.48, 41),
    ]


def _build_patient(pid: str, index: int, rng_seed: int) -> dict[str, Any]:
    """One patient in Contract 2 shape, with the documents that reveal it."""
    gen = PatientGenerator(rng_seed)
    raw = gen.make_patient(with_planted=False)
    demo = raw["demographics"]

    patient: dict[str, Any] = {
        "id": pid,
        "name": demo["name"],
        "dob": demo["dob"],
        "mrn": demo["mrn"],
        "sex": demo["sex"],
        "encounters": [],
        "diagnoses": [],
        "labs": [],
        "meds": [],
        "allergies": [],
        "imaging": [],
        "notes": [],
        "vitals": [],
    }

    role = next((k for k, s in SCENARIOS.items() if s["patient_id"] == pid), None)

    # ---- diagnoses: reuse the real ICD-10 subset
    codes = {
        "pat_001": ["N18.3", "I10", "E11.9"],
        "pat_002": ["I10", "E78.5", "J44.1"],
        "pat_003": ["E11.9", "E66.9"],
        "pat_004": ["K21.9", "M54.5"],
        "pat_005": ["F32.9", "E78.5"],
    }[pid]
    base = CORPUS_START + timedelta(days=30 + index * 11)
    for i, code in enumerate(codes):
        patient["diagnoses"].append({
            "id": f"{pid}-dx{i}", "code": code,
            "display": CONDITIONS[code][0], "category": CONDITIONS[code][1],
            "onset": _iso(base + timedelta(days=i * 40)),
            "source_doc_id": f"{pid}-doc0", "source_page": 1,
        })

    # ---- labs
    if role == "renal_deterioration":
        for dt, creat, egfr in _renal_series():
            patient["labs"].append({
                "id": f"{pid}-lab-creat-{_iso(dt)}", "loinc": CREATININE_LOINC,
                "value": creat, "unit": "mg/dL", "observed_at": _iso(dt),
                "ref_low": ANALYTES[CREATININE_LOINC][2],
                "ref_high": ANALYTES[CREATININE_LOINC][3],
            })
            patient["labs"].append({
                "id": f"{pid}-lab-egfr-{_iso(dt)}", "loinc": EGFR_LOINC,
                "value": egfr, "unit": ANALYTES[EGFR_LOINC][1], "observed_at": _iso(dt),
                "ref_low": ANALYTES[EGFR_LOINC][2], "ref_high": ANALYTES[EGFR_LOINC][3],
            })

        documents = []
        for n, (dt, creat, egfr) in enumerate(_renal_series()):
            documents.append({
                "name": f"lab_renal_{_iso(dt)}",
                "kind": "lab",
                "collected": dt.strftime("%m/%d/%Y %H:%M"),
                "accession": f"25{18473920 + n * 137}",
                "panel": "CHEMISTRY - RENAL PANEL",
                "analytes": [_analyte(CREATININE_LOINC, creat),
                             _analyte(EGFR_LOINC, egfr),
                             _analyte("2823-3", 4.8 + n * 0.11),
                             _analyte("2951-2", 139.0 - n * 1.4)],
            })
        documents.append({
            "name": "discharge_summary_2026-01-22",
            "kind": "discharge",
            "admit": "2026-01-15", "discharge": "2026-01-22",
            "attending": "Ramanathan, K.",
            "diagnoses": [(d["display"], d["code"]) for d in patient["diagnoses"]],
            "history": [
                f"Patient is {_describe(patient, '2026-01-15')} presenting with "
                "progressive fatigue and worsening exertional dyspnea. "
                f"{_pronoun(patient)} denies chest pain. {_pronoun(patient)} denies "
                "hematuria. Creatinine rose from 0.85 to 1.48 over the admission.",
                "Renal function declined steadily across five outpatient draws "
                "between January 2025 and January 2026. eGFR fell from 78 to 41 "
                "mL/min/1.73m2 over the same interval.",
            ],
            "meds": [("Metformin", "500 mg", "PO BID"),
                     ("Lisinopril", "10 mg", "PO daily"),
                     ("Furosemide", "40 mg", "PO daily")],
            "disposition": [
                "Follow up with Cardiology within 2 weeks. Renal nephrology referral "
                "placed. Repeat basic metabolic panel in 4 weeks.",
            ],
        })

    elif role == "interaction":
        patient["meds"] = [
            {"id": f"{pid}-med0", "name": WARFARIN, "rxnorm": DRUGS[WARFARIN]["rxnorm"],
             "dose": "5 mg", "frequency": "PO daily",
             "start": "2025-03-02", "end": None, "active": True},
            {"id": f"{pid}-med1", "name": NSAIDS[0], "rxnorm": DRUGS[NSAIDS[0]]["rxnorm"],
             "dose": "600 mg", "frequency": "PO TID PRN",
             "start": "2025-11-04", "end": None, "active": True},
            {"id": f"{pid}-med2", "name": "lisinopril", "rxnorm": DRUGS["lisinopril"]["rxnorm"],
             "dose": "20 mg", "frequency": "PO daily",
             "start": "2024-12-01", "end": None, "active": True},
            {"id": f"{pid}-med3", "name": "atorvastatin",
             "rxnorm": DRUGS["atorvastatin"]["rxnorm"],
             "dose": "40 mg", "frequency": "PO daily",
             "start": "2024-12-01", "end": None, "active": True},
        ]
        patient["labs"] = [
            {"id": f"{pid}-lab-inr-1", "loinc": "6301-6", "value": 2.1, "unit": "",
             "observed_at": "2025-11-06", "ref_low": 0.8, "ref_high": 1.2},
            {"id": f"{pid}-lab-inr-2", "loinc": "6301-6", "value": 3.4, "unit": "",
             "observed_at": "2026-01-08", "ref_low": 0.8, "ref_high": 1.2},
            {"id": f"{pid}-lab-hgb", "loinc": HAEMOGLOBIN_LOINC, "value": 9.2,
             "unit": "g/dL", "observed_at": "2026-01-08",
             "ref_low": 12.0, "ref_high": 17.5},
        ]

        documents = [
            {"name": "rx_history_2026-01-20", "kind": "pharmacy",
             "meds": [("Warfarin", "5 mg", "Take 1 tablet PO daily", "03/02/2025"),
                      ("Lisinopril", "20 mg", "Take 1 tablet PO daily", "12/01/2024"),
                      ("Atorvastatin", "40 mg", "Take 1 tablet PO daily", "12/01/2024"),
                      ("Ibuprofen", "600 mg", "Take 1 tablet PO TID PRN", "11/04/2025")]},
            {"name": "lab_inr_2026-01-08", "kind": "lab",
             "collected": "01/08/2026 07:55", "accession": "2529004117",
             "panel": "COAGULATION PANEL",
             "analytes": [_analyte("6301-6", 3.4), _analyte(HAEMOGLOBIN_LOINC, 9.2),
                          _analyte("777-3", 121)]},
            {"name": "lab_cbc_2025-11-06", "kind": "lab",
             "collected": "11/06/2025 08:10", "accession": "2526118840",
             "panel": "HEMATOLOGY - CBC",
             "analytes": [_analyte(HAEMOGLOBIN_LOINC, 11.8), _analyte("777-3", 168),
                          _analyte("6690-2", 7.4)]},
            {"name": "discharge_summary_2026-01-20", "kind": "discharge",
             "admit": "2026-01-14", "discharge": "2026-01-20",
             "attending": "Okonkwo, T.",
             "diagnoses": [(d["display"], d["code"]) for d in patient["diagnoses"]],
             "history": [
                 f"Patient is {_describe(patient, '2026-01-14')} admitted with melena "
                 f"and lightheaded dizziness. {_pronoun(patient)} denies hematuria. "
                 f"{_pronoun(patient)} denies chest pain.",
                 "INR has risen from 2.1 to 3.4 since ibuprofen was started on "
                 "11/04/2025 for knee pain. Haemoglobin fell from 11.8 to 9.2 g/dL.",
             ],
             "meds": [("Warfarin", "5 mg", "PO daily"),
                      ("Lisinopril", "20 mg", "PO daily"),
                      ("Atorvastatin", "40 mg", "PO daily")],
             "disposition": [
                 "Ibuprofen discontinued. Follow up with Cardiology within 2 weeks. "
                 "Hematology consult placed for anticoagulation management.",
             ]},
        ]

    elif role == "conflict":
        patient["meds"] = [
            {"id": f"{pid}-med0", "name": "metformin", "rxnorm": DRUGS["metformin"]["rxnorm"],
             "dose": "500 mg", "frequency": "PO BID", "start": "2024-11-10",
             "end": None, "active": True},
            {"id": f"{pid}-med1", "name": "glipizide", "rxnorm": DRUGS["glipizide"]["rxnorm"],
             "dose": "5 mg", "frequency": "PO daily", "start": "2025-05-19",
             "end": None, "active": True},
        ]
        patient["labs"] = [
            {"id": f"{pid}-lab-hgb-a", "loinc": HAEMOGLOBIN_LOINC, "value": 10.4,
             "unit": "g/dL", "observed_at": "2025-09-12",
             "ref_low": 12.0, "ref_high": 17.5},
            {"id": f"{pid}-lab-hgb-b", "loinc": HAEMOGLOBIN_LOINC, "value": 14.6,
             "unit": "g/dL", "observed_at": "2025-09-12",
             "ref_low": 12.0, "ref_high": 17.5},
        ]

        # Same analyte, same collection date, two different results, drawn from
        # two source systems. The discrepancy is the point; nothing reconciles it.
        documents = [
            {"name": "lab_hgb_quest_2025-09-12", "kind": "lab",
             "collected": "09/12/2025 07:20", "accession": "2522077614",
             "panel": "HEMATOLOGY - CBC",
             "analytes": [_analyte(HAEMOGLOBIN_LOINC, 10.4), _analyte("777-3", 244),
                          _analyte("6690-2", 6.1)]},
            {"name": "lab_hgb_stmargarets_2025-09-12", "kind": "lab",
             "collected": "09/12/2025 09:35", "accession": "2522079901",
             "lab_name": HOSP_LAB_NAME, "lab_address": HOSP_LAB_ADDRESS,
             "panel": "HEMATOLOGY - CBC",
             "analytes": [_analyte(HAEMOGLOBIN_LOINC, 14.6), _analyte("777-3", 233),
                          _analyte("6690-2", 6.4)]},
            {"name": "lab_a1c_2025-12-02", "kind": "lab",
             "collected": "12/02/2025 08:05", "accession": "2524881203",
             "panel": "DIABETES MONITORING",
             "analytes": [_analyte("4548-4", 8.1), _analyte("2345-7", 142)]},
            {"name": "discharge_summary_2026-02-10", "kind": "discharge",
             "admit": "2026-02-08", "discharge": "2026-02-10",
             "attending": "Vasquez, R.",
             "diagnoses": [(d["display"], d["code"]) for d in patient["diagnoses"]],
             "history": [
                 f"Patient is {_describe(patient, '2026-02-08')} admitted for elective "
                 f"hernia repair. {_pronoun(patient)} denies chest pain. "
                 f"{_pronoun(patient)} denies hematuria.",
                 "Two haemoglobin results from 09/12/2025 differ between the "
                 "outpatient laboratory and the hospital system; the outpatient "
                 "result of 10.4 g/dL is being treated as the correct value.",
             ],
             "meds": [("Metformin", "500 mg", "PO BID"),
                      ("Glipizide", "5 mg", "PO daily")],
             "disposition": [
                 "Discharged home. Reconcile duplicate haemoglobin results with "
                 "outpatient laboratory before the next visit.",
             ]},
        ]

    else:
        ordinary = raw["labs"][:4]
        for i, l in enumerate(ordinary):
            patient["labs"].append({
                "id": f"{pid}-lab{i}", "loinc": l["loinc"], "value": l["value"],
                "unit": l["unit"], "observed_at": _iso(base + timedelta(days=i * 95)),
                "ref_low": l["ref_low"], "ref_high": l["ref_high"],
            })
        for i, m in enumerate(raw["meds"][:3]):
            drug = m["drug"]
            patient["meds"].append({
                "id": f"{pid}-med{i}", "name": drug, "rxnorm": DRUGS[drug]["rxnorm"],
                "dose": m["dose"], "frequency": "PO daily",
                "start": _iso(base + timedelta(days=i * 30)), "end": None, "active": True,
            })
        patient["notes"] = [
            {"id": f"{pid}-note0", "observed_at": _iso(base),
             "stance": "ASSERTED", "text": raw["notes"][0]["text"] if raw["notes"] else ""},
        ]
        loincs = [l["loinc"] for l in patient["labs"]]
        documents = []
        for n in range(3):
            dt = base + timedelta(days=n * 130)
            analytes = [_analyte(l, patient["labs"][i]["value"])
                        for i, l in enumerate(loincs[:4])]
            documents.append({
                "name": f"lab_panel_{_iso(dt)}", "kind": "lab",
                "collected": dt.strftime("%m/%d/%Y %H:%M"),
                "accession": f"25{33000000 + index * 991 + n * 271}",
                "panel": "CHEMISTRY - BASIC METABOLIC PANEL",
                "analytes": analytes or [_analyte("2345-7", 96)],
            })
        documents.append({
            "name": f"rx_history_{_iso(base + timedelta(days=200))}", "kind": "pharmacy",
            "meds": [(m["name"].capitalize(), m["dose"], "Take 1 tablet PO daily",
                      _us_date(m["start"]))
                     for m in patient["meds"]] or [("Aspirin", "81 mg", "Take 1 tablet PO daily", "01/05/2025")],
        })

    # every patient gets a pharmacy record; documents stay within 4-8
    if not any(d["kind"] == "pharmacy" for d in documents):
        documents.append({
            "name": f"rx_history_{_iso(base + timedelta(days=210))}", "kind": "pharmacy",
            "meds": [(m["name"].capitalize(), m["dose"], "Take 1 tablet PO daily",
                      _us_date(m["start"]))
                     for m in patient["meds"]] or
                    [("Aspirin", "81 mg", "Take 1 tablet PO daily", "01/05/2025")],
        })

    for i, enc in enumerate(raw["encounters"][:6]):
        start = enc["start"]
        patient["encounters"].append({
            "id": enc["id"],
            "start": start[:10] if isinstance(start, str) else _iso(start),
            "type": enc["type"], "source_doc_id": f"{pid}-doc{i % len(documents)}",
            "source_page": 1,
        })

    patient["_documents"] = documents
    patient["_seed"] = rng_seed
    patient["scenario"] = role
    patient["index"] = index
    return patient


def build_corpus(patients: int = PATIENT_COUNT, seed: int = SEED) -> dict[str, Any]:
    """The full corpus in memory. Pure -- no files written, no clock read."""
    corpus_patients = []
    for i in range(patients):
        pid = f"pat_{i + 1:03d}"
        # per-patient derived seed keeps each patient's content stable even if
        # the cohort size changes
        p = _build_patient(pid, i, seed + i * 977)
        docs = p.pop("_documents")
        p.pop("_seed")
        # dataclasses are not JSON-serialisable; the manifest-free corpus should
        # still round-trip through json.dumps for the determinism test.
        for d in docs:
            # JSON-safe: the corpus is the serialisable description of the
            # corpus. _render_patient turns these back into LabAnalyte.
            d["analytes"] = [asdict(a) for a in d.get("analytes", [])]
        p["document_count"] = len(docs)
        p["documents"] = docs
        corpus_patients.append(p)

    return {
        "seed": seed,
        "patient_count": len(corpus_patients),
        "scenarios": {
            k: dict(v) for k, v in SCENARIOS.items()
            if any(p["id"] == v["patient_id"] for p in corpus_patients)
        },
        "patients": corpus_patients,
    }


def scenario_of(patient_id: str) -> str | None:
    for role, spec in SCENARIOS.items():
        if spec["patient_id"] == patient_id:
            return role
    return None


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _flag_for(loinc: str, value: float) -> str:
    return _analyte(loinc, value).flag


def _render_patient(out_dir: Path, patient: dict[str, Any]) -> list[str]:
    pid = patient["id"]
    pdir = out_dir / pid
    pdir.mkdir(parents=True, exist_ok=True)
    rels = []

    for doc in patient["documents"]:
        path = pdir / f"{doc['name']}.pdf"
        kind = doc["kind"]
        analytes = [LabAnalyte(**a) for a in doc.get("analytes", [])]
        if kind == "lab":
            render_lab_report(
                path, patient=patient, collected=doc["collected"],
                accession=doc["accession"],
                ordering_physician="Ramanathan, K.",
                panel=doc["panel"], analytes=analytes,
                lab_name=doc.get("lab_name", LAB_NAME),
                lab_address=doc.get("lab_address", LAB_ADDRESS),
            )
        elif kind == "discharge":
            render_discharge_summary(
                path, patient=patient, admit=doc["admit"], discharge=doc["discharge"],
                attending=doc["attending"], diagnoses=doc["diagnoses"],
                history=doc["history"], meds=doc["meds"],
                disposition=doc["disposition"],
            )
        elif kind == "pharmacy":
            render_pharmacy_printout(path, patient=patient, meds=doc["meds"])
        else:  # pragma: no cover - guarded by construction
            raise ValueError(f"unknown document kind {kind!r}")
        rels.append(f"{pid}/{doc['name']}.pdf")

    return sorted(rels)


def generate(out_dir: Path | str, patients: int = PATIENT_COUNT,
             seed: int = SEED) -> dict[str, Any]:
    """Render the whole corpus to `out_dir` and write manifest.json."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    corpus = build_corpus(patients=patients, seed=seed)
    manifest_patients = []

    for patient in corpus["patients"]:
        files = _render_patient(out, patient)
        manifest_patients.append({
            "id": patient["id"],
            "name": patient["name"],
            "dob": patient["dob"],
            "mrn": patient["mrn"],
            "sex": patient["sex"],
            "scenarios": [ROLE_LABEL[patient["scenario"]]] if patient["scenario"] else [],
            "files": files,
        })

    manifest = {
        "seed": corpus["seed"],
        "generator": "axiom.render.synthea",
        "patient_count": len(manifest_patients),
        "scenarios": {
            k: v["patient_id"] for k, v in corpus["scenarios"].items()
        },
        "patients": manifest_patients,
    }

    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m axiom.render.synthea",
        description="Render synthetic clinical documents as PDFs (deterministic, offline).",
    )
    ap.add_argument("--out", default="demo_docs/", help="output directory")
    ap.add_argument("--patients", type=int, default=PATIENT_COUNT)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)

    manifest = generate(args.out, patients=args.patients, seed=args.seed)
    total = sum(len(p["files"]) for p in manifest["patients"])
    print(f"Wrote {total} PDFs for {manifest['patient_count']} patients -> {args.out}")
    for p in manifest["patients"]:
        tag = f"  [{', '.join(p['scenarios'])}]" if p["scenarios"] else ""
        print(f"  {p['id']}  {p['name']:<20} {len(p['files'])} docs{tag}")
    print("manifest: " + str(Path(args.out) / "manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())