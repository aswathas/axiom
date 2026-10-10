"""Patient registry business logic, validation at the trust boundary, and chart rebuilding.

Ensures that bad data never becomes a permanent record in the SQLite store or clinical graph.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from axiom.facts import from_dict as fact_from_dict
from axiom.patient import build_patient, empty_patient

from .engine import build_graph, contract2_to_engine, engine_to_contract2, normalise_patient
from .store import (
    DocumentNotFoundError,
    DuplicateMRNError,
    DuplicatePatientError,
    PatientNotFoundError,
    ValidationError,
)

log = logging.getLogger("axiom.registry")

__all__ = [
    "validate_mrn",
    "validate_dob",
    "validate_name",
    "validate_sex",
    "validate_patient_create",
    "validate_patient_update",
    "rebuild_patient_chart",
    "create_patient_record",
    "get_patient_record",
    "list_patient_records",
    "update_patient_record",
    "attach_document_to_patient",
    "list_patient_documents",
    "PatientCreatePayload",
    "PatientUpdatePayload",
]


class PatientCreatePayload(BaseModel):
    """Payload for creating a patient in the registry."""

    mrn: Optional[str] = Field(default=None, description="Medical Record Number (unique, required)")
    name: Optional[str] = Field(default=None, description="Patient full name (required)")
    dob: Optional[str] = Field(default=None, description="Date of birth in ISO format (required)")
    sex: Optional[str] = Field(default=None, description="Sex / gender (optional)")
    id: Optional[str] = Field(default=None, description="Explicit patient ID (optional)")


class PatientUpdatePayload(BaseModel):
    """Payload for updating patient demographics."""

    mrn: Optional[str] = Field(default=None, description="Updated MRN")
    name: Optional[str] = Field(default=None, description="Updated name")
    dob: Optional[str] = Field(default=None, description="Updated DOB (ISO format)")
    sex: Optional[str] = Field(default=None, description="Updated sex")


# ---------------------------------------------------------------------------
# Trust Boundary Validation
# ---------------------------------------------------------------------------

def validate_mrn(mrn: Any) -> str:
    """Validate MRN: must be present and non-empty after stripping whitespace."""
    if mrn is None or not isinstance(mrn, str):
        raise ValidationError("MRN is required and must be a string")
    s = mrn.strip()
    if not s:
        raise ValidationError("MRN is required and cannot be empty")
    return s


def validate_dob(dob: Any) -> str:
    """Validate DOB: must parse as an ISO-8601 date.

    Returns the normalized YYYY-MM-DD string.
    """
    if dob is None or not isinstance(dob, str):
        raise ValidationError("DOB is required and must be an ISO date string")
    s = dob.strip()
    if not s:
        raise ValidationError("DOB cannot be empty")

    try:
        if "T" in s:
            parsed = datetime.fromisoformat(s).date()
        else:
            parsed = date.fromisoformat(s)
        return parsed.isoformat()
    except Exception as exc:
        raise ValidationError(f"DOB {dob!r} is not a valid ISO date: {exc}")


def validate_name(name: Any) -> str:
    """Validate Name: must be non-empty after stripping whitespace."""
    if name is None or not isinstance(name, str):
        raise ValidationError("Name is required and must be a string")
    s = name.strip()
    if not s:
        raise ValidationError("Name is required and cannot be empty")
    return s


def validate_sex(sex: Any) -> Optional[str]:
    """Validate optional sex field."""
    if sex is None:
        return None
    if not isinstance(sex, str):
        raise ValidationError("Sex must be a string")
    s = sex.strip()
    return s if s else None


def validate_patient_create(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate all fields at trust boundary when creating a patient."""
    mrn = validate_mrn(payload.get("mrn"))
    dob = validate_dob(payload.get("dob"))
    name = validate_name(payload.get("name"))
    sex = validate_sex(payload.get("sex"))
    explicit_id = payload.get("id") or payload.get("patient_id")
    if explicit_id is not None:
        explicit_id = str(explicit_id).strip()
        if not explicit_id:
            explicit_id = None

    return {
        "mrn": mrn,
        "dob": dob,
        "name": name,
        "sex": sex,
        "id": explicit_id,
    }


def validate_patient_update(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate fields provided for demographic update."""
    out: dict[str, Any] = {}
    if "mrn" in payload and payload["mrn"] is not None:
        out["mrn"] = validate_mrn(payload["mrn"])
    elif "mrn" in payload:
        raise ValidationError("MRN cannot be null")

    if "dob" in payload and payload["dob"] is not None:
        out["dob"] = validate_dob(payload["dob"])
    elif "dob" in payload:
        raise ValidationError("DOB cannot be null")

    if "name" in payload and payload["name"] is not None:
        out["name"] = validate_name(payload["name"])
    elif "name" in payload:
        raise ValidationError("Name cannot be null")

    if "sex" in payload:
        out["sex"] = validate_sex(payload["sex"])

    return out


# ---------------------------------------------------------------------------
# Chart Rebuilding
# ---------------------------------------------------------------------------

def rebuild_patient_chart(store: Any, patient_id: str) -> dict[str, Any]:
    """Re-derive the patient's chart from all stored facts.

    Preserves demographics (name, dob, mrn, sex, created_at) from prior record.
    """
    prior = store.get_patient(patient_id) or {}
    raw_facts = store.get_facts_for_patient(patient_id)
    facts = []
    for rf in raw_facts:
        payload = rf.get("fact_json") or rf
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        try:
            facts.append(fact_from_dict(payload))
        except (TypeError, ValueError):
            continue

    patient = build_patient(
        facts,
        pid=patient_id,
        name=prior.get("name", "") or "",
        dob=prior.get("dob", "") or "",
        mrn=prior.get("mrn", "") or "",
    )
    if "sex" in prior and prior["sex"]:
        patient["sex"] = prior["sex"]
    if "created_at" in prior:
        patient["created_at"] = prior["created_at"]

    store.update_patient(patient)
    return patient


# ---------------------------------------------------------------------------
# Registry Operations
# ---------------------------------------------------------------------------

def create_patient_record(store: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a patient in the registry after trust-boundary validation."""
    validated = validate_patient_create(payload)
    record = store.create_registry_patient(validated)
    # Return formatted Contract 2 shape with demographics
    norm = normalise_patient(record)
    out = engine_to_contract2(norm)
    if record.get("sex"):
        out["sex"] = record["sex"]
    if record.get("created_at"):
        out["created_at"] = record["created_at"]
    return out


def get_patient_record(store: Any, patient_id: str) -> dict[str, Any]:
    """Get a patient record by ID, formatted with Contract 2 and demographics."""
    patient = store.get_patient(patient_id)
    if patient is None:
        raise PatientNotFoundError(f"unknown patient {patient_id!r}")
    norm = normalise_patient(patient)
    out = engine_to_contract2(norm)
    if patient.get("sex"):
        out["sex"] = patient["sex"]
    if patient.get("created_at"):
        out["created_at"] = patient["created_at"]
    return out


def list_patient_records(store: Any) -> list[dict[str, Any]]:
    """List patients including doc_count, node_count, and demographics."""
    out = []
    for row in store.list_patients():
        patient = store.get_patient(row["id"])
        node_count = 0
        if patient is not None:
            try:
                node_count = len(build_graph(patient).nodes)
            except ValueError:
                node_count = 0
        out.append({**row, "node_count": node_count})
    return out


def update_patient_record(store: Any, patient_id: str,
                          payload: dict[str, Any]) -> dict[str, Any]:
    """Update demographic fields on a patient."""
    validated = validate_patient_update(payload)
    record = store.update_patient_demographics(patient_id, validated)
    norm = normalise_patient(record)
    out = engine_to_contract2(norm)
    if record.get("sex"):
        out["sex"] = record["sex"]
    if record.get("created_at"):
        out["created_at"] = record["created_at"]
    return out


def attach_document_to_patient(store: Any, patient_id: str,
                               doc_id: str) -> dict[str, Any]:
    """Attach an ingested document to a registry patient and rebuild chart."""
    attach_result = store.attach_document(patient_id, doc_id)
    # Rebuild patient chart with newly attributed facts
    rebuild_patient_chart(store, patient_id)
    old_pid = attach_result.get("old_patient_id")
    if old_pid and old_pid != patient_id:
        rebuild_patient_chart(store, old_pid)

    return {
        "doc_id": attach_result["doc_id"],
        "patient_id": attach_result["patient_id"],
        "filename": attach_result["filename"],
        "kind": attach_result["kind"],
        "sha256": attach_result["sha256"],
        "created_at": attach_result["created_at"],
        "attached": True,
    }


def list_patient_documents(store: Any, patient_id: str) -> list[dict[str, Any]]:
    """List all documents attached to a patient."""
    if store.get_patient(patient_id) is None:
        raise PatientNotFoundError(f"unknown patient {patient_id!r}")
    return store.list_documents(patient_id)
