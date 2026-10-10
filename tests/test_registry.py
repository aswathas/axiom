"""Tests for Patient Registry backend — Store layer, API routes, trust-boundary validation.

Matches the testing style of tests/test_api.py:
- Real SQLite database in tmp_path
- TestClient against create_app
- Strict assertions on status codes and Contract 2 shapes
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.store import (
    DuplicateMRNError,
    DuplicatePatientError,
    PatientNotFoundError,
    DocumentNotFoundError,
    ValidationError,
)


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


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "test_reg.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def store(client):
    return client.app.state.store


# ---------------------------------------------------------------------------
# Store Layer Tests
# ---------------------------------------------------------------------------

def test_store_create_registry_patient(store):
    """Store creates patient with demographics and Contract 2 empty collections."""
    record = store.create_registry_patient({
        "mrn": "MRN_REG_001",
        "name": "Smith, Alice",
        "dob": "1980-05-15",
        "sex": "F",
    })
    assert record["id"].startswith("pat_")
    assert record["mrn"] == "MRN_REG_001"
    assert record["name"] == "Smith, Alice"
    assert record["dob"] == "1980-05-15"
    assert record["sex"] == "F"
    assert "created_at" in record

    # Fetch back
    fetched = store.get_patient(record["id"])
    assert fetched is not None
    assert fetched["mrn"] == "MRN_REG_001"
    assert fetched["name"] == "Smith, Alice"


def test_store_duplicate_mrn_raises_409_error(store):
    """Store layer rejects duplicate MRN with DuplicateMRNError, never silently overwriting."""
    store.create_registry_patient({
        "mrn": "MRN_UNIQUE_001",
        "name": "Patient One",
        "dob": "1975-01-01",
    })

    with pytest.raises(DuplicateMRNError) as exc_info:
        store.create_registry_patient({
            "mrn": "MRN_UNIQUE_001",
            "name": "Patient Two",
            "dob": "1982-02-02",
        })

    assert exc_info.value.status_code == 409
    assert "MRN_UNIQUE_001" in str(exc_info.value)

    # First patient is preserved intact
    patients = store.list_patients()
    assert len(patients) == 1
    assert patients[0]["name"] == "Patient One"


def test_store_update_patient_demographics(store):
    """Demographics can be updated in the store without losing existing data."""
    created = store.create_registry_patient({
        "mrn": "MRN_UPD_001",
        "name": "Original Name",
        "dob": "1970-03-10",
        "sex": "M",
    })
    pid = created["id"]

    updated = store.update_patient_demographics(pid, {
        "name": "Updated Name",
        "sex": "Other",
    })
    assert updated["name"] == "Updated Name"
    assert updated["sex"] == "Other"
    assert updated["mrn"] == "MRN_UPD_001"
    assert updated["dob"] == "1970-03-10"

    # Verify persistent in DB
    refetched = store.get_patient(pid)
    assert refetched["name"] == "Updated Name"
    assert refetched["sex"] == "Other"


def test_store_update_duplicate_mrn_rejected(store):
    """Updating MRN to an existing patient's MRN is rejected."""
    p1 = store.create_registry_patient({"mrn": "MRN_A", "name": "Patient A", "dob": "1970-01-01"})
    p2 = store.create_registry_patient({"mrn": "MRN_B", "name": "Patient B", "dob": "1972-02-02"})

    with pytest.raises(DuplicateMRNError):
        store.update_patient_demographics(p2["id"], {"mrn": "MRN_A"})


# ---------------------------------------------------------------------------
# API Route: POST /api/patients (Create)
# ---------------------------------------------------------------------------

def test_api_create_patient_success(client):
    """POST /api/patients creates a patient and returns Contract 2 shape."""
    payload = {
        "mrn": "MRN_API_100",
        "name": "Doe, Jane",
        "dob": "1988-11-23",
        "sex": "F",
    }
    r = client.post("/api/patients", json=payload)
    assert r.status_code == 200
    body = r.json()

    assert body["id"].startswith("pat_")
    assert body["mrn"] == "MRN_API_100"
    assert body["name"] == "Doe, Jane"
    assert body["dob"] == "1988-11-23"
    assert body["sex"] == "F"
    assert "created_at" in body

    # Contract 2 keys present
    for k in ("encounters", "diagnoses", "labs", "meds", "allergies", "imaging", "notes", "vitals"):
        assert k in body
        assert isinstance(body[k], list)
    assert "patient_id" not in body


def test_api_create_patient_duplicate_mrn_is_409(client):
    """Duplicate MRN returns HTTP 409 Conflict."""
    payload = {"mrn": "MRN_DUP_API", "name": "Patient First", "dob": "1960-01-01"}
    r1 = client.post("/api/patients", json=payload)
    assert r1.status_code == 200

    r2 = client.post("/api/patients", json={
        "mrn": "MRN_DUP_API",
        "name": "Patient Duplicate",
        "dob": "1965-05-05",
    })
    assert r2.status_code == 409
    assert "MRN_DUP_API" in r2.json()["detail"]


@pytest.mark.parametrize("bad_payload,err_snippet", [
    ({"mrn": "", "name": "A", "dob": "1990-01-01"}, "MRN"),
    ({"mrn": "   ", "name": "A", "dob": "1990-01-01"}, "MRN"),
    ({"name": "A", "dob": "1990-01-01"}, "MRN"),
    ({"mrn": "M1", "name": "", "dob": "1990-01-01"}, "Name"),
    ({"mrn": "M1", "name": "   ", "dob": "1990-01-01"}, "Name"),
    ({"mrn": "M1", "dob": "1990-01-01"}, "Name"),
    ({"mrn": "M1", "name": "A", "dob": ""}, "DOB"),
    ({"mrn": "M1", "name": "A", "dob": "not-a-date"}, "not a valid ISO date"),
    ({"mrn": "M1", "name": "A", "dob": "04/12/1964"}, "not a valid ISO date"),
    ({"mrn": "M1", "name": "A", "dob": "1990-02-31"}, "not a valid ISO date"),
    ({"mrn": "M1", "name": "A"}, "DOB"),
])
def test_api_create_patient_malformed_inputs_rejected(client, bad_payload, err_snippet):
    """Malformed input is rejected at the trust boundary with HTTP 400."""
    r = client.post("/api/patients", json=bad_payload)
    assert r.status_code == 400
    assert err_snippet.lower() in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# API Route: GET /api/patients (List) & GET /api/patients/{id} (Get)
# ---------------------------------------------------------------------------

def test_api_list_patients_includes_registry_fields(client):
    """GET /api/patients lists patients with original fields plus registry extensions."""
    client.post("/api/patients", json={
        "mrn": "MRN_LIST_1",
        "name": "Patient Alpha",
        "dob": "1977-07-07",
        "sex": "M",
    })
    client.post("/api/patients", json={
        "mrn": "MRN_LIST_2",
        "name": "Patient Beta",
        "dob": "1988-08-08",
        "sex": "F",
    })

    r = client.get("/api/patients")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2

    for row in items:
        # Original fields
        assert "id" in row
        assert "name" in row
        assert "dob" in row
        assert "mrn" in row
        assert "doc_count" in row
        assert "node_count" in row
        # Registry extensions
        assert "sex" in row
        assert "created_at" in row


def test_api_get_patient_by_id(client):
    """GET /api/patients/{id} returns Contract 2 shape with demographics."""
    created = client.post("/api/patients", json={
        "mrn": "MRN_GET_1",
        "name": "Johnson, Mark",
        "dob": "1992-04-18",
        "sex": "M",
    }).json()
    pid = created["id"]

    r = client.get(f"/api/patients/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == pid
    assert body["name"] == "Johnson, Mark"
    assert body["mrn"] == "MRN_GET_1"
    assert body["dob"] == "1992-04-18"
    assert body["sex"] == "M"
    assert "created_at" in body
    assert "patient_id" not in body


def test_api_get_unknown_patient_is_404(client):
    """GET /api/patients/{id} on unknown patient returns 404."""
    r = client.get("/api/patients/pat_nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# API Route: PATCH / PUT /api/patients/{id} (Update)
# ---------------------------------------------------------------------------

def test_api_patch_patient_demographics(client):
    """PATCH /api/patients/{id} updates demographics."""
    created = client.post("/api/patients", json={
        "mrn": "MRN_PATCH_1",
        "name": "Initial Name",
        "dob": "1985-05-05",
        "sex": "F",
    }).json()
    pid = created["id"]

    r = client.patch(f"/api/patients/{pid}", json={
        "name": "Renamed Person",
        "sex": "Other",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Renamed Person"
    assert body["sex"] == "Other"
    assert body["mrn"] == "MRN_PATCH_1"
    assert body["dob"] == "1985-05-05"


def test_api_put_patient_demographics(client):
    """PUT /api/patients/{id} updates demographics."""
    created = client.post("/api/patients", json={
        "mrn": "MRN_PUT_1",
        "name": "Put Initial",
        "dob": "1985-05-05",
    }).json()
    pid = created["id"]

    r = client.put(f"/api/patients/{pid}", json={
        "name": "Put Updated",
        "dob": "1985-06-06",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Put Updated"
    assert body["dob"] == "1985-06-06"


def test_api_update_patient_malformed_rejected(client):
    """Malformed update values are rejected with 400."""
    created = client.post("/api/patients", json={
        "mrn": "MRN_UPD_BAD",
        "name": "Valid Name",
        "dob": "1980-01-01",
    }).json()
    pid = created["id"]

    # Empty MRN
    r = client.patch(f"/api/patients/{pid}", json={"mrn": ""})
    assert r.status_code == 400

    # Invalid DOB
    r = client.patch(f"/api/patients/{pid}", json={"dob": "invalid-date"})
    assert r.status_code == 400

    # Empty name
    r = client.patch(f"/api/patients/{pid}", json={"name": ""})
    assert r.status_code == 400


def test_api_update_duplicate_mrn_is_409(client):
    """Updating MRN to a duplicate returns 409."""
    p1 = client.post("/api/patients", json={"mrn": "MRN_P1", "name": "P1", "dob": "1980-01-01"}).json()
    p2 = client.post("/api/patients", json={"mrn": "MRN_P2", "name": "P2", "dob": "1980-01-01"}).json()

    r = client.patch(f"/api/patients/{p2['id']}", json={"mrn": "MRN_P1"})
    assert r.status_code == 409


def test_api_update_unknown_patient_is_404(client):
    """Updating unknown patient returns 404."""
    r = client.patch("/api/patients/pat_ghost", json={"name": "Ghost"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# API Route: Attach & Claim Documents
# ---------------------------------------------------------------------------

def test_unattributed_upload_can_be_attached_later(client, store):
    """An unattributed document upload can be claimed later by attaching to a patient."""
    # 1. Clinician uploads lab document with NO patient selected
    upload_res = client.post(
        "/api/upload",
        files={"file": ("lab.txt", LAB_TEXT.encode("utf-8"), "text/plain")},
    )
    assert upload_res.status_code == 200
    upload_body = upload_res.json()
    doc_id = upload_body["doc_id"]
    assert upload_body["patient_id"] is None
    assert len(upload_body["facts"]) > 0

    # Verify document and facts are in store with no patient_id
    stored_doc = store.get_document(doc_id)
    assert stored_doc["patient_id"] is None
    doc_facts = store.get_facts_for_document(doc_id)
    assert len(doc_facts) > 0

    # 2. Clinician creates a patient in the registry
    patient = client.post("/api/patients", json={
        "mrn": "MRN762900",
        "name": "Bergman, L.",
        "dob": "1964-04-12",
        "sex": "F",
    }).json()
    pid = patient["id"]

    # Before attaching: patient has 0 documents and 0 graph nodes
    p_before = client.get(f"/api/patients/{pid}/graph").json()
    assert len(p_before["nodes"]) == 0

    docs_before = client.get(f"/api/patients/{pid}/documents").json()
    assert len(docs_before) == 0

    # 3. Clinician attaches document to patient: POST /api/patients/{id}/documents/{doc_id}
    attach_res = client.post(f"/api/patients/{pid}/documents/{doc_id}")
    assert attach_res.status_code == 200
    attach_body = attach_res.json()
    assert attach_body["doc_id"] == doc_id
    assert attach_body["patient_id"] == pid
    assert attach_body["attached"] is True

    # 4. Verification:
    # Documents list for patient now includes the attached document
    docs_after = client.get(f"/api/patients/{pid}/documents").json()
    assert len(docs_after) == 1
    assert docs_after[0]["doc_id"] == doc_id
    assert docs_after[0]["patient_id"] == pid

    # Facts now belong to the patient
    patient_facts = store.get_facts_for_patient(pid)
    assert len(patient_facts) > 0

    # Patient graph was re-derived and now contains nodes from the document!
    p_graph = client.get(f"/api/patients/{pid}/graph").json()
    assert len(p_graph["nodes"]) > 0
    node_names = {n.get("name") or n.get("drug") or n.get("display") or "" for n in p_graph["nodes"]}
    assert any("Creatinine" in s for s in node_names)

    # In patient list, doc_count and node_count are now populated
    plist = client.get("/api/patients").json()
    match = [p for p in plist if p["id"] == pid][0]
    assert match["doc_count"] == 1
    assert match["node_count"] > 0

    # 5. Pipeline reasoning (/api/ask) works against the newly attached evidence
    ask_res = client.post("/api/ask", json={
        "patient_id": pid,
        "query": "Is the kidney function getting worse?",
    })
    assert ask_res.status_code == 200


def test_attach_document_unknown_patient_is_404(client):
    """Attaching document to non-existent patient returns 404."""
    r = client.post("/api/patients/pat_nope/documents/doc_123")
    assert r.status_code == 404


def test_attach_unknown_document_is_404(client):
    """Attaching non-existent document returns 404."""
    p = client.post("/api/patients", json={
        "mrn": "MRN_ATT_404", "name": "Pat", "dob": "1990-01-01",
    }).json()
    r = client.post(f"/api/patients/{p['id']}/documents/doc_nope")
    assert r.status_code == 404


def test_list_patient_documents_unknown_patient_is_404(client):
    """Listing documents for unknown patient returns 404."""
    r = client.get("/api/patients/pat_ghost/documents")
    assert r.status_code == 404
