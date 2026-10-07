"""Adapter between the Contract 2 patient dict and the engine's actual keys.

WHY THIS FILE EXISTS
--------------------
``AxiomPipeline.answer`` reads ``patient["patient_id"]`` (pipeline.py:595, 615,
625) while Contract 2 specifies the identifier key as ``"id"``. Those two
cannot both be true, and pipeline.py is frozen working core that other agents
depend on. So we do not change either: we pass the engine the key it asks for
and keep Contract 2 intact on the wire. This is the cheapest of the three
possible resolutions and it leaves the published contract exactly as frozen.

The same module also guarantees the eight collections Contract 2 promises are
present, because ``ClinicalGraph._build`` indexes each one by key and raises
``KeyError`` on a malformed record. Turning that KeyError into a clean 404 is
the API layer's job, not the engine's.
"""

from __future__ import annotations

from typing import Any

from axiom.patient import COLLECTIONS

__all__ = ["normalise_patient", "contract2_to_engine", "engine_to_contract2"]


# Required keys per collection, mirroring exactly what ClinicalGraph._build
# indexes. Checked here rather than letting the engine's KeyError escape as a
# 500 — the contract guarantees these exist, so their absence is a data fault.
_REQUIRED = {
    "encounters": ("id", "start"),
    "diagnoses": ("id", "onset", "code", "category"),
    "labs": ("id", "loinc", "observed_at"),
    "meds": ("id", "start"),
    "allergies": ("id", "substance", "recorded_at"),
    "imaging": ("id", "reported_at"),
    "notes": ("id", "text", "observed_at"),
    "vitals": ("id",),
}


def normalise_patient(raw: Any) -> dict[str, Any]:
    """Coerce anything patient-shaped into a dict the engine can index.

    Raises ``ValueError`` (never KeyError/TypeError) when the input cannot be a
    patient record, so the route layer can turn it into a 404.

    A missing collection is a hard error, not something to default to ``[]``:
    silently inventing empty encounters for a record that merely *omitted* the
    key would produce a confident, structurally valid, entirely fictional chart.
    """
    if not isinstance(raw, dict):
        raise ValueError("patient record is not an object")

    pid = raw.get("id") or raw.get("patient_id")
    if not pid or not isinstance(pid, str):
        raise ValueError("patient record has no usable id")

    out: dict[str, Any] = {
        "id": pid,
        "name": str(raw.get("name", "") or ""),
        "dob": str(raw.get("dob", "") or ""),
        "mrn": str(raw.get("mrn", "") or ""),
    }
    for coll in COLLECTIONS:
        if coll not in raw:
            raise ValueError(f"patient record is missing the {coll!r} collection")
        value = raw[coll]
        if not isinstance(value, list):
            raise ValueError(f"patient collection {coll!r} is not a list")
        out[coll] = value
    for coll, required in _REQUIRED.items():
        for i, node in enumerate(out[coll]):
            if not isinstance(node, dict):
                raise ValueError(f"{coll}[{i}] is not an object")
            missing = [k for k in required if k not in node]
            if missing:
                raise ValueError(f"{coll}[{i}] is missing {missing}")
    # the engine's spelling of the identifier
    out["patient_id"] = pid
    return out


def contract2_to_engine(patient: dict[str, Any]) -> dict[str, Any]:
    """Contract 2 dict -> the dict ``AxiomPipeline.answer`` consumes."""
    return normalise_patient(patient)


def engine_to_contract2(patient: dict[str, Any]) -> dict[str, Any]:
    """Engine dict -> Contract 2 wire shape (drops the ``patient_id`` alias)."""
    out = {k: v for k, v in patient.items() if k != "patient_id"}
    out["id"] = patient.get("id") or patient.get("patient_id")
    return out


def build_graph(patient: dict[str, Any]):
    """Construct a ClinicalGraph, or raise ValueError on a malformed record.

    ClinicalGraph indexes eight collections and every node's ``id`` by key; a
    record missing any of them raises KeyError. We translate that here so the
    route can answer 404 rather than leaking a 500 stack trace.
    """
    from axiom.graph import ClinicalGraph

    try:
        return ClinicalGraph(normalise_patient(patient))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"patient record is malformed: {exc}") from exc