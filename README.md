# AXIOM

**An evidence-grounded clinical intelligence layer for electronic medical records.**

> A clinical AI that always answers is unsafe. Ours refuses when the evidence does
> not support an answer — and we measure how often that happens.

District 04 — AI-Native EMR for Intelligent Clinical Assistance.
Synthetic clinical data throughout. Clinician-assist only.

---

## Run it

### Backend

```bash
pip install pypdf reportlab fastapi uvicorn python-multipart python-dotenv
cp .env.example .env       # then paste your OpenRouter key into it
PYTHONUTF8=1 python -m axiom.demo     # 90-second pitch, end to end
PYTHONUTF8=1 python -m axiom.bench    # metric report + robustness sweep
```

> **Windows:** prefix with `PYTHONUTF8=1` or the run dies on the box-drawing
> characters in the console output — `UnicodeEncodeError: 'charmap' codec`.

### Document ingest

```bash
PYTHONUTF8=1 python -m axiom.render.synthea --out demo_docs/ --patients 5
```

Generates realistic clinical documents — lab reports, discharge summaries,
pharmacy printouts — with a selectable seeded random source. No network access.

### API

```bash
uvicorn api.main:app --reload --port 8000
```

### Frontend

```bash
cd axiom-ui && npm install && npm run dev      # http://localhost:3000
```

---

## What this actually does

Most clinical AI generates a fluent summary and trusts it. That fails in a
specific, detectable way: there is no mechanism separating what the record
supports from what the model inferred. In a clinical setting that is not a bug,
it is the product defect.

AXIOM inverts it.

```
document  →  text  →  deterministic extraction  →  clinical graph
                          ↓                              ↓
                    LLM for prose only          claim generation
                                                     ↓
                                          independent entailment check
                                                     ↓
                              published with citations  |  refused with a reason
```

Every claim is atomised, bound to the nodes that support it, then checked by a
verifier that sees only the claim and its evidence. Anything that fails is
suppressed — not greyed out, not footnoted, **absent**. When the record cannot
support an answer, the system refuses, names the missing evidence, and routes it
to a human.

### Four questions flat retrieval cannot answer

Document chunks do not have time in them. A time-stamped clinical graph does.

| Question | What it requires |
|---|---|
| *"What changed since the last visit?"* | temporal join across encounters |
| *"Was this already known?"* | supersession reasoning |
| *"What is the creatinine trajectory over 18 months?"* | series over one analyte |
| *"Which diagnoses have no follow-up?"* | an anti-join in time |

We build `axiom/baseline_rag.py` — a competent, unrigged chunk-retrieval
implementation — so the comparison on this point is honest rather than asserted.

### Where the LLM is, and where it deliberately is not

The model runs on a free, rate-limited tier. Rather than hide that, we let it
shape the architecture toward determinism:

| Stage | Owner | Fails how |
|---|---|---|
| PDF → text | `pypdf` | n/a |
| Lab / Rx extraction | **deterministic parser** | effectively never |
| Prose extraction | LLM | degrades to prose-only |
| Clinical graph | deterministic | never |
| **Query compilation** | **LLM — the only load-bearing call** | falls back to a rule planner |
| Verification | deterministic | never |
| Refusal | deterministic | never |

A clinical system should not ask a language model to read `Potassium | 5.20 |
mmol/L | 3.50 - 5.10 | H` when a regex reads it perfectly. Models handle prose;
parsers handle structure. The one place the model earns its keep is compiling
*"is his kidney function actually getting worse, or is one bad day skewing it?"*
into a scoped graph traversal — which is exactly the thing chunk retrieval
cannot express, and exactly the thing a small model can do reliably, because the
output is thirty tokens of JSON.

---

## Measured results

```
detection rate (planted findings)     97.1%   102/105
unsupported claim rate                 0.0%   0/270 claims
citation validity                     100%    every claim resolves to a real node
false positive rate                    0.0%   29 clean patients, 0 spurious findings
abstention recall                     100%    6/6 unanswerable questions refused
negation accuracy                     100%    120 sentences checked
entity resolution  P/R/F1           1.00     180 negative pairs, margin 0.015
```

**Robustness sweep** — the only numbers here that predict real-world behaviour:

```
noise 0.00   1.000  ####################################
noise 0.25   0.950  ##################################
noise 0.50   0.950  ##################################
noise 0.75   0.925  #################################
noise 1.00   0.875  ###############################
```

Degradation is graceful rather than cliff-edged. **Present this curve, not the
headline number.**

---

## Limitations — read these before you quote our numbers

1. **The verifier is rule-based, not a model.** Every high score reflects
   deterministic checks against known ground truth. An LLM verifier would score
   materially lower. We say this first because you will find it anyway.

2. **All clinical data is synthetic and generated by us.** Records are generated
   in-process from our own patient model (`axiom.clinical.PatientGenerator`
   rendered via `axiom.render.synthea`), not from an upstream project like MITRE
   Synthea. We wrote both the clinical records and the answer key, so recall
   measures *our pipeline against our own assumptions*, not against real patients
   or an external model of medicine. It is a weaker claim than evaluating
   against third-party or clinical data: it proves the pipeline recovers what we
   planted under our own rules, not that it generalises to medicine in the wild.

3. **We do not touch real PHI, and neither should you.** Identifiable patient
   records scraped from the open internet are either a breach already committed or
   were never de-identified; either way, processing them makes us a covered entity
   under HIPAA. We generate clinical data instead. If your project needs real
   records, [MIMIC-IV on PhysioNet](https://physionet.org/content/mimiciv/) is
   the legitimate route — credentialed, with a DUA, and worth the paperwork.

4. **Ingestion is fully automatic — nothing is confirmed by a clinician.** A
   mis-extracted value becomes a permanent graph node, and downstream claims will
   cite it confidently. The verifier tests whether a claim is faithful to the
   graph; by then, a bad value *is* the graph. In a real deployment this is where a
   review step belongs. We cut it for scope and it is the first thing we would add
   back.

5. **High scores do not generalise to real clinical text.** Real records contain
   abbreviations, typos, scanned documents, and coding conventions we have not
   modelled. OCR and handwriting support are not implemented at all.

6. **The entity-resolution margin is thin (0.015).** The highest-scoring
   non-match sits just below the merge threshold. On real data this needs proper
   calibration and manual review for ambiguous pairs.

7. **RxNorm mapping is an illustrative subset**, not the authoritative release.

Publishing these alongside the results is the point. A team that volunteers the
number it missed is demonstrating more engineering maturity than one that reports
only wins — and it is the only way the rest of the numbers are believable.

---

## Scope boundary

**AXIOM does not diagnose and does not prescribe.** It surfaces evidence and
reasoning to a licensed clinician who decides. It is read-only.

These are safety and regulatory constraints, not missing features, and they
appear as permanent chrome in the UI rather than a dismissible banner.

---

## Clinical reference

LOINC and ICD-10 values are real. The RxNorm mapping is an illustrative subset.
Clinical interaction pairs are drawn from documented, well-known interactions and
are illustrative for demonstration only — **not for clinical use**.

---

## Layout

```
axiom/
  facts.py         canonical Fact schema + provenance contract
  patient.py       Facts -> patient record -> ClinicalGraph
  graph.py         temporal clinical graph (the moat)
  pipeline.py      query planning, claim generation, verification, abstention
  clinical.py      record generation, normalisation, negation detection
  extract/         deterministic table parsing, LLM prose extraction
  render/          synthetic clinical document generation
  llm.py           provider switch, disk cache, retry
  baseline_rag.py  the strawman we measure ourselves against
  bench.py         metrics + robustness sweep
api/               FastAPI surface
axiom-ui/          Next.js clinician surface
docs/CONTRACTS.md  frozen interfaces — read before contributing
```

## Contributing

`docs/CONTRACTS.md` is frozen. Read it before touching anything. It exists so
parallel work does not collide, and breaking it breaks everyone.