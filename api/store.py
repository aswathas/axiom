"""SQLite persistence extensions for the AXIOM Patient Registry.

Matches the existing schema and style of axiom/store.py exactly:
- Connection reuse with check_same_thread=False
- Concurrency guarded by RLock
- Uniqueness enforced at the store layer without silent overwrites
- Provenance and audit invariants maintained
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from typing import Any, Iterable, Optional

from axiom.patient import empty_patient
import axiom.store
from axiom.store import Store as AxiomStore, utcnow_iso, _dumps, _loads

log = logging.getLogger("axiom.store.registry")

__all__ = [
    "Store",
    "DuplicateMRNError",
    "DuplicatePatientError",
    "PatientNotFoundError",
    "DocumentNotFoundError",
    "ValidationError",
    "ensure_registry_schema",
    "utcnow_iso",
]


class DuplicateMRNError(ValueError):
    """Raised when an MRN already belongs to another patient."""

    def __init__(self, message: str = "patient with this MRN already exists",
                 status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DuplicatePatientError(ValueError):
    """Raised when attempting to create a patient with an existing ID."""

    def __init__(self, message: str = "patient already exists",
                 status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PatientNotFoundError(KeyError):
    """Raised when a patient ID cannot be found."""

    def __init__(self, message: str = "patient not found",
                 status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class DocumentNotFoundError(KeyError):
    """Raised when a document ID cannot be found."""

    def __init__(self, message: str = "document not found",
                 status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ValidationError(ValueError):
    """Raised for trust-boundary validation failures."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def ensure_registry_schema(conn: sqlite3.Connection, lock: threading.RLock) -> None:
    """Migrate the SQLite schema to support registry demographics and unique MRN index."""
    with lock:
        try:
            cursor = conn.execute("PRAGMA table_info(patients)")
            columns = [row[1] for row in cursor.fetchall()]
            if "sex" not in columns:
                conn.execute("ALTER TABLE patients ADD COLUMN sex TEXT NOT NULL DEFAULT ''")
                conn.commit()
        except sqlite3.OperationalError:
            pass

        # Partial unique index: only non-empty MRNs must be globally unique.
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_mrn_unique "
            "ON patients (mrn) WHERE mrn != '' AND mrn IS NOT NULL"
        )
        conn.commit()


def _store_ensure_registry_schema(self: AxiomStore) -> None:
    ensure_registry_schema(self._conn, self._lock)


def _store_create_patient(self: AxiomStore, patient: dict[str, Any]) -> dict[str, Any]:
    """Store or update a patient dict.

    Enforces MRN uniqueness across distinct patient IDs, rejecting duplicates
    with DuplicateMRNError rather than silently overwriting.
    """
    _store_ensure_registry_schema(self)
    pid = str(patient.get("id") or patient.get("patient_id") or f"pat_{uuid.uuid4().hex[:8]}")
    record = dict(patient)
    record["id"] = pid
    record.setdefault("name", "")
    record.setdefault("dob", "")
    mrn = str(record.setdefault("mrn", "") or "")
    sex = str(record.setdefault("sex", "") or "")
    created_at = record.get("created_at") or utcnow_iso()
    record["created_at"] = created_at

    with self._lock:
        if mrn:
            dup = self._conn.execute(
                "SELECT id FROM patients WHERE mrn = ? AND id != ?",
                (mrn, pid),
            ).fetchone()
            if dup is not None:
                raise DuplicateMRNError(f"patient with MRN {mrn!r} already exists (id={dup['id']})")

        existing = self._conn.execute(
            "SELECT id FROM patients WHERE id = ?", (pid,)
        ).fetchone()

        try:
            if existing is not None:
                self._conn.execute(
                    "UPDATE patients SET name = ?, dob = ?, mrn = ?, sex = ?, "
                    "patient_json = ? WHERE id = ?",
                    (record["name"], record["dob"], mrn, sex, _dumps(record), pid),
                )
            else:
                self._conn.execute(
                    "INSERT INTO patients (id, name, dob, mrn, sex, patient_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (pid, record["name"], record["dob"], mrn, sex, _dumps(record), created_at),
                )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() and "MRN" in str(exc).upper():
                raise DuplicateMRNError(f"patient with MRN {mrn!r} already exists") from exc
            raise

    return record


def _store_create_registry_patient(self: AxiomStore,
                                   patient_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new patient in the registry.

    Fails if MRN already exists or if an explicit patient ID conflicts with
    an existing record. Initializes empty collections for a valid Contract 2 shape.
    """
    _store_ensure_registry_schema(self)
    mrn = str(patient_data.get("mrn", "") or "").strip()
    if not mrn:
        raise ValidationError("MRN is required and cannot be empty")

    name = str(patient_data.get("name", "") or "").strip()
    dob = str(patient_data.get("dob", "") or "").strip()
    sex = str(patient_data.get("sex", "") or "").strip() if patient_data.get("sex") else ""

    pid = str(patient_data.get("id") or patient_data.get("patient_id")
              or f"pat_{uuid.uuid4().hex[:8]}")

    with self._lock:
        # Check duplicate ID
        id_dup = self._conn.execute(
            "SELECT id FROM patients WHERE id = ?", (pid,)
        ).fetchone()
        if id_dup is not None:
            raise DuplicatePatientError(f"patient with ID {pid!r} already exists")

        # Check duplicate MRN
        mrn_dup = self._conn.execute(
            "SELECT id FROM patients WHERE mrn = ?", (mrn,)
        ).fetchone()
        if mrn_dup is not None:
            raise DuplicateMRNError(
                f"patient with MRN {mrn!r} already exists (id={mrn_dup['id']})"
            )

        record = empty_patient(pid, name=name, dob=dob, mrn=mrn)
        record["id"] = pid
        if sex:
            record["sex"] = sex
        now_ts = utcnow_iso()
        record["created_at"] = now_ts

        try:
            self._conn.execute(
                "INSERT INTO patients (id, name, dob, mrn, sex, patient_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, name, dob, mrn, sex, _dumps(record), now_ts),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() and "MRN" in str(exc).upper():
                raise DuplicateMRNError(f"patient with MRN {mrn!r} already exists") from exc
            raise

    return record


def _store_list_patients(self: AxiomStore) -> list[dict[str, Any]]:
    """List patients including doc_count, sex, and created_at."""
    _store_ensure_registry_schema(self)
    with self._lock:
        rows = self._conn.execute(
            "SELECT id, name, dob, mrn, sex, created_at FROM patients ORDER BY id"
        ).fetchall()
        counts = {
            r["patient_id"]: r["n"]
            for r in self._conn.execute(
                "SELECT patient_id, COUNT(*) AS n FROM documents GROUP BY patient_id"
            ).fetchall()
        }
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "dob": r["dob"],
            "mrn": r["mrn"],
            "sex": r["sex"] if r["sex"] else None,
            "created_at": r["created_at"],
            "doc_count": counts.get(r["id"], 0),
        }
        for r in rows
    ]


def _store_update_patient_demographics(self: AxiomStore, patient_id: str,
                                      updates: dict[str, Any]) -> dict[str, Any]:
    """Update demographic fields on an existing patient."""
    _store_ensure_registry_schema(self)
    with self._lock:
        row = self._conn.execute(
            "SELECT id, name, dob, mrn, sex, patient_json, created_at FROM patients WHERE id = ?",
            (str(patient_id),),
        ).fetchone()
        if row is None:
            raise PatientNotFoundError(f"unknown patient {patient_id!r}")

        current_mrn = row["mrn"]
        if "mrn" in updates:
            new_mrn = str(updates["mrn"] or "").strip()
            if not new_mrn:
                raise ValidationError("MRN cannot be empty")
            if new_mrn != current_mrn:
                dup = self._conn.execute(
                    "SELECT id FROM patients WHERE mrn = ? AND id != ?",
                    (new_mrn, str(patient_id)),
                ).fetchone()
                if dup is not None:
                    raise DuplicateMRNError(
                        f"patient with MRN {new_mrn!r} already exists (id={dup['id']})"
                    )
        else:
            new_mrn = current_mrn

        new_dob = str(updates["dob"]).strip() if "dob" in updates else row["dob"]
        new_name = str(updates["name"]).strip() if "name" in updates else row["name"]
        if "name" in updates and not new_name:
            raise ValidationError("Name cannot be empty")

        if "sex" in updates:
            new_sex = str(updates["sex"]).strip() if updates["sex"] else ""
        else:
            new_sex = row["sex"] if "sex" in row.keys() else ""

        try:
            record = _loads(row["patient_json"])
        except Exception:
            record = empty_patient(str(patient_id), name=new_name, dob=new_dob, mrn=new_mrn)

        record["id"] = str(patient_id)
        record["name"] = new_name
        record["dob"] = new_dob
        record["mrn"] = new_mrn
        if new_sex:
            record["sex"] = new_sex
        elif "sex" in record:
            record["sex"] = ""

        try:
            self._conn.execute(
                "UPDATE patients SET name = ?, dob = ?, mrn = ?, sex = ?, "
                "patient_json = ? WHERE id = ?",
                (new_name, new_dob, new_mrn, new_sex, _dumps(record), str(patient_id)),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" in str(exc).upper() and "MRN" in str(exc).upper():
                raise DuplicateMRNError(f"patient with MRN {new_mrn!r} already exists") from exc
            raise

    return record


def _store_attach_document(self: AxiomStore, patient_id: str,
                           doc_id: str) -> dict[str, Any]:
    """Attach an ingested document to a patient and attribute its facts."""
    _store_ensure_registry_schema(self)
    with self._lock:
        p_row = self._conn.execute(
            "SELECT id FROM patients WHERE id = ?", (str(patient_id),)
        ).fetchone()
        if p_row is None:
            raise PatientNotFoundError(f"unknown patient {patient_id!r}")

        d_row = self._conn.execute(
            "SELECT doc_id, patient_id, filename, kind, sha256, created_at "
            "FROM documents WHERE doc_id = ?", (str(doc_id),)
        ).fetchone()
        if d_row is None:
            raise DocumentNotFoundError(f"unknown document {doc_id!r}")

        old_patient_id = d_row["patient_id"]

        self._conn.execute(
            "UPDATE documents SET patient_id = ? WHERE doc_id = ?",
            (str(patient_id), str(doc_id)),
        )
        self._conn.execute(
            "UPDATE facts SET patient_id = ? WHERE doc_id = ?",
            (str(patient_id), str(doc_id)),
        )
        self._conn.commit()

    return {
        "doc_id": d_row["doc_id"],
        "patient_id": str(patient_id),
        "old_patient_id": old_patient_id,
        "filename": d_row["filename"],
        "kind": d_row["kind"],
        "sha256": d_row["sha256"],
        "created_at": d_row["created_at"],
        "attached": True,
    }


# Patch methods onto AxiomStore so instances initialized in api.main or fixtures
# carry registry functionality seamlessly.
AxiomStore.ensure_registry_schema = _store_ensure_registry_schema  # type: ignore
AxiomStore.create_patient = _store_create_patient  # type: ignore
AxiomStore.create_registry_patient = _store_create_registry_patient  # type: ignore
AxiomStore.list_patients = _store_list_patients  # type: ignore
AxiomStore.update_patient_demographics = _store_update_patient_demographics  # type: ignore
AxiomStore.attach_document = _store_attach_document  # type: ignore


class Store(AxiomStore):
    """Subclass of Store with explicit registry methods."""

    def __init__(self, path: str = "axiom.db") -> None:
        super().__init__(path)
        self.ensure_registry_schema()
