# Frozen Contracts

**These are FROZEN. Agents build against them. Do not change without a decision.**

Established so four agents can work in parallel without file collisions or
interface drift. Change requests go to the integrator, not into other agents'
files.

---

## Contract 1 — `axiom/facts.py` (the Fact schema)

```python
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

FACT_KINDS = ("lab", "med", "dx", "allergy", "note_stance", "vital", "imaging")

@dataclass
class Fact:
    kind: str                      # one of FACT_KINDS
    name: str                      # "Creatinine", "metformin", "Type 2 diabetes"
    value: Optional[Any] = None    # 1.48 (lab), None (med)
    unit: Optional[str] = None     # "mg/dL"
    timestamp: Optional[str] = None# ISO-8601 "2025-04-15"
    loinc: Optional[str] = None    # "2160-0" for known analytes, else None
    ref_low: Optional[float] = None
    ref_high: Optional[float] = None
    abnormal: Optional[bool] = None
    negated: bool = False          # "denies chest pain" -> negated=True
    meta: dict[str, Any] = field(default_factory=dict)
    # provenance — REQUIRED on every fact, this is the whole point of the project
    source_doc_id: str = ""
    source_page: int = 1
    source_char_start: int = 0
    source_char_end: int = 0
    extractor: str = "regex"       # "regex" | "llm"

    def to_dict(self) -> dict: return asdict(self)
```

**Invariants (agents must not violate):**
- `kind` ∈ `FACT_KINDS`
- `timestamp` is ISO-8601 date or datetime string, or `None`
- `source_doc_id` is never empty on a returned fact
- `extractor` ∈ `{"regex", "llm"}`
- `lab` facts SHOULD carry `loinc` when the analyte is in `axiom.clinical.ANALYTES`
- `abnormal` is computed, not guessed: value outside `[ref_low, ref_high]`

---

## Contract 2 — `axiom/patient.py` (patient dict shape)

This is what `ClinicalGraph(patient)` consumes (`axiom/graph.py:255`). **Do not
change the shape** — the existing engine indexes all eight keys.

> **Correction (2026-10-07).** An earlier revision of this contract specified the
> identity key as `id`. That was wrong. `axiom.clinical` emits `patient_id`
> (`clinical.py:256`) and `axiom.pipeline` indexes `patient["patient_id"]` at
> lines 595, 615 and 625. The engine is canonical. Caught during integration by
> an agent that read both sides instead of trusting the contract — which is
> exactly the failure mode this project exists to prevent, so it is recorded
> here rather than quietly fixed.
>
> **Node typing rule.** A node's `type` is structural and cannot be shadowed by
> payload data. Encounter payloads carry a visit kind in `type`
> (`"inpatient"`/`"outpatient"`); that value is preserved as
> `encounter_type`. Consumers filter nodes on `type` and may rely on it.
>
> **`meds` key is `drug`, not `name`.** A second revision of this contract got
> this wrong. `axiom.clinical` emits `drug` (`clinical.py:345`) and
> `graph.py`'s drug-interaction pass indexes `nodes[m]["drug"]`
> (`graph.py:337,345,348`). Building a patient from uploaded documents with
> `name` produced a `KeyError: 'drug'` the moment the patient had two
> overlapping prescriptions — precisely the case the interaction demo needs.
>
> **Lesson, recorded deliberately.** Three defects in this file were caught
> because an integrating agent read the engine rather than trusting the
> contract. A contract written from memory of a codebase is a liability; where
> this contract and the engine disagree, **the engine is canonical** and this
> file is wrong until proven otherwise.

```python
{
  "patient_id": "pat_001",          <-- canonical. NOT "id" (see note below)
  "name": "Bergman, L.",
  "dob": "1964-04-12",
  "mrn": "MRN762900",
  "encounters": [{"id","start","type","source_doc_id","source_page"}],
  "diagnoses":  [{"id","code","display","onset","category","source_doc_id","source_page"}],
  "labs":       [{"id","loinc","value","unit","observed_at","ref_low","ref_high"}],
  "meds":       [{"id","drug","rxnorm","dose","frequency","start","end","active"}],
  "allergies":  [{"id","substance","reaction","recorded_at"}],
  "imaging":    [{"id","modality","display","reported_at"}],
  "notes":      [{"id","text","observed_at","stance"}],
  "vitals":     [{"id","display","unit","points":[[ts, value], ...]}],
}
```

---

## Contract 3 — Document text layouts (what Agent B renders, Agent A parses)

### Layout A — Lab report (Quest-style)

Text layer must contain these exact anchors so the parser can anchor on them.

```
                    QUEST DIAGNOSTICS
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
```

**Parser anchors:** `Result`, `Reference Range`, the `----` rule under the header,
and `Flag` values `H`/`L`/`A`.

### Layout B — Discharge summary (narrative, for LLM extraction)

```
ST. MARGARET'S MEDICAL CENTER
Department of Internal Medicine

DISCHARGE SUMMARY

Patient: Bergman, L.        DOB: 04/12/1964        MRN: MRN762900
Admit Date: 01/15/2025      Discharge Date: 01/22/2025
Attending: Ramanathan, K.

DIAGNOSIS
1. Chronic kidney disease, stage 3 (N18.3)
2. Essential hypertension (I10)
3. Type 2 diabetes mellitus (E11.9)

PRESENTING HISTORY
Patient is a 60-year-old female presenting with progressive fatigue and
worsening exertional dyspnea. She denies chest pain. She denies hematuria.
Creatinine rose from 0.85 to 1.48 over the admission.

MEDICATIONS ON DISCHARGE
- Metformin 500 mg PO BID
- Lisinopril 10 mg PO daily
- Warfarin 5 mg PO daily

DISPOSITION
Follow up with Cardiology within 2 weeks. Renal nephrology referral placed.
```

### Layout C — Medication printout (pharmacy)

```
HARBORVIEW PHARMACY
Prescription History

Patient: Bergman, L.     DOB: 04/12/1964     MRN: MRN762900

Medication            Strength     Directions              Start
------------------------------------------------------------------------------
Metformin             500 mg       Take 1 tablet PO BID     01/15/2025
Lisinopril             10 mg       Take 1 tablet PO daily   01/15/2025
Warfarin                5 mg       Take 1 tablet PO daily   03/02/2025
```

---

## Contract 4 — `axiom/llm.py` (LLMClient)

```python
class LLMUnavailable(RuntimeError): ...

class LLMClient:
    def __init__(self, provider=None, model=None, cache_dir=".llm_cache", timeout=30.0): ...
    def json(self, system: str, user: str) -> dict:
        """Return parsed JSON. Raises LLMUnavailable on any failure after retries.

        Provider selection, in order:
          1. explicit provider= argument
          2. OPENROUTER_API_KEY env  -> https://openrouter.ai/api/v1/chat/completions
          3. MINIMAX_API_KEY env     -> https://api.minimax.io/v1/chat/completions
        Raises LLMUnavailable at construction if no key is present.
        """
```

**Contract details:**
- Disk cache at `cache_dir`, keyed `sha256(provider + model + system + user)`. Cache hit must not touch the network.
- Retry 3× with exponential backoff (1s, 2s, 4s) on 429/5xx/timeout.
- Strip markdown fences from the response before JSON parsing; if parse fails, retry once with a stricter prompt.
- **Never** log or echo the API key.
- Loads `.env` from repo root if `python-dotenv` is available, else plain `os.environ`.

---

## Contract 5 — HTTP API surface

```
GET  /api/health                -> {"ok": true, "llm": "openrouter"|"minimax"|"none"}
GET  /api/patients              -> [{"id","name","dob","mrn","doc_count","node_count"}]
GET  /api/patients/{id}         -> patient dict (Contract 2)
GET  /api/patients/{id}/graph   -> {"nodes":[...], "edges":[[a,b,type]]}
POST /api/upload                -> multipart file; {"doc_id","kind","facts":[Fact],"pages":[...]}
POST /api/ask                   -> {"patient_id","query"} -> AxiomPipeline.answer()
GET  /api/documents/{doc_id}/page/{n} -> {"text","page","ocr_used":false}
GET  /api/audit/{claim_id}      -> AuditTrail.trace(claim_id)
```

**`/api/ask` must never return HTTP 4xx for an unanswerable question.** A refusal
is a 200 with the refusal payload. This is the core product behaviour.

---

## Contract 6 — Ports (avoid conflicts)

| Agent | Owns | Must not touch |
|---|---|---|
| A — extract | `axiom/extract/**`, `tests/test_extract*.py` | `api/`, `axiom/render/`, `axiom/store.py` |
| B — render | `axiom/render/**`, `tests/test_render*.py` | `axiom/extract/`, `api/`, `axiom/store.py` |
| C — llm | `axiom/llm.py`, `tests/test_llm.py` | everything else |
| D — store+api | `axiom/store.py`, `api/**`, `tests/test_api*.py` | `axiom/extract/`, `axiom/render/`, `axiom/llm.py` |

Shared files (`axiom/facts.py`, `axiom/patient.py`, `axiom/__init__.py`) are
**integrator-owned**. Agents import them; agents do not edit them.

---

## Additive Extension — Patient Registry & Document Attribution (Additive to Contract 5)

> **Additive Extension (2026-10-10).** Adds explicit patient creation, demographics management, and retroactive document attribution. Existing frozen contracts (Contracts 1–6) remain strictly unchanged.

```
POST   /api/patients                         -> {"id","name","dob","mrn","sex","created_at",...}
GET    /api/patients                         -> [{"id","name","dob","mrn","sex","created_at","doc_count","node_count"}]
GET    /api/patients/{id}                    -> patient dict (Contract 2 shape + "sex", "created_at")
PATCH  /api/patients/{id}                    -> patient dict (update demographics)
PUT    /api/patients/{id}                    -> patient dict (update demographics)
POST   /api/patients/{id}/documents/{doc_id} -> {"doc_id","patient_id","filename","kind","sha256","created_at","attached":true}
GET    /api/patients/{id}/documents          -> [{"doc_id","patient_id","filename","kind","sha256","created_at"}]
```

**Registry Rules & Invariants:**
- `POST /api/patients`: MRN is required and non-empty. DOB must parse as an ISO-8601 date. Name is required. Sex is optional.
- MRN uniqueness is strictly enforced at the store layer. Duplicate MRNs return HTTP 409 Conflict (never silent overwrites).
- Malformed inputs (empty MRN, invalid DOB, empty Name) return HTTP 400 at the trust boundary.
- `POST /api/patients/{id}/documents/{doc_id}` attaches an ingested document to a registry patient, attributes all document facts to the patient, and rebuilds the clinical graph.
- `GET /api/patients/{id}/documents` lists documents attached to the patient; returns 404 if patient does not exist.