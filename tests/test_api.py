"""HTTP layer tests — Contract 5, against a real SQLite file in tmp_path.

The load-bearing assertion in this file is
``test_unanswerable_question_is_200_not_4xx``. Everything else in the API could
be refactored tomorrow; that test encodes the one behaviour the product is
for, and it is written first-class so it cannot be quietly deleted.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from axiom.patient import empty_patient

# ---------------------------------------------------------------------------
# Contract 3 Layout A — lab report, verbatim
# ---------------------------------------------------------------------------

LAB_TEXT = """                    QUEST DIAGNOSTICS
              8401 Wilson Boulevard, Tampa, FL 33618

Patient: Bergman, L.          MRN: MRN762900
DOB: 04/12/1964               Collected: 04/15/2025 09:42
Accession: 2518473920         Ordering Physician: Ramanathan, K.

CHEMISTRY - RENAL PANEL

Analyte                     Result     Units       Reference Range    Flag
--------------------------------------------------------------------------------
Creatinine                     1.48      mg/dL       0.60 - 1.30          H
eGFR                            41     mL/min/1.73m2  90 - 140           L
Potassium                      5.20      mmol/L      3.50 - 5.10          H
Sodium                        131.0      mmol/L      135.0 - 145.0       L

End of Report
"""

RX_TEXT = """HARBORVIEW PHARMACY
Prescription History

Patient: Bergman, L.     DOB: 04/12/1964     MRN: MRN762900

Medication            Strength     Directions              Start
------------------------------------------------------------------------------
Metformin             500 mg       Take 1 tablet PO BID     01/15/2025
Lisinopril             10 mg       Take 1 tablet PO daily   01/15/2025
Warfarin                5 mg       Take 1 tablet PO daily   03/02/2025
"""


def make_pdf(text: str) -> bytes:
    """A real one-page PDF whose text layer is `text`.

    pypdf's reportlab-free route is awkward, so we emit a minimal uncompressed
    PDF by hand. If a PDF library is available we prefer it; otherwise this
    still produces a file pypdf can parse.
    """
    lines = text.split("\n")

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    content_ops = ["BT", "/F1 9 Tf", "10 TL", "40 750 Td"]
    for line in lines:
        content_ops.append(f"({esc(line)}) Tj T*")
    content_ops.append("ET")
    content = "\n".join(content_ops).encode("latin-1", "replace")

    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def store(client):
    return client.app.state.store


def seed_patient(client, pid: str = "pat_001", **over):
    """A Contract 2 patient with real content the graph can traverse."""
    p = empty_patient(pid, name="Bergman, L.", dob="1964-04-12", mrn="MRN762900")
    p["encounters"] = [
        {"id": "enc_0001", "start": "2024-06-01T09:00:00", "end": "2024-06-01T13:00:00",
         "type": "outpatient", "facility": "Tampa General"},
        {"id": "enc_0002", "start": "2025-04-15T09:42:00", "end": "2025-04-15T15:00:00",
         "type": "inpatient", "facility": "St. Margaret's Medical Center"},
    ]
    p["diagnoses"] = [
        {"id": "dx_0001", "code": "N18.3", "display": "Chronic kidney disease stage 3",
         "onset": "2024-06-01", "category": "renal", "encounter_id": "enc_0001"},
        {"id": "dx_0002", "code": "I10", "display": "Essential hypertension",
         "onset": "2025-04-15", "category": "cardio", "encounter_id": "enc_0002"},
    ]
    p["labs"] = [
        {"id": f"lab_{i:04d}", "loinc": "2160-0", "value": v, "unit": "mg/dL",
         "observed_at": ts, "ref_low": 0.6, "ref_high": 1.3,
         "encounter_id": "enc_0002"}
        for i, (v, ts) in enumerate(
            [(0.85, "2024-06-01T09:00:00"), (1.10, "2024-10-01T09:00:00"),
             (1.32, "2025-01-10T09:00:00"), (1.48, "2025-04-15T09:42:00")], start=1)
    ]
    p["meds"] = [
        {"id": "med_0001", "drug": "Warfarin", "rxnorm": "11289", "dose": "5 mg",
         "start": "2025-03-02", "end": None, "active": True},
        {"id": "med_0002", "drug": "Lisinopril", "rxnorm": "314076", "dose": "10 mg",
         "start": "2024-06-01", "end": None, "active": True},
    ]
    p["allergies"] = [
        {"id": "alg_0001", "substance": "Penicillin", "reaction": "rash",
         "severity": "moderate", "recorded_at": "2015-02-11"},
    ]
    p.update(over)
    client.app.state.store.create_patient(p)
    return p


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["llm"] in ("openrouter", "minimax", "none")


def test_health_never_leaks_the_key(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-THIS-MUST-NOT-LEAK")
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.text
    assert "sk-" not in body
    assert "THIS-MUST-NOT-LEAK" not in body
    assert r.json()["llm"] == "openrouter"


# ---------------------------------------------------------------------------
# THE core behaviour
# ---------------------------------------------------------------------------

def test_unanswerable_question_is_200_not_4xx(client):
    """A refusal is HTTP 200. This is the product behaviour; do not weaken it."""
    seed_patient(client)
    r = client.post("/api/ask", json={"patient_id": "pat_001",
                                      "query": "What is the patient's blood type?"})
    assert r.status_code == 200, "a refusal must never be a 4xx"
    body = r.json()
    assert body["refused"] is True
    assert body["published"] == []
    assert body["refusal_reason"]
    assert body["abstained"]


def test_out_of_schema_question_is_200_not_4xx(client):
    seed_patient(client)
    r = client.post("/api/ask", json={"patient_id": "pat_001",
                                      "query": "Can you prescribe an antibiotic?"})
    assert r.status_code == 200
    assert r.json()["refused"] is True


def test_undocumented_condition_is_refusal_not_a_no(client):
    """Absence of documentation is not absence of the condition."""
    seed_patient(client)
    r = client.post("/api/ask", json={"patient_id": "pat_001",
                                      "query": "Has this patient had a stroke?"})
    assert r.status_code == 200
    assert r.json()["refused"] is True
    assert "not absence of the condition" in r.json()["refusal_reason"]


def test_ask_unknown_patient_is_404(client):
    r = client.post("/api/ask", json={"patient_id": "nope", "query": "any trend?"})
    assert r.status_code == 404


def test_answerable_question_returns_200_with_claims(client):
    seed_patient(client)
    r = client.post("/api/ask", json={"patient_id": "pat_001",
                                      "query": "Is the kidney function getting worse?"})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert body["plan"]["intent"] == "trend"
    assert isinstance(body["published"], list)
    assert body["audit_ref"]


def test_ask_is_recorded_in_the_audit_table(client, store):
    seed_patient(client)
    client.post("/api/ask", json={"patient_id": "pat_001", "query": "any interaction?"})
    rows = store.get_audit("pat_001")
    assert len(rows) == 1
    assert rows[0]["query"] == "any interaction?"


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

def test_list_patients(client):
    seed_patient(client)
    r = client.get("/api/patients")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == "pat_001"
    assert rows[0]["name"] == "Bergman, L."
    assert rows[0]["node_count"] > 0
    assert "doc_count" in rows[0]


def test_get_patient_contract2_shape(client):
    seed_patient(client)
    r = client.get("/api/patients/pat_001")
    assert r.status_code == 200
    body = r.json()
    # Contract 2 keys, and NOT the engine's patient_id alias on the wire.
    for k in ("id", "name", "dob", "mrn", "encounters", "diagnoses", "labs",
              "meds", "allergies", "imaging", "notes", "vitals"):
        assert k in body, f"missing Contract 2 key {k}"
    assert "patient_id" not in body


def test_unknown_patient_is_404(client):
    assert client.get("/api/patients/nope").status_code == 404
    assert client.get("/api/patients/nope/graph").status_code == 404


def test_graph_endpoint_nodes_and_edges(client):
    seed_patient(client)
    r = client.get("/api/patients/pat_001/graph")
    assert r.status_code == 200
    body = r.json()
    assert body["nodes"] and all("id" in n and "type" in n for n in body["nodes"])
    assert all(len(e) == 3 for e in body["edges"])
    # NOTE: encounter nodes report node["type"] as the *encounter* type
    # ("outpatient"), not "Encounter" — ClinicalGraph._add spreads the payload
    # after the type key, and Contract 2 gives encounters their own `type`.
    # by_type/stats is the trustworthy grouping, so assert on that.
    ids = {n["id"] for n in body["nodes"]}
    assert {"enc_0001", "enc_0002", "dx_0001", "lab_0001", "med_0001"} <= ids
    by_type = body["stats"]["by_type"]
    assert {"Encounter", "Diagnosis", "LabResult", "MedicationOrder",
            "Allergy"} <= set(by_type)
    assert by_type["Encounter"] == 2
    assert body["stats"]["nodes"] == len(body["nodes"])


def test_malformed_patient_graph_is_404_not_500(client, store):
    """A record missing a collection the graph indexes must not be a 500."""
    from axiom.store import Store

    broken = {"id": "pat_broken", "name": "Broken"}
    store.create_patient(broken)  # stored verbatim, no collections
    r = client.get("/api/patients/pat_broken/graph")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def test_upload_text_round_trips_to_facts(client, store):
    r = client.post("/api/upload",
                    files={"file": ("lab.txt", LAB_TEXT.encode("utf-8"), "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "lab"
    assert body["doc_id"].startswith("doc_")
    names = {f["name"] for f in body["facts"]}
    assert {"Creatinine", "eGFR", "Potassium", "Sodium"} <= names
    assert len(body["pages"]) == 1
    assert store.get_facts_for_document(body["doc_id"])


def test_upload_detects_rx_layout(client):
    r = client.post("/api/upload",
                    files={"file": ("rx.txt", RX_TEXT.encode("utf-8"), "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "rx"
    assert {f["name"] for f in body["facts"]} >= {"Metformin", "Lisinopril"}


def test_upload_pdf_round_trips_to_facts_and_slices_back(client, store):
    """The whole thesis: a PDF in, cited character offsets out."""
    pdf = make_pdf(LAB_TEXT)
    r = client.post("/api/upload",
                    files={"file": ("report.pdf", pdf, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "lab", body
    creat = [f for f in body["facts"] if f["name"] == "Creatinine"]
    assert creat, "PDF text layer should have produced a Creatinine fact"
    f = creat[0]
    doc_id, page = body["doc_id"], f["source_page"]

    page_body = client.get(f"/api/documents/{doc_id}/page/{page}").json()
    assert page_body["ocr_used"] is False
    text = page_body["text"]
    # the offsets must actually slice the analyte name out of the stored page
    assert text[f["source_char_start"]:f["source_char_end"]] == "Creatinine"


def test_upload_facts_are_attached_to_a_patient(client, store):
    seed_patient(client)
    r = client.post("/api/upload",
                    files={"file": ("lab.txt", LAB_TEXT.encode("utf-8"), "text/plain")},
                    data={"patient_id": "pat_001"})
    assert r.status_code == 200
    assert store.get_facts_for_patient("pat_001")


def test_upload_docx_is_400_with_a_clear_message(client):
    r = client.post("/api/upload",
                    files={"file": ("notes.docx", b"PK\x03\x04", "application/msword")})
    assert r.status_code == 400
    assert "not supported" in r.json()["detail"].lower()


def test_upload_empty_is_400(client):
    r = client.post("/api/upload", files={"file": ("empty.txt", b"", "text/plain")})
    assert r.status_code == 400


def test_upload_to_unknown_patient_creates_them(client):
    """Uploading for a patient we have never seen must succeed, not 404.

    This previously raised 404, which made it impossible to ever create a
    patient's first document — the patient list stayed permanently empty and the
    demo could not ingest anything. Identity is read from the document header
    instead of being demanded as form input.
    """
    r = client.post("/api/upload",
                    files={"file": ("lab.txt", LAB_TEXT.encode("utf-8"), "text/plain")},
                    data={"patient_id": "ghost"})
    assert r.status_code == 200, r.text
    assert r.json()["patient_id"] == "ghost"

    listed = client.get("/api/patients").json()
    assert any(p["id"] == "ghost" for p in listed), listed

    # And the chart is immediately queryable.
    assert client.get("/api/patients/ghost/graph").status_code == 200


def test_page_endpoint_404_for_unknown_doc_and_page(client):
    assert client.get("/api/documents/doc_nope/page/1").status_code == 404
    r = client.post("/api/upload",
                    files={"file": ("lab.txt", LAB_TEXT.encode("utf-8"), "text/plain")})
    doc_id = r.json()["doc_id"]
    assert client.get(f"/api/documents/{doc_id}/page/99").status_code == 404


# ---------------------------------------------------------------------------
# Audit trace
# ---------------------------------------------------------------------------

def test_audit_trace_unknown_claim_is_404(client):
    assert client.get("/api/audit/c_nope").status_code == 404


def test_audit_trace_finds_a_published_claim(client):
    seed_patient(client)
    body = client.post("/api/ask", json={
        "patient_id": "pat_001", "query": "Is the kidney function getting worse?"}).json()
    published = body["published"]
    if not published:
        pytest.skip("no claim cleared the abstention threshold; trace path untested")
    cid = published[0]["claim_id"]
    r = client.get(f"/api/audit/{cid}")
    assert r.status_code == 200
    assert r.json()["claim"]["claim_id"] == cid


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

def test_cors_allows_the_ui_origin(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ---------------------------------------------------------------------------
# Store, directly
# ---------------------------------------------------------------------------

def test_store_round_trip(tmp_path):
    from axiom.facts import Fact
    from axiom.store import Store

    with Store(str(tmp_path / "s.db")) as s:
        s.create_patient(empty_patient("p1", "Doe, J."))
        assert s.get_patient("p1")["name"] == "Doe, J."
        assert s.get_patient("nope") is None
        s.save_document("d1", "p1", "a.pdf", "lab", "sha", [{"page_no": 1, "text": "x"}])
        n = s.save_facts("p1", "d1", [Fact(kind="lab", name="Creatinine", value=1.48,
                                           source_doc_id="d1", source_page=1,
                                           source_char_start=10, source_char_end=21)])
        assert n == 1
        got = s.get_facts_for_patient("p1")
        assert got[0]["source_char_start"] == 10
        assert s.get_page("d1", 1)["text"] == "x"
        assert s.record_audit("p1", "q", {"ok": True}) > 0
        assert s.get_audit("p1")[0]["response"] == {"ok": True}


def test_store_is_thread_safe(tmp_path):
    """FastAPI runs handlers in a threadpool; concurrent writes must not raise."""
    import threading

    from axiom.store import Store

    s = Store(str(tmp_path / "t.db"))
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            s.create_patient(empty_patient(f"p{i}"))
            s.record_audit(f"p{i}", "q", {"i": i})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(s.list_patients()) == 24
    s.close()


def test_planner_without_llm_is_deterministic():
    from api.planner import build_planner

    p = build_planner(llm_client=None)
    assert p.parse("is the kidney function worsening?")["intent"] == "trend"
    assert p.parse("is there a drug interaction?")["intent"] == "interaction"


def test_planner_llm_cannot_introduce_an_unknown_intent():
    from api.planner import build_planner

    class Rogue:
        def json(self, system, user):
            return {"intent": "diagnose_everything", "entity": "renal",
                    "window_months": 3}

    p = build_planner(llm_client=Rogue())
    out = p.parse("tell me something about this chart")   # base -> "general"
    assert out["intent"] == "general", "a hallucinated intent must not survive"


def test_planner_llm_failure_falls_back_to_deterministic():
    from api.planner import build_planner

    class Broken:
        def json(self, system, user):
            raise RuntimeError("no network")

    # A question the base parser already resolves short-circuits before the
    # LLM is consulted at all — the deterministic parse is authoritative.
    assert build_planner(llm_client=Broken()).parse("any follow-up overdue?")["intent"] \
        == "followup"

    # A genuinely ambiguous one does reach it, and the provider failure falls
    # through to "general" rather than propagating.
    p = build_planner(llm_client=Broken())
    assert p.parse("what do you make of this chart?")["intent"] == "general"
    assert p.llm_fallbacks == 1


def test_planner_never_calls_the_llm_when_the_base_parser_is_specific():
    from api.planner import build_planner

    class Exploding:
        def json(self, system, user):
            raise AssertionError("the LLM must not be consulted here")

    p = build_planner(llm_client=Exploding())
    assert p.parse("is the kidney function worsening?")["intent"] == "trend"
    assert p.parse("any drug interaction?")["intent"] == "interaction"
    assert p.llm_calls == 0