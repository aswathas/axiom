# 04 — The plan, as executed

**Date.** 2026-10-07, run against commits `79f3c9b` through `9c0fcfa`.

Scope is locked by this file. The phases below are the ones the commits actually
followed, in the order they were executed, not the order the design spec hoped
for. Where the build diverged from `docs/superpowers/specs/2026-10-07-axiom-emr-design.md`,
the divergence is recorded under the phase, because a plan that hides its own
changes is a plan nobody can use to reconstruct what happened.

Twenty-eight build commits and five branch merges, in six phases. Every phase ends with
something that runs.

---

## Phase 1 — Contracts and the ground rule

**Delivered.** `docs/CONTRACTS.md` frozen with six interfaces: the `Fact` schema,
the patient dict shape, three document text layouts, the `LLMClient`, the HTTP
surface, and a ports table assigning file ownership. The rewritten README and the
env template landed in the same commit (`c768373`), ahead of most of the code it
describes.

**Why first.** Four agents were going to work in parallel against a 48-hour
clock. The alternative — build sequentially and integrate at the end — does not
fit. Freezing the interfaces upfront bought the time; `03-decision.md` records
what it cost, which was three defects that came from the contracts being written
from memory of the engine rather than extracted from it.

**Done when.** An agent can be handed the repository and one contract and know
what it must not touch.

## Phase 2 — The engine's new edges

**Delivered.** Deterministic lab and Rx table parsers (`7e4ff29`), the clinical
document generator (`eeddd18`), the OpenRouter/MiniMax client with disk cache
(`30a6b71`), and then the two commits that made the graph worth having:
encounter extraction (`36ca2ba`) and encounter attribution (`a0c018a`).

The graph went from 21 nodes and 0 edges to 27 nodes and 25 edges on the demo
patient. Everything downstream depends on this phase: without temporal edges
there is no temporal answer, and the whole positioning in the design spec rests on
four question classes that flat retrieval cannot express.

**Done when.** Ingested documents produce a graph with `occurs_during` edges
firing, not just `precedes`.

## Phase 3 — Serving and querying

**Delivered.** The SQLite store and the FastAPI surface (`e0fb909`), the LLM
query-compilation seam with its rule planner fallback, verification and refusal
wired through to the API, and the patient registry with validation, document
attachment and tests (`fc2e52d`).

**Divergence from spec.** The registry was not in the design spec's API surface.
It arrived after the API was working, because a demo with one hard-coded patient
cannot show a patient list, and the answer to "is this a real EMR or a demo" is a
real patient list. It came with an additive extension to Contract 5 rather than an
edit, which is the mechanism that let it ship without breaking the freeze.

**Done when.** `/api/ask` returns verified claims with citations and refuses
correctly, and the refusal is a 200 with a reason rather than an error status.

## Phase 4 — The surface

**Delivered.** The frontend retargeted at the live API with upload and a source
viewer (`2324a2e`), a persistent URL shell and registry (`0c969b1`), and a visual
redesign with a clinical design system (`6b188fc`).

`2324a2e` is the phase's real content. It replaced a single pre-baked fixture
patient with the HTTP surface, put a refusal in first-class UI rather than the
red error treatment, made every citation resolve to a document, page and
character span or render struck-through, and fixed two chart bugs (a timeline
mixing px and %, and a hardcoded trend domain fighting the reference band) that
would have been visible in the first screenshot anyone took.

**Done when.** The full flow is clickable end to end against the live backend
with no console errors.

## Phase 5 — Running it, and being wrong about it

This is the phase the spec did not have, and it produced the three records in
`attempts/`.

Every defect below was found by running the assembled system. None was found by
the benchmark, and two of them were live while every benchmark metric was green.

| Commit | What running it found |
|---|---|
| `8c81bb8` | Node type shadowed by payload data; upload 404'd for a patient's first document; the production entrypoint never bound a store, so every store-backed route 500'd — and the tests passed because they all used the factory path |
| `3f2121e`, `bb1d004` | The default model id did not resolve on OpenRouter. Caught by an agent that had only ever tested a paid default |
| `d3f8987` | An empty answer was not a refusal; undated prose crashed the graph. `attempts/002` |
| `b9347f2` | One unfamiliar LOINC erased an entire chart. `attempts/003` |
| `40fee62` | Canned fixtures were rendering a complete fake registry with no indication it was fake. `attempts/001` |
| `bf5b7ce` | Two copies of citation resolution, one of them wrong; a focus trap that escaped; a dead backend rendering as a crash rather than a refusal |
| `55c71ae` | Refusals reached the audit trail but never the response, so the UI rendered a placeholder for one of the three things a refusal exists to say |
| `9c0fcfa` | The offline status label was still claiming a fallback that no longer existed — a fixture's own ghost, after the fixture was gone |

**Done when.** The defects stop being found by running it. They did not stop
during this build, and `06-verification.md` lists what is still untested as a
result.

## Phase 6 — Measuring, and publishing what it costs

**Delivered.** The naive RAG baseline (`87adba6`) so the comparison is against a
competent opponent rather than an assertion, the benchmark and robustness sweep,
UI screenshots taken from the live backend (`faec99a`), and the pitch deck
generated from live benchmark output (`ef6d912`).

**Divergence from spec, deliberate.** The design spec puts the RAG comparison
column last, at hour 34-40, "only after everything above is green." It was built
in the middle of day one instead, right after the store. The reason is visible in
the README's stage table: the whole architecture is an argument that the
comparison is worth making, and a comparison you have not built yet is a claim
rather than a measurement. Building it early also made it cheap to notice that
the four temporal question classes are the ones chunk retrieval cannot express,
which is the argument the demo is making.

The superseded deck and the pre-live screenshots were archived rather than
deleted (`fa4a206`), for the same reason every other decision in this project
keeps its losers.

**Done when.** Every number on a screen traces to `bench.py`, and every claim
traces to a source record.

---

## What this plan did not deliver

Written here so the next reader does not have to diff the spec against the log.

**OCR and handwriting were never built.** The spec put PyMuPDF plus Tesseract in
phase 1 and a degradation simulator in phase 2, and the definition of done
included "upload JPG/PNG → structured facts." Neither shipped. `pypdf` reads the
text layer and nothing else; this is limitation 5 in the README. The demo runs on
generated text PDFs throughout, which means the OCR path was never exercised by
anything, including the tests.

**The 5-patient corpus with a conflicting pair and a messy phone photo**
(`axiom/render/synthea`, 4-8 documents each spanning 12-24 months) was not built
at the specified size. The document generator and the degraded-render simulator
exist; the corpus around them is smaller and has no deliberate conflict pair,
because the phone-photo half depended on the OCR that did not get built.

**A clinician confirmation step at ingest** was cut, not deferred — see decision 8
in `03-decision.md` and limitation 4 in the README.

**Rehearsal and the backup video** were the last two blocks of the spec's
48-hour schedule and are not in this repository. Nothing in the code can record
whether the demo was rehearsed three times.

## The pattern in the execution

The plan's phases ran roughly in order, but the shape of the work was not
sequential build followed by test. Phase 5 — running the assembled system — is
where most of the commits are, and it is where every safety defect was found. The
benchmark was green from the first run of `axiom.bench` onward and stayed green
through all of it.

That is the lesson this build paid for, and it is recorded at full length in
`attempts/002`: the metrics assert about claims, and the defects lived in the
transformation from claims to an API response, and from Facts to a graph. Neither
level is observable to the other.