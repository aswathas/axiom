# AXIOM-EMR — Design Spec

**Hackathon District 04: "AI-Native EMR for Intelligent Clinical Assistance"**
*Develop an AI-powered Electronic Medical Record platform that helps healthcare
professionals capture, organize, understand, and retrieve patient information efficiently.*

Date: 2026-10-07
Status: approved for implementation
Timeline: 48 hours

---

## 1. Positioning

### 1.1 The category we refuse to enter

Every other team will build chat-over-documents. In that category we lose: chat is
a commodity, and judges have scored a hundred of them. Committing to it spends the
whole weekend on a feature that is table stakes.

### 1.2 The category we enter

**The AI that is accountable.**

Every AI system at this hackathon will hallucinate. Ours catches itself, and can
prove it live, on demand, in front of a judge. The refusal is the product feature —
not the fallback, not the sad path. This is the reason naive clinical AI gets killed
in hospitals: a system that answers everything confidently is unsafe, and every
clinician knows it instantly.

**One-sentence pitch:** *Every AI on this floor will hallucinate. We built the one
that catches itself, and we can prove it on demand, live.*

### 1.3 Why this is a moat

The load-bearing distinction between this system and flat document retrieval is
that four question classes are not expressible over document chunks:

- *"What changed since the last visit?"* — temporal join across encounters
- *"Was this already known?"* — supersession reasoning
- *"What's the creatinine trajectory over 18 months?"* — series over one analyte
- *"Which diagnoses have no follow-up?"* — an anti-join in time

No chunk-retrieval pipeline answers these. A time-stamped clinical graph does. The
existing AXIOM engine already implements all four; this project makes it ingest
real documents rather than a pre-baked fixture.

---

## 2. Scope

### 2.1 In scope

| Capability | Why |
|---|---|
| Document upload (PDF, JPG, PNG) | "Capture" — first word in the brief |
| OCR + PDF text extraction | Real documents arrive as photos and scans |
| LLM-assisted fact extraction | Prose requires a model; tables do not |
| Time-stamped clinical graph | The technical moat (§1.3) |
| Query compilation via LLM | One narrow, reliable, high-value LLM task |
| Entailment verification | Converts confidence into citations |
| Calibrated refusal with named cause | The differentiator (§1.2) |
| Page-level provenance | "resolves to source in two clicks" |
| Patient list + chart screens | Minimum credible "EMR" surface |

### 2.2 Explicitly out of scope

Auth, scheduling, billing, e-prescribing, HL7/FHIR integration, HL7v2 parsing,
multi-tenancy, production deployment, mobile app. A real EMR is 6–12 months of work.
Half-building one produces eight dead screens and no impressive core; judges click
one broken control and the whole submission reads as a mockup.

### 2.3 Confirmed scope decisions

- **48-hour timeline.** One vertical slice, complete, over breadth.
- **All four document types** supported, built in sequence: lab reports →
  prescriptions → discharge notes → photos. Each stage is separately demoable, so
  there is never a day where the whole application is red.
- **Full auto-accept at ingest.** No confirmation screen, no confidence flags in the
  UI. Trade-off accepted and understood: a wrong extraction becomes a permanent
  "fact" that downstream claims will cite confidently. Mitigated structurally
  (§5.4) rather than by review UI.
- **LLM: OpenRouter, `apodex/apodex-1.1-mini`, free tier.** MiniMax is a supported
  drop-in alternate (§4.5).

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────┐
│  BROWSER — Next.js 14 (already exists, retooled)         │
│  Patient list │ Upload │ Chart │ Q&A │ Source viewer    │
└───────────────────────────┬──────────────────────────────┘
                            │ HTTP :8000
┌───────────────────────────▼──────────────────────────────┐
│  BACKEND — Python 3.12 + FastAPI + SQLite               │
│                                                          │
│  1. INGEST    PDF/JPG/PNG → text (PyMuPDF / Tesseract)    │
│  2. EXTRACT   regex-first, LLM for prose → Fact[]        │
│  3. GRAPH     Fact[] → ClinicalGraph (existing engine)   │
│  4. COMPILE   question → QueryPlan  ← ONLY LLM hot path  │
│  5. VERIFY    claim + evidence → entailed | suppressed   │
│  6. SERVE     patients / upload / ask / citations        │
│                                                          │
│  LLMClient ── provider switch (OpenRouter | MiniMax)     │
│  cache: disk, keyed by sha256(prompt)                    │
└──────────────────────────────────────────────────────────┘
```

### 3.1 Reuse boundary — what we do NOT rewrite

The existing `axiom/` package (~2,260 lines, working, benchmarked) is the core:

| Existing symbol | File:line | Role in new system |
|---|---|---|
| `ClinicalGraph` | `graph.py:255` | Built from ingested docs instead of generated patient |
| `ClinicalGraph.trend` | `graph.py:372` | Answers "is it actually deteriorating?" |
| `ClinicalGraph.diagnoses_without_followup` | `graph.py:409` | Anti-join in time |
| `ClinicalGraph.new_since_last_visit` | `graph.py:429` | Temporal join across encounters |
| `QueryPlanner.parse` | `pipeline.py:75` | **LLM seam** — replace rule parser, keep signature |
| `ClaimGenerator.verify` | `pipeline.py:328` | Independent entailment check |
| `AbstentionLayer` | `pipeline.py:483` | Calibrated refusal |
| `AuditTrail` | `pipeline.py:520` | Provenance, incl. refusal events |
| `AxiomPipeline.answer` | `pipeline.py:581` | Single entry point the API wraps |

Modifying, not forking. `QueryPlanner.parse` keeps its signature so the rest of the
pipeline is untouched.

### 3.2 New modules

```
axiom/
  ingest/
    pdf.py          PyMuPDF text-layer extraction, per-page offsets
    ocr.py          Tesseract for image input, preprocessing pass
    detect.py       doc-type classifier (lab | rx | note | unknown)
  extract/
    facts.py        Fact dataclass, canonical schema
    tables.py       DETERMINISTIC lab/Rx table parser (regex)
    prose.py        LLM extractor for free-text notes
    merge.py        dedupe + temporal ordering across documents
  render/
    synthea.py      Synthea patient → realistic clinical documents
    templates.py    Quest-style lab report, discharge summary
    degrade.py      page image, skew, shadow, blur, JPEG artifacts
  store.py          SQLite schema + repository
  llm.py            LLMClient, provider switch, disk cache
api/
  main.py           FastAPI app
  routes.py         endpoints
```

### 3.3 Design-for-isolation rules

Each unit answers: *what does it do, what does it depend on?*

- `axiom/llm.py` — knows about HTTP and caching. Knows nothing about clinical concepts.
- `axiom/extract/tables.py` — pure functions, `(text) -> [Fact]`. No I/O, no LLM, no graph. Trivially unit-testable.
- `axiom/extract/prose.py` — depends on `llm.py` only.
- `axiom/ingest/*` — `(bytes, mime) -> ExtractedText`. No clinical knowledge.
- `axiom/store.py` — knows the schema. Nothing else.

Consequence: swapping the LLM touches exactly one file. Replacing OCR touches one
file. The clinical core never learns that an LLM exists.

---

## 4. The pipeline, in detail

### 4.1 Ingest

| Input | Path | Notes |
|---|---|---|
| Text PDF | PyMuPDF `page.get_text()` | Per-page, offsets preserved |
| Scanned PDF | Rasterize → Tesseract | Most lab PDFs from real portals |
| JPG/PNG | Preprocess → Tesseract | Phone photos of paper reports |

OCR preprocessing: grayscale → upscale 2× → adaptive threshold → deskew
(Hough transform). Built for the `degrade.py` output, which simulates skew,
shadow, blur and JPEG compression.

**Extraction record per page** — this is the provenance substrate:
```python
PageText(doc_id, page_no, text, bbox_list, ocr_used: bool, confidence: float)
```

### 4.2 Extract — deterministic first, LLM second

**This ordering is architectural, not a workaround.** A clinical system should
never trust an LLM to read `Potassium | 4.8 | mEq/L` when a regex reads it
perfectly. LLM for prose, parsers for structure.

**Stage 1 — deterministic tables (always runs, never fails, costs nothing).**
Handles lab reports and prescriptions, which are structured:

```
Analyte | Value | Unit | Ref-range | Flag | Date
Creatinine | 1.48 | mg/dL | 0.60–1.30 | H | 2025-04-15
Potassium  | 5.20 | mmol/L | 3.50–5.10 | H | 2025-04-15
```
→ `Fact` objects. Expected to capture the large majority of lab fields.

**Stage 2 — LLM for prose only.** Discharge summaries, clinic notes. Extract
diagnoses, medications with dose/frequency, **negation**, and temporal expressions.

**Stage 3 — graceful degradation.** If the LLM fails, 402/403/429/502, or times out:
proceed with stage-1 output only. Extraction is never all-or-nothing.

### 4.3 Graph

`Fact[]` → `ClinicalGraph`. Every node carries provenance:

```python
Node(id, type, ts, payload, source_doc_id, source_page, source_char_start,
     source_char_end, extractor: "regex" | "llm")
```

`extractor` is retained even though the UI does not surface it — it is free to
store, and makes later calibration possible without re-ingestion.

### 4.4 Query compilation — the only load-bearing LLM call

The question is compiled into a `QueryPlan`:

```json
{"intent": "trend", "entity": "renal", "window_months": 6, "analyte": "creatinine"}
```

Intents: `trend` · `change_since` · `known` · `followup_gap` · `interaction` ·
`lookup` · `out_of_scope`.

**Why this is the right place for a small, free, rate-limited model:**
- Output is ~30 tokens of JSON. Tiny models do this reliably.
- It is exactly what flat retrieval cannot do — no chunk index produces a scoped
  temporal traversal.
- It is a large fraction of the demo's differentiation per token spent.

**Fallback:** if the LLM is unavailable, a keyword/intent classifier in
`QueryPlanner.parse` (which already exists, `pipeline.py:75`) handles the common
cases. The demo degrades to a slightly less fluent plan, not an error.

### 4.5 LLM client

```python
class LLMClient:
    def __init__(self, provider=None, model=None, cache_dir=".llm_cache/"): ...
    def json(self, system: str, user: str, schema_hint: str = "") -> dict: ...
```

- Provider selected by env: `OPENROUTER_API_KEY` → OpenRouter; `MINIMAX_API_KEY` →
  MiniMax. Neither set → raise at startup with a clear message.
- OpenRouter: `https://openrouter.ai/api/v1/chat/completions`
- MiniMax: `https://api.minimax.io/v1` (OpenAI-compatible — same request shape)
- **Cache:** disk, keyed `sha256(provider + model + system + user)`. Repeat queries
  in the demo cost nothing and cannot rate-limit. Pre-warm the cache before presenting.
- **Retry:** 429/502/timeout → exponential backoff, 3 attempts, ~8s total.
  Then fall through to the deterministic path.

**Key handling:** `.env` at repo root, gitignored. Never `NEXT_PUBLIC_*`.
Backend reads via `os.environ`. The key is never sent to the browser, and never
transcribed into a chat transcript.

---

## 5. Data

### 5.1 Provenance

Synthea patients (free, no credentialing, real clinical distributions: real disease
progression, real medication histories, real lab trajectories).

### 5.2 Why not real patient data

Identifiable patient records are HIPAA-regulated. Datasets scraped from the open
internet are either a breach already committed or never de-identified; either way,
processing them makes us a covered entity. Beyond legal exposure, a hospital-sector
judge who learns our demo used real patient data ends the conversation.

We state the synthetic origin **out loud, unprompted**. Honesty here is the pitch.

### 5.3 Synthea → documents → upload

```
Synthea patient record
    ├─ render → Quest-style lab report PDF, real reference ranges
    ├─ render → hospital discharge summary PDF, narrative prose
    ├─ render → pharmacy medication printout
    └─ degrade → phone photo: skew, shadow, low contrast, JPEG artifacts
                    ↓ upload through the real pipeline
```

The demo therefore has **real clinical data underneath**, in **real document
formats**, ingested the **messy way real documents arrive**.

### 5.4 Accepted consequence of auto-accept

With no confirmation step, a bad extraction silently becomes a graph node. The
verifier will pass claims citing it — the verifier tests whether a claim is faithful
to the graph, and by then the bad value *is* the graph. The error is invisible
downstream.

Accepted for timeline reasons. Partially mitigated by retaining `extractor` and
per-page OCR confidence in the node metadata (§4.3), so bad extractions remain
identifiable after the fact.

### 5.5 Assets

Corpus of **5 patients**, each with 4–8 documents spanning 12–24 months, including
at least one deliberately conflicting pair and one messy phone photo. Five is
enough to show the patient list is real; more is wasted build time.

---

## 6. API surface

```
GET  /api/patients                  → list: id, name, dob, mrn, doc_count, node_count
GET  /api/patients/{id}             → chart payload
GET  /api/patients/{id}/graph       → nodes + edges for timeline render
POST /api/upload                    → multipart; returns doc_id, detected type,
                                     extracted Fact[], page provenance
POST /api/patients/{id}/ask         → {query} → AnswerPlan
GET  /api/documents/{doc_id}/page/{n}   → page text + bbox, for source viewer
GET  /api/audit/{claim_id}          → full provenance chain
```

`POST /ask` returns the full refusal structure — refusal reason, named missing
evidence, routing destination, audit reference — not an error status. A refusal is
a successful response.

---

## 7. Frontend

Retool the existing Next.js app. Do not restart it. Components to repurpose:
`ClinicianApp.js`, `SourceDrawer.js` (becomes the page-level source viewer),
`Timeline.js` (renders the ingested graph), `TrendChart.js` (kept), `Benchmark.js`
(kept, repointed at the live API).

Screens: **Patient list** · **Upload** · **Chart** (timeline, trend, evidence
cards) · **Ask** (question box + answer + refusal states) · **Source viewer**
(overlaid PDF page with highlighted spans).

Permanent safety boundary chrome — "does not diagnose, does not prescribe" — stays
as non-dismissible UI, per the existing scope boundary.

---

## 8. Demo script — 4 minutes

| Time | Beat | What the screen does |
|---|---|---|
| 0:00 | **Problem** | "Every AI on this floor answers everything. In a hospital, that's how patients get hurt." |
| 0:20 | **Capture** | Drag in `discharge_summary.pdf`, `lab_report.pdf`, `phone_photo.jpg`. Live, no pre-baked fixture. Facts land. The photo genuinely OCRs through degradation. |
| 0:50 | **THE TURN** | Ask: *"Does this patient have a DVT?"* Split screen: naive RAG answers *"No documented evidence of DVT"* (absence of mention read as absence of disease). Ours **refuses**, names the missing test, routes to chart review. |
| 1:30 | **Temporal graph** | *"Is his creatinine actually deteriorating, or is one bad day skewing it?"* Trend line + the four lab dates behind it. |
| 2:10 | **Provenance** | Click any sentence → original PDF opens, scrolled to the exact line. Two clicks, every time. |
| 2:40 | **Honesty** | *"This detector is rule-based, not a model. Our data is synthetic. Here's the sweep where it breaks."* Noise curve degrading. |
| 3:30 | **Refusals** | Three questions it won't answer, each with its reason named. |

**0:50 is the hinge.** Every competitor demonstrates success. We demonstrate
safe failure, live, deliberately.

**2:40 buys disproportionate trust.** Publishing where the system breaks is nearly
free to prepare and is the single highest-trust move available.

### 8.1 Build order for the demo

The naive-RAG comparison column is ~1 hour and the highest-leverage hour in the
demo — but it is built **last**, only after the real pipeline works end to end.

---

## 9. Honest scoreboard

Presented unprompted, before any judge asks:

- Detection rate on our synthetic corpus — **published**
- Degradation under injected noise — **published**
- The verifier is **deterministic, not an LLM**. An LLM verifier would score
  materially lower. Stated first, before a judge finds it.
- Entity-resolution margin is thin (0.015) — the top-scoring non-match sits just
  below the merge threshold. Would require calibration and manual review on real data.
- Real clinical text — abbreviations, typos, scanned documents, coding conventions —
  would need revalidation. A working baseline, never a performance claim.

---

## 10. Hour-by-hour schedule

### Hour 0–6 — Data + ingest
- Synthea download, patient selection (5 patients)
- `render/` — lab report, discharge summary, Rx templates
- `degrade.py` — phone-photo simulation
- PyMuPDF + Tesseract extraction verified on all four doc types
- **Milestone:** upload a photo of a lab report, get correct text out

### Hour 6–12 — Extract + graph
- `tables.py` deterministic parser (regex table extraction)
- `prose.py` LLM extraction, OpenRouter wired, cache in place
- `Fact` schema, `merge.py`, `ClinicalGraph` construction from real facts
- `store.py` SQLite schema, repositories
- **Milestone:** ingested documents produce a populated graph

### Hour 12–18 — API + core query
- FastAPI app, all endpoints
- `llm.py` — provider switch, cache, retry, fallback
- `QueryPlanner.parse` — LLM compilation + deterministic fallback
- Verification, abstention, refusal wired through to the API
- **Milestone:** `POST /ask` returns verified claims with citations *and* refuses correctly

### Hour 18–28 — Frontend
- Patient list, upload screen with progress
- Chart: timeline, trend chart, evidence cards
- Ask panel with refusal rendering
- Source viewer: PDF page + highlighted span
- **Milestone:** full flow clickable, end to end, no console errors

### Hour 28–34 — Benchmark + hardening
- Repoint `Benchmark.js` at the live API
- Re-run `axiom.bench`; publish the sweep
- LLM cache pre-warm for every demo question
- Graceful-degradation verification: kill the API key, confirm the demo still runs

### Hour 34–40 — The naive-RAG comparison column
- Build only after everything above is green

### Hour 40–48 — Rehearsal
- Run the 4-minute script end to end, timed, 3× minimum
- Rehearse the failure mode: what if the network drops mid-demo
- Second machine / backup video, per the venue's risk tolerance
- README, data provenance statement, limitations published

---

## 11. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Free-tier 429 mid-demo | **High** | Disk cache, pre-warmed; deterministic fallback keeps the demo alive without the LLM |
| Model returns malformed JSON | High | Schema hint + retry + regex fallback; a query planner failure degrades fluency, not correctness |
| OCR fails on degraded photos | Medium | Preprocessing pass; the deterministic table parser salvages what OCR gets |
| Timeline slip | Medium | Doc types ship in sequence; stage 1 is independently demoable |
| Judge dismisses synthetic data | Medium | Volunteer it at 2:40; Synthea provenance is stated up front |
| Hall network unavailable | Low | Pre-warmed cache means zero network dependency at demo time |

---

## 12. Definition of done

- [ ] Upload PDF + JPG/PNG → structured facts → populated clinical graph
- [ ] Patient list with ≥5 patients, real document counts
- [ ] Four temporal question classes answered with citations
- [ ] At least 3 unanswerable questions refused, each naming what's missing
- [ ] Every claim traceable to source document, page, and character span
- [ ] `axiom.bench` passes; robustness sweep published in the UI
- [ ] Demo runs 4 minutes with the LLM API key removed
- [ ] Limitations published in-app
- [ ] `.env` gitignored; no key in any tracked file or transcript