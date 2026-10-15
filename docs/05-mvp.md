# 05 — MVP scope

**Date.** 2026-10-07, frozen at the end of the build; registry addition 2026-10-10.

Two lists. The first is what the MVP does. The second is what it deliberately
does not, and every entry there has a reason — "no auth in v1" is a decision,
"no auth" is an oversight. The second list is the one that matters, because it is
what stops the next person re-adding something that was cut on purpose.

The scope boundary this whole document sits inside:

> **AXIOM does not diagnose and does not prescribe.** It surfaces evidence and
> reasoning to a licensed clinician who decides. It is read-only.

That is a safety and regulatory constraint, not a missing feature. It appears as
permanent chrome in the UI (`Chrome.js`) rather than a dismissible banner, so it
cannot be switched off by someone in a hurry.

---

## What the MVP does

**Ingests clinical documents.** PDF upload through `POST /api/upload`, with
document-type detection, per-page text extraction through `pypdf`, and facts
returned with provenance. Four screens: patients, ingest, chart, evidence, plus
the ask panel on the chart.

**Extracts deterministically first, and with a model second.** Lab reports and
prescriptions are parsed by regex into `Fact` objects carrying source document,
page and character span. Prose — discharge summaries, clinic notes — goes to the
model, which extracts diagnoses, medications, temporal expressions and negation.

**Builds a time-stamped clinical graph** from those facts, with provenance on
every node and `occurs_during` / `precedes` edges between encounters and the
observations inside them.

**Compiles a question into a scoped graph traversal.** The one load-bearing
model call in the pipeline, producing ~30 tokens of JSON, with a deterministic
rule planner as its fallback when the model is unavailable.

**Verifies every claim independently and publishes only what survives.** The
verifier sees only the claim and its evidence. Unsupported claims are suppressed —
absent, not greyed out, not footnoted.

**Refuses, and says why.** When nothing survives, the API returns a 200 with
`refused: true`, the reason, the named missing evidence, and where it routed. A
refusal is a successful response; `/api/ask` never returns 4xx for an unanswerable
question.

**Traces everything to a source.** Every citation resolves to document, page and
character span, or renders struck-through. `GET /api/audit/{claim_id}` returns the
full provenance chain, including refusal events.

**Generates its own corpus.** `axiom.render.synthea` renders synthetic patient
records into realistic clinical documents — Quest-style lab reports, discharge
summaries, pharmacy printouts — so the demo path needs no network and no external
dataset.

**Measures itself and publishes the result.** `python -m axiom.bench` produces
every number in the README, plus the robustness sweep. The pitch deck is generated
from live benchmark output. A naive chunk-retrieval baseline
(`axiom/baseline_rag.py`) is built and measured against rather than asserted
against.

**Manages patients.** Patient registry with validation, MRN uniqueness enforced
at the store layer (409, never a silent overwrite), demographic updates, and
retroactive document attachment that re-attributes facts and rebuilds the graph.

---

## What the MVP deliberately does not do

Each of these was cut, not overlooked. The reason is stated so the next person
does not re-litigate it.

**No authentication, no users, no sessions.** The API has no auth of any kind —
every endpoint is open to anyone who can reach it. Reason: a 48-hour hackathon
scope, and there is nothing to protect because all data is synthetic. This is
safe *only* because of the next entry.

**No real patient data, ever.** Identifiable records scraped from the open
internet are either a breach already committed or were never de-identified;
processing them makes us a covered entity under HIPAA. Records are generated
in-process. MIMIC-IV on PhysioNet is named as the legitimate route for a project
that genuinely needs real ones — credentialed, with a DUA. Reason: regulatory
refusal, not technical incapacity. Anyone deploying this beyond a demo inherits
this problem immediately.

**No diagnosis, no prescribing, no write access to the record.** Read-only.
Reason: safety property, not feature gate. A system that can edit the chart is a
system that can corrupt it, and the verifier's job is to check claims against a
graph it does not write to.

**No clinician confirmation at ingest.** A mis-extracted value becomes a permanent
graph node and downstream claims cite it confidently, because the verifier tests
fidelity to the graph and by then the bad value *is* the graph. Cut for scope;
the README names it the first thing to add back. Partially mitigated, not solved:
`extractor` and per-page OCR confidence are retained on every node so a bad
extraction stays identifiable after the fact.

**No OCR and no handwriting support.** Not implemented at all — `pypdf` reads
the text layer and stops there. Scanned documents, photographs and handwriting
are limitation 5. Reason: it was in the design spec's phase 1 and did not get
built, and shipping a degraded path that silently extracts nothing is worse than
not having it. The degradation simulator that would have fed it exists; the OCR
behind it does not.

**No HL7, FHIR, or any interoperability.** Not attempted. Reason: out of scope for
the window, and the interface cost is real — a second contract to freeze and get
wrong.

**No scheduling, billing, e-prescribing, or multi-tenancy.** Reason: all of these
are features of an EMR, and none of them are features of a system whose
contribution is refusing to answer. The spec's phrasing on this is worth keeping:
half-building an EMR produces eight dead screens and no impressive core.

**No calibration on real data, no manual review for ambiguous identity
resolution.** The entity-resolution margin is 0.015 and nothing tests behaviour at
the boundary. Reason: the margin is a property of synthetic data with names we
generated; there is nothing to calibrate against.

**No authoritative RxNorm.** An illustrative subset only, limitation 7. Reason:
the authoritative release is a large dataset with a sync story, and a subset that
looks authoritative but is not would be a lie in a drug-interaction demo.

**No load testing, no concurrency work, no multi-patient scale work.** 29 clean
patients, 180 negative pairs, 105 planted findings. The graph is per-patient by
construction and nothing records behaviour at EMR scale. Reason: it was not the
bottleneck in a 48-hour build, and it is recorded in `06-verification.md` as
untested rather than assumed fine.

**No fallback when the backend is down.** This one shipped by mistake and was
removed in `remove canned fixtures on offline backend and make extraction pipeline
visible`. The full record is `attempts/001`. Reason: a fixture fallback is only
safe when the fallback is visibly fake, and a synthetic lab report is not visibly
fake to a reader who has not been told which it is. The UI now fails loudly with
the startup command, and the offline ask path returns a coverage refusal naming
the missing backend.

**No "production deployment".** The app runs locally on two commands. Reason:
scope, and pretending otherwise would have been the easier lie.

---

## What this MVP is honest about

The exclusions above are the engineering decisions. The limitations below are
published in the README above the results, deliberately, and a reader should
treat them as part of the scope rather than as an appendix.

The verifier is rule-based, not a model, and an LLM verifier would score
materially lower. All clinical data is synthetic and written by the same hand as
the answer key, so recall measures the pipeline against our own assumptions.
The entity-resolution margin is thin. The scores do not generalise to real
clinical text. RxNorm is a subset.

Publishing the number that hurts is what makes the rest of the table believable,
and it is the cheapest trust available in a project like this.