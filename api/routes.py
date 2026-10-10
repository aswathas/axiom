"""HTTP surface, Contract 5.

The rule that shapes every handler here: **a refusal is a 200.** When AXIOM
declines to answer a question, that is the product working, not a client error.
The only 4xx this module returns is for a *malformed request* — an unknown
patient id, an unparseable upload, a missing required field. "I don't know" and
"your request was wrong" are different statements and the status codes must not
conflate them.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from axiom.graph import ClinicalGraph  # noqa: F401  (re-exported for callers)
from axiom.pipeline import AxiomPipeline

from .engine import build_graph, contract2_to_engine, engine_to_contract2, normalise_patient
from .ingest import (UnsupportedDocument, extract_demographics, extract_pages,
                      sha256_hex)
from .planner import build_planner
from .registry import (PatientCreatePayload, PatientUpdatePayload,
                       attach_document_to_patient, create_patient_record,
                       get_patient_record, list_patient_documents,
                       list_patient_records, rebuild_patient_chart,
                       update_patient_record)
from .store import (DocumentNotFoundError, DuplicateMRNError,
                    DuplicatePatientError, PatientNotFoundError,
                    ValidationError)

log = logging.getLogger("axiom.api")

router = APIRouter(prefix="/api")

# One pipeline per process. AxiomPipeline holds an AuditTrail, which is a growing
# in-memory list; a per-request pipeline would lose the audit chain entirely.
_PIPELINE: Optional[AxiomPipeline] = None


def get_pipeline() -> AxiomPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        p = AxiomPipeline()
        # Swap in the LLM-bounded planner without touching pipeline.py: answer()
        # calls self.planner.parse(), so replacing the attribute is the seam.
        p.planner = build_planner(llm_client=None)
        _PIPELINE = p
    return _PIPELINE


def set_llm_client(client: Optional[Any]) -> None:
    """Attach an LLMClient to the shared pipeline's planner.

    Kept separate from construction so the app can boot, serve, and answer
    refusals correctly with no LLM configured at all.
    """
    p = get_pipeline()
    p.planner = build_planner(llm_client=client)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def _llm_provider() -> str:
    """Which provider is configured. NEVER returns the key itself."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("MINIMAX_API_KEY"):
        return "minimax"
    return "none"


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm": _llm_provider()}


# ---------------------------------------------------------------------------
# Patients & Registry
# ---------------------------------------------------------------------------

@router.post("/patients")
def create_patient(payload: PatientCreatePayload, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    raw_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    try:
        return create_patient_record(store, raw_data)
    except ValidationError as exc:
        raise HTTPException(400, exc.message)
    except (DuplicateMRNError, DuplicatePatientError) as exc:
        raise HTTPException(409, exc.message)


@router.get("/patients")
def list_patients(request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    return list_patient_records(store)


@router.get("/patients/{patient_id}")
def get_patient(patient_id: str, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    try:
        return get_patient_record(store, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(404, exc.message)


@router.patch("/patients/{patient_id}")
@router.put("/patients/{patient_id}")
def update_patient_demographics(patient_id: str, payload: PatientUpdatePayload,
                                request: Request) -> dict[str, Any]:
    store = request.app.state.store
    raw_data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    try:
        return update_patient_record(store, patient_id, raw_data)
    except PatientNotFoundError as exc:
        raise HTTPException(404, exc.message)
    except ValidationError as exc:
        raise HTTPException(400, exc.message)
    except DuplicateMRNError as exc:
        raise HTTPException(409, exc.message)


@router.post("/patients/{patient_id}/documents/{doc_id}")
def attach_patient_document(patient_id: str, doc_id: str,
                            request: Request) -> dict[str, Any]:
    store = request.app.state.store
    try:
        return attach_document_to_patient(store, patient_id, doc_id)
    except PatientNotFoundError as exc:
        raise HTTPException(404, exc.message)
    except DocumentNotFoundError as exc:
        raise HTTPException(404, exc.message)


@router.get("/patients/{patient_id}/documents")
def get_patient_documents(patient_id: str, request: Request) -> list[dict[str, Any]]:
    store = request.app.state.store
    try:
        return list_patient_documents(store, patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(404, exc.message)


@router.get("/patients/{patient_id}/graph")
def get_patient_graph(patient_id: str, request: Request) -> dict[str, Any]:
    """Serialise the ClinicalGraph.

    A malformed stored record raises ValueError out of ``build_graph``; that is
    a 404 (we have nothing to draw) and explicitly not a 500.
    """
    store = request.app.state.store
    patient = store.get_patient(patient_id)
    if patient is None:
        raise HTTPException(404, f"unknown patient {patient_id!r}")
    try:
        g = build_graph(patient)
    except ValueError as exc:
        raise HTTPException(404, f"patient {patient_id!r} has no usable record: {exc}")
    return {
        "patient_id": patient_id,
        "nodes": [g.nodes[n] for n in sorted(g.nodes)],
        "edges": [[a, b, t] for a, b, t in g.edges],
        "stats": g.stats(),
    }


# ---------------------------------------------------------------------------
# Documents and pages
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/page/{page_no}")
def get_page(doc_id: str, page_no: int, request: Request) -> dict[str, Any]:
    store = request.app.state.store
    page = store.get_page(doc_id, page_no)
    if page is None:
        if store.get_document(doc_id) is None:
            raise HTTPException(404, f"unknown document {doc_id!r}")
        raise HTTPException(404, f"document {doc_id!r} has no page {page_no}")
    text = page["text"]
    facts = store.get_facts_for_document(doc_id)
    spans = [{"fact": f, "char_start": f.get("source_char_start", 0),
              "char_end": f.get("source_char_end", 0)}
             for f in facts if int(f.get("source_page", 1)) == int(page_no)]
    return {
        "doc_id": doc_id,
        "page": int(page_no),
        "text": text,
        "char_start": 0,
        "char_end": len(text),
        "ocr_used": False,
        "kind": page.get("kind", "unknown"),
        "fact_spans": spans,
    }


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

def _parse_document(text: str, doc_id: str, page: int) -> list:
    """Call Agent A's parser; degrade to [] if it is not importable yet.

    ``axiom.extract.tables.parse_document`` exists in this tree. The guard is
    here because the upload path must not 500 during the window where the
    extract module is mid-edit by another agent — an empty fact list is a
    truthful answer, a crash is not.
    """
    try:
        from axiom.extract.tables import parse_document
    except Exception:  # pragma: no cover - only during parallel development
        log.warning("axiom.extract.tables.parse_document unavailable", exc_info=True)
        return []
    try:
        return list(parse_document(text, doc_id, page) or [])
    except Exception:
        log.warning("parse_document failed for %s p%d", doc_id, page, exc_info=True)
        return []


def _detect_kind(text: str) -> str:
    try:
        from axiom.extract.tables import detect_kind
    except Exception:  # pragma: no cover
        return "unknown"
    try:
        return str(detect_kind(text) or "unknown")
    except Exception:
        return "unknown"


@router.post("/upload")
async def upload(request: Request,
                 file: UploadFile = File(...),
                 patient_form: Optional[str] = Form(default=None, alias="patient_id"),
                 patient_id: Optional[str] = Query(default=None)) -> dict[str, Any]:
    """Ingest a document.

    ``patient_id`` is accepted as a form field *or* a query parameter. Declaring
    it only as a Form field meant a caller passing ``?patient_id=`` got a silent
    200 with no patient attached — the request looked successful and ingested
    nothing, which is the worst possible failure mode. Both are honoured.
    """
    patient_id = patient_id or patient_form
    store = request.app.state.store
    data = await file.read()
    try:
        pages = extract_pages(data, file.filename or "")
    except UnsupportedDocument as exc:
        raise HTTPException(exc.status_code, exc.message)

    doc_id = f"doc_{uuid.uuid4().hex[:12]}"
    sha = sha256_hex(data)
    kind = _detect_kind(pages[0]["text"])

    all_facts: list[dict[str, Any]] = []
    for p in pages:
        p["kind"] = kind
        for f in _parse_document(p["text"], doc_id, p["page_no"]):
            all_facts.append(f.to_dict() if hasattr(f, "to_dict") else dict(f))

    if patient_id and store.get_patient(patient_id) is None:
        # Uploading a document for a patient we have never seen is the normal
        # path, not an error — it is how a chart begins. Identity comes from the
        # document header. Previously this raised 404, which meant the very
        # first upload of a new patient could never succeed, and the patient
        # list stayed permanently empty.
        existing = store.create_patient({
            "patient_id": patient_id,
            **extract_demographics(pages[0]["text"]),
        })

    store.save_document(doc_id, patient_id, file.filename or "", kind, sha, pages)
    store.save_facts(patient_id, doc_id, all_facts)

    # Rebuild from every fact accumulated so far, not just this document — the
    # graph is a view over the whole chart, and a second lab report must be
    # able to complete a trend the first one could not.
    if patient_id:
        try:
            _rebuild_patient(store, patient_id)
        except Exception:
            log.exception("fact extraction stored, but chart rebuild failed")

    return {
        "doc_id": doc_id,
        "kind": kind,
        "sha256": sha,
        "filename": file.filename or "",
        "patient_id": patient_id,
        "facts": all_facts,
        "pages": [{"page_no": p["page_no"], "chars": len(p["text"]),
                   "kind": p["kind"]} for p in pages],
    }


def _rebuild_patient(store: Any, patient_id: str) -> dict[str, Any]:
    """Re-derive the patient's chart from all stored facts."""
    return rebuild_patient_chart(store, patient_id)


# ---------------------------------------------------------------------------
# Ask — the core product behaviour
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)


@router.post("/ask")
def ask(payload: AskRequest, request: Request) -> dict[str, Any]:
    """Answer a question about a patient.

    HTTP 200 is returned for EVERY question that names an existing patient,
    including every refusal and every abstention. A 4xx here would tell the
    clinician their question was malformed, which is a lie — the question was
    perfectly well formed, the record simply does not support an answer, and
    that distinction is the entire product.
    """
    store = request.app.state.store
    patient = store.get_patient(payload.patient_id)
    if patient is None:
        # This is the ONE 4xx: the resource itself does not exist. There is no
        # patient to ask about, so there is no refusal to give either.
        raise HTTPException(404, f"unknown patient {payload.patient_id!r}")

    try:
        engine_patient = contract2_to_engine(patient)
    except ValueError as exc:
        raise HTTPException(404, f"patient {payload.patient_id!r} has no usable record: {exc}")

    pipeline = get_pipeline()
    try:
        result = pipeline.answer(engine_patient, payload.query)
    except Exception as exc:
        # The engine raised on a record it should have refused. We still owe
        # the caller a 200 with an honest refusal — surfacing a 500 here would
        # teach clinicians that asking AXIOM a hard question breaks the app.
        log.exception("pipeline failure on %s", payload.patient_id)
        result = {
            "patient_id": payload.patient_id,
            "query": payload.query,
            "plan": {"intent": "general", "entity": None, "window_months": None},
            "refused": True,
            "refusal_reason": f"the analysis pipeline could not process this "
                              f"record: {type(exc).__name__}",
            "published": [],
            "abstained": [{"claim_id": "__refusal__", "action": "REFUSED",
                           "message": "AXIOM could not complete the analysis for "
                                      "this question. No claim has been made.",
                           "escalate_to": "records request"}],
            "audit_ref": None,
        }

    result.setdefault("status", "refused" if result.get("refused") else "answered")

    # An answer with nothing in it is not an answer.
    #
    # Measured case: "Does this patient have a pulmonary embolism?" against a
    # chart with no such documentation returned refused=False with an EMPTY
    # `published` list. To a clinician that renders as silence, and silence
    # reads as "nothing to report" — which is precisely the confident-negative
    # this system exists to refuse. Silence and absence-of-finding are not the
    # same statement, and the wire format must never collapse them.
    if not result.get("refused") and not result.get("published"):
        result["refused"] = True
        result["status"] = "refused"
        result["refusal_reason"] = (
            result.get("refusal_reason")
            or "the record does not contain evidence that either supports or "
               "excludes this claim; AXIOM will not infer one from silence."
        )
        result.setdefault("abstained", []).append({
            "claim_id": "__refusal__",
            "action": "REFUSED",
            "message": ("No claim could be published for this question. Absence of "
                        "a finding in the record is not a finding of absence."),
            "escalate_to": "clinician review",
        })

    try:
        store.record_audit(payload.patient_id, payload.query, result)
    except Exception:
        log.exception("audit write failed for %s", payload.patient_id)
    return result


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@router.get("/audit/{claim_id}")
def get_audit_trace(claim_id: str, request: Request) -> dict[str, Any]:
    """Trace a published claim back to the audit entry that decided it."""
    pipeline = get_pipeline()
    entry = pipeline.audit.trace(claim_id)
    if entry is not None:
        return entry
    store = request.app.state.store
    for row in store.get_audit(limit=500):
        for published in (row.get("response") or {}).get("published", []):
            if published.get("claim_id") == claim_id:
                return {"patient_id": row["patient_id"], "query": row["query"],
                        "claim": published, "source": "sqlite"}
    raise HTTPException(404, f"no audit trail for claim {claim_id!r}")


@router.get("/audit")
def list_audit(request: Request, patient_id: Optional[str] = Query(default=None),
               limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    return request.app.state.store.get_audit(patient_id=patient_id, limit=limit)