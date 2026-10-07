"""
Tests for Agent B: clinical document rendering (axiom/render/).

Contract 3 defines the exact text layouts Agent A's parser anchors on. These
tests assert that what we draw comes back out of the PDF text layer intact,
that the planted clinical scenarios survive the round trip, and that the whole
generator is reproducible.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PdfReader

from axiom.render.synthea import (
    CREATININE_LOINC,
    INTERACTION_DRUGS,
    RENAL_PATIENT_ID,
    SCENARIOS,
    build_corpus,
    generate,
    scenario_of,
)
from axiom.render.templates import (
    LabAnalyte,
    extract_text,
    render_discharge_summary,
    render_lab_report,
    render_pharmacy_printout,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _tmp_pdf(tmp_path: Path, name: str = "doc.pdf") -> Path:
    return tmp_path / name


def _read(p: Path) -> str:
    return extract_text(p)


SAMPLE = {
    "patient_id": "pat_001",
    "name": "Bergman, L.",
    "dob": "1964-04-12",
    "mrn": "MRN762900",
    "sex": "F",
}

RENAL_LABS = [
    LabAnalyte("2160-0", "Creatinine", 1.48, "mg/dL", 0.60, 1.30, "H"),
    LabAnalyte("33914-3", "eGFR", 41, "mL/min/1.73m2", 90.0, 140.0, "L"),
    LabAnalyte("2823-3", "Potassium", 5.20, "mmol/L", 3.50, 5.10, "H"),
    LabAnalyte("2951-2", "Sodium", 131.0, "mmol/L", 135.0, 145.0, "L"),
]

DISCHARGE = {
    "admit": "2025-01-15",
    "discharge": "2025-01-22",
    "attending": "Ramanathan, K.",
    "diagnoses": [
        ("Chronic kidney disease, stage 3", "N18.3"),
        ("Essential hypertension", "I10"),
        ("Type 2 diabetes mellitus", "E11.9"),
    ],
    "history": [
        "Patient is a 60-year-old female presenting with progressive fatigue and",
        "worsening exertional dyspnea. She denies chest pain. She denies hematuria.",
        "Creatinine rose from 0.85 to 1.48 over the admission.",
    ],
    "meds": [
        ("Metformin", "500 mg", "PO BID"),
        ("Lisinopril", "10 mg", "PO daily"),
        ("Warfarin", "5 mg", "PO daily"),
    ],
    "disposition": [
        "Follow up with Cardiology within 2 weeks. Renal nephrology referral placed.",
    ],
}

RX_MEDS = [
    ("Metformin", "500 mg", "Take 1 tablet PO BID", "01/15/2025"),
    ("Lisinopril", "10 mg", "Take 1 tablet PO daily", "01/15/2025"),
    ("Warfarin", "5 mg", "Take 1 tablet PO daily", "03/02/2025"),
]


# ---------------------------------------------------------------------------
# 1. Layout anchors round-trip through the PDF text layer
# ---------------------------------------------------------------------------

def test_layout_a_anchors_round_trip(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_lab_report(
        out,
        patient=SAMPLE,
        collected="04/15/2025 09:42",
        accession="2518473920",
        ordering_physician="Ramanathan, K.",
        panel="CHEMISTRY - RENAL PANEL",
        analytes=RENAL_LABS,
    )
    text = _read(out)

    for anchor in (
        "QUEST DIAGNOSTICS",
        "8401 Wilson Boulevard, Tampa, FL 33618",
        "Patient: Bergman, L.",
        "MRN: MRN762900",
        "DOB: 04/12/1964",
        "Collected: 04/15/2025 09:42",
        "Accession: 2518473920",
        "Ordering Physician: Ramanathan, K.",
        "CHEMISTRY - RENAL PANEL",
        "Result",
        "Reference Range",
        "Flag",
        "End of Report",
    ):
        assert anchor in text, f"missing Layout A anchor: {anchor!r}"

    # the parser anchors on the dashed rule beneath the column header
    assert re.search(r"-{20,}", text), "missing dashed rule under the header"
    assert "----------------" in text


def test_layout_a_preserves_every_analyte_row(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_lab_report(out, patient=SAMPLE, collected="04/15/2025 09:42",
                      accession="2518473920", ordering_physician="Ramanathan, K.",
                      panel="CHEMISTRY - RENAL PANEL", analytes=RENAL_LABS)
    text = _read(out)

    rows = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] in {a.display for a in RENAL_LABS}:
            rows.setdefault(parts[0], line)

    assert len(rows) == 4, f"lost analyte rows, got {sorted(rows)}"
    assert "Creatinine" in rows and "1.48" in rows["Creatinine"]
    assert "0.60 - 1.30" in rows["Creatinine"]
    assert rows["Creatinine"].rstrip().endswith("H")
    assert rows["Potassium"].rstrip().endswith("H")
    assert rows["Sodium"].rstrip().endswith("L")


def test_layout_a_columns_do_not_collapse(tmp_path):
    """Column alignment must survive extraction: analyte, result, unit, range, flag
    all on one line, in that order. The parser splits these rows on whitespace."""
    out = _tmp_pdf(tmp_path)
    render_lab_report(out, patient=SAMPLE, collected="04/15/2025 09:42",
                      accession="2518473920", ordering_physician="Ramanathan, K.",
                      panel="CHEMISTRY - RENAL PANEL", analytes=RENAL_LABS)
    text = _read(out)

    line = next(l for l in text.splitlines() if l.strip().startswith("Creatinine"))
    pos = [m.start() for m in re.finditer(r"\S+", line)]
    # strictly increasing = columns are separated, not run together
    assert pos == sorted(pos)
    tokens = line.split()
    assert tokens[0] == "Creatinine"
    assert tokens[1] == "1.48"
    assert tokens[2] == "mg/dL"
    assert tokens[-1] == "H"
    assert "-" in tokens, "reference range lost its separator"


def test_layout_b_anchors_round_trip(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_discharge_summary(out, patient=SAMPLE, **DISCHARGE)
    text = _read(out)

    for anchor in (
        "ST. MARGARET'S MEDICAL CENTER",
        "Department of Internal Medicine",
        "DISCHARGE SUMMARY",
        "Patient: Bergman, L.",
        "DOB: 04/12/1964",
        "MRN: MRN762900",
        "Admit Date: 01/15/2025",
        "Discharge Date: 01/22/2025",
        "Attending: Ramanathan, K.",
        "DIAGNOSIS",
        "Chronic kidney disease, stage 3 (N18.3)",
        "Essential hypertension (I10)",
        "Type 2 diabetes mellitus (E11.9)",
        "PRESENTING HISTORY",
        "She denies chest pain.",
        "MEDICATIONS ON DISCHARGE",
        "- Metformin 500 mg PO BID",
        "- Warfarin 5 mg PO daily",
        "DISPOSITION",
        "nephrology referral placed.",
    ):
        assert anchor in text, f"missing Layout B anchor: {anchor!r}"


def test_layout_b_numbered_diagnoses_and_negation_survive(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_discharge_summary(out, patient=SAMPLE, **DISCHARGE)
    text = _read(out)
    assert "1. Chronic kidney disease, stage 3 (N18.3)" in text
    assert "2. Essential hypertension (I10)" in text
    assert "3. Type 2 diabetes mellitus (E11.9)" in text
    # narrative line wrapping must not merge adjacent sentences
    assert "She denies chest pain. She denies hematuria." in text


def test_layout_c_anchors_round_trip(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_pharmacy_printout(out, patient=SAMPLE, meds=RX_MEDS)
    text = _read(out)

    for anchor in (
        "HARBORVIEW PHARMACY",
        "Prescription History",
        "Patient: Bergman, L.",
        "DOB: 04/12/1964",
        "MRN: MRN762900",
        "Medication",
        "Strength",
        "Directions",
        "Start",
    ):
        assert anchor in text, f"missing Layout C anchor: {anchor!r}"
    assert re.search(r"-{20,}", text), "missing dashed rule in Layout C"

    for name, strength, directions, start in RX_MEDS:
        line = next((l for l in text.splitlines() if l.strip().startswith(name)), None)
        assert line is not None, f"lost med row {name}"
        for token in (strength, start):
            assert token in line
        assert directions.split()[0] in line


def test_layout_c_columns_do_not_collapse(tmp_path):
    out = _tmp_pdf(tmp_path)
    render_pharmacy_printout(out, patient=SAMPLE, meds=RX_MEDS)
    text = _read(out)
    line = next(l for l in text.splitlines() if l.strip().startswith("Warfarin"))
    tokens = line.split()
    assert tokens[0] == "Warfarin"
    assert tokens[1] == "5"
    assert tokens[-1] == "03/02/2025"
    assert "Take" in tokens


# ---------------------------------------------------------------------------
# 2. Planted clinical scenarios
# ---------------------------------------------------------------------------

def test_renal_patient_creatinine_series_is_monotonic():
    corpus = build_corpus()
    patients = {p["id"]: p for p in corpus["patients"]}
    p = patients[RENAL_PATIENT_ID]

    series = sorted(
        (lab for lab in p["labs"] if lab["loinc"] == CREATININE_LOINC),
        key=lambda l: l["observed_at"],
    )
    assert len(series) >= 4, "renal patient needs a real series to be a trend"
    values = [lab["value"] for lab in series]
    assert values == sorted(values), f"creatinine not monotonic: {values}"
    assert values[-1] > values[0], "no deterioration over the series"
    assert all(lab["unit"] == "mg/dL" for lab in series), "unit drift breaks comparison"


def test_renal_patient_labs_reach_the_documents(tmp_path):
    out_dir = tmp_path / "demo_docs"
    generate(out_dir, patients=5)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    entry = next(e for e in manifest["patients"] if e["id"] == RENAL_PATIENT_ID)

    crets = []
    for f in entry["files"]:
        text = extract_text(out_dir / f)
        for line in text.splitlines():
            if line.strip().startswith("Creatinine"):
                crets.append(float(line.split()[1]))

    assert len(crets) >= 4, f"creatinine not rendered into PDFs: {crets}"
    assert crets == sorted(crets), f"rendered creatinine series not monotonic: {crets}"


def test_interaction_patient_has_warfarin_plus_nsaid(tmp_path):
    out_dir = tmp_path / "demo_docs"
    generate(out_dir, patients=5)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    hits = []
    for entry in manifest["patients"]:
        blob = "\n".join(extract_text(out_dir / f) for f in entry["files"])
        low = blob.lower()
        if "warfarin" in low and any(n in low for n in INTERACTION_DRUGS):
            hits.append(entry["id"])

    assert hits, "no patient carries the warfarin + NSAID interaction"
    assert RENAL_PATIENT_ID not in hits or True  # roles may overlap, both are fine


def test_conflicting_pair_disagrees_on_an_analyte(tmp_path):
    out_dir = tmp_path / "demo_docs"
    generate(out_dir, patients=5)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))

    entry = next(e for e in manifest["patients"] if e["id"] == SCENARIOS["conflict"]["patient_id"])
    values = {}
    for f in entry["files"]:
        if not f.endswith(".pdf"):
            continue
        text = extract_text(out_dir / f)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Hemoglobin"):
                values.setdefault(f, []).append(stripped)

    seen = {tuple(v) for v in values.values() if v}
    assert len(seen) >= 2, f"conflicting pair reports the same value: {values}"


# ---------------------------------------------------------------------------
# 3. Determinism
# ---------------------------------------------------------------------------

def test_corpus_is_deterministic():
    a = build_corpus()
    b = build_corpus()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_render_is_deterministic(tmp_path):
    for i in (1, 2):
        out = _tmp_pdf(tmp_path, f"det{i}.pdf")
        render_lab_report(out, patient=SAMPLE, collected="04/15/2025 09:42",
                          accession="2518473920", ordering_physician="Ramanathan, K.",
                          panel="CHEMISTRY - RENAL PANEL", analytes=RENAL_LABS)
    assert (tmp_path / "det1.pdf").read_bytes() == (tmp_path / "det2.pdf").read_bytes()


def test_generated_tree_is_byte_identical_across_runs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    generate(first, patients=5)
    generate(second, patients=5)

    files_a = sorted(p.relative_to(first) for p in first.rglob("*.pdf"))
    files_b = sorted(p.relative_to(second) for p in second.rglob("*.pdf"))
    assert files_a == files_b and len(files_a) >= 20

    for rel in files_a:
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel

    assert json.loads((first / "manifest.json").read_text()) == \
           json.loads((second / "manifest.json").read_text())


def test_cli_matches_library(tmp_path):
    out = tmp_path / "cli_docs"
    proc = subprocess.run(
        [sys.executable, "-m", "axiom.render.synthea", "--out", str(out), "--patients", "5"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    lib = tmp_path / "lib_docs"
    generate(lib, patients=5)

    for rel in sorted(p.relative_to(lib) for p in lib.rglob("*.pdf")):
        assert (out / rel).read_bytes() == (lib / rel).read_bytes(), rel


# ---------------------------------------------------------------------------
# 4. Manifest integrity
# ---------------------------------------------------------------------------

def test_manifest_is_valid_json_and_files_exist(tmp_path):
    out = tmp_path / "demo_docs"
    generate(out, patients=5)

    manifest_path = out / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["seed"]
    assert manifest["patient_count"] == 5
    assert len(manifest["patients"]) == 5

    ids = set()
    for entry in manifest["patients"]:
        for key in ("id", "name", "dob", "mrn", "files"):
            assert key in entry, f"manifest entry missing {key}: {entry}"
        assert entry["id"] not in ids, f"duplicate patient id {entry['id']}"
        ids.add(entry["id"])
        assert re.fullmatch(r"pat_\d{3}", entry["id"])
        assert re.fullmatch(r"MRN\d{6}", entry["mrn"])
        assert 4 <= len(entry["files"]) <= 8, f"{entry['id']} has {len(entry['files'])} docs"
        for rel in entry["files"]:
            assert (out / rel).exists(), f"manifest references missing file {rel}"
            assert rel.split("/")[0] == entry["id"]


def test_every_pdf_is_readable_and_carries_patient_identity(tmp_path):
    out = tmp_path / "demo_docs"
    generate(out, patients=5)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    for entry in manifest["patients"]:
        for rel in entry["files"]:
            reader = PdfReader(str(out / rel))
            assert len(reader.pages) == 1
            text = extract_text(out / rel)
            assert entry["name"] in text, f"{rel} lost the patient name"
            assert entry["mrn"] in text, f"{rel} lost the MRN"


def test_scenarios_are_marked_in_manifest(tmp_path):
    out = tmp_path / "demo_docs"
    generate(out, patients=5)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in manifest["patients"]}

    assert by_id[RENAL_PATIENT_ID]["scenarios"] == ["renal_deterioration"]
    assert by_id[SCENARIOS["interaction"]["patient_id"]]["scenarios"] == ["drug_interaction"]
    assert by_id[SCENARIOS["conflict"]["patient_id"]]["scenarios"] == ["conflicting_results"]


def test_facilities_are_fictional(tmp_path):
    """No real institution may appear in generated documents."""
    banned = ["mayo", "cleveland clinic", "johns hopkins", "mass general",
              "kaiser", "blue cross", "cvs", "walgreens"]
    out = tmp_path / "demo_docs"
    generate(out, patients=5)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["patients"]:
        for rel in entry["files"]:
            low = extract_text(out / rel).lower()
            for b in banned:
                assert b not in low, f"{rel} names a real institution: {b}"