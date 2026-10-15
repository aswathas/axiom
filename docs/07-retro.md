# 07 — Retro

**Date.** 2026-10-16, written with the tool shipped and the benchmark green.

Written after the fact, not before. Several of these are things we could not have
known at kickoff, and knowing them in advance would have been the fiction this
whole directory exists to avoid.

---

## What actually happened

Twenty-eight build commits and five branch merges in a 48-hour window. The
pipeline works end to end: documents in, facts out, a time-stamped graph, a
verified answer with citations, or a refusal that names what is missing. The
benchmark is green. The README publishes seven limitations above the results
rather than in a footnote.

The benchmark was also green on the first run, and stayed green through the three
worst defects in the project. That is the single most useful thing this build
taught us, and it is worth leading with.

## What went right

**Writing the contracts before the code.** Six interfaces frozen, a ports table
assigning ownership, shared files named integrator-owned. Four agents built in
parallel and the whole thing integrated. The alternative — sequential builds with
integration at the end — does not fit 48 hours.

**Making the free tier shape the architecture instead of being hidden by it.**
One load-bearing model call out of seven stages, with a deterministic fallback at
that one point and none needed elsewhere. Every latency and rate-limit risk in the
design spec's risk table was answered by the same move: move work out of the model.

**Publishing the benchmark honestly, immediately.** The limitations went into the
README above the results. The naive RAG baseline was built rather than argued
against, so the comparison is a measurement. The pitch deck is generated from live
benchmark output — every number on a slide traces to `bench.py`.

**Reading the engine instead of trusting the contract.** An agent caught that
Contract 2 disagreed with the code on the patient identity key, and a second time
on `meds[].drug`. Both would have been integration-day surprises. The lesson is
now written into the contract itself: where the contract and the engine disagree,
the engine is canonical.

**Removing the fixture fallback rather than labelling it.** A fixture fallback is
only safe when the fallback is visibly fake, and a synthetic lab report is not
visibly fake. Deleting the path was both the correct call and better engineering —
the fallback had been masking every backend error during development.

## What went wrong

**The benchmarks could not see the bugs.** Every metric was green while an empty
answer rendered as silence (`attempts/002`) and while one unfamiliar LOINC code
erased an entire patient's chart (`attempts/003`). The metrics assert about claims:
were they supported, do they cite, were they refused. The first defect lived in the
transformation from "no supported claims" to an API response. The second lived in
the transformation from Facts to a graph. Neither level observes the other.

This is not a case of insufficient test coverage that more tests would have
caught. It is a gap between what the metrics describe and what the user sees, and
it will persist unless the assertions are written at the boundary where the two
meet.

**Nobody ran the thing early enough.** All three recorded failures were found by
running the assembled system. The two defects that mattered most were live for
hours while `axiom.bench` printed green. The first integration commit
(`fix(integration): node type collision, patient upsert on upload, production
lifespan`) found three defects in one pass, including one where
`uvicorn api.main:app` never bound a store and every store-backed route 500'd —
while the tests passed, because every test used the factory path instead. The
production entrypoint was broken and the suite was green.

**Contracts were written from memory.** Three defects in `docs/CONTRACTS.md`
existed before any code depended on them. The parallel build saved the schedule
and the contract file cost accuracy. Both things are true at once.

**A lie survived in the README for days.** The first version said the synthetic
data came from an upstream project. It did not; it was generated in-process by our
own patient model, and we wrote both the records and the answer key. Fixed in its
own commit, published as limitation 2. The correction matters more than the error:
recall measures the pipeline against our own assumptions, and until that sentence
existed above the results, the headline number meant something we had not earned.

**Small unlabelled truths accumulate.** After the fixtures were deleted, the
status label went on claiming a fallback that no longer existed — a separate fix,
`honest offline status label, no phantom fallback claim`. The mojibake in the
refusal string is the same shape: fixed once in `escalate_to`, left in
`refusal_reason`, the scope-boundary messages and the drug-interaction
descriptions, i.e. in the exact text the demo shows. In a system where refusals
are the primary output, the refusal string is the most consequential string in the
product, and we fixed it the way people fix such things: one instance at a time,
by noticing.

**The plan's front end was not built.** OCR and handwriting were in the design
spec's phase 1, in the definition of done, and in the risk table. They shipped as
nothing. `pypdf` reads a text layer and the demo runs on generated text PDFs
throughout, which means the degraded-render simulator that was built to feed OCR
has never fed anything. See `04-plan.md` for what else the build did not deliver.

**Entity resolution has a 0.015 margin and no boundary test.** The
highest-scoring non-match sits just below the merge threshold. A merge error at
that margin does not erase a chart — it merges two patients, which in this domain
is not recoverable by a clinician reading a disclaimer. Limitation 6, untested,
and it is the limitation whose failure mode is worst.

## What we would do differently

**Run the assembled system before running the benchmark.** Not instead of —
before. The benchmark answers "is the verifier working". It does not answer "does
the product work", and those were different questions for the entire build.

**Assert at the output boundary.** At minimum, a regression test that `/api/ask`
converts zero supported claims into `refused=true`, and a test that an unknown
LOINC degrades one node rather than the chart. Both defects were survivable; both
are one test each now. The general rule: *test what the user sees, not only what
the component produced*.

**Exercise the production entrypoint in CI.** `create_app()` attaching a lifespan
only when given a `db_path` is a defect no unit test could have found, because
every test used the factory. One test that boots `uvicorn api.main:app` would have
caught it on day one.

**Generate contracts from the code, not from memory of it.** `CONTRACTS.md` could
be partly derived by introspecting the dataclass and the router. The three defects
it contained were all instances of one mistake, and the mistake was structural.

**Delete the demo path earlier.** The single-HTML fixture plan in
`docs/archive/UI_BUILD_PLAN.md` was correct about stage risk and wrong about the
product, and it survived because nothing forced the question early. It was
superseded by the retarget at the live API, which was the right call — but the
retarget happened as part of the UI phase rather than as a decision taken in
advance.

**Sweep user-facing strings once, not instance by instance.** Grep for every
non-ASCII character in the string set and fix them in one commit. We fixed the
em-dash three times.

## What we would keep, unchanged

The architecture. Every stage decision held up under contact with real documents,
and the deterministic verifier is still the reason the numbers mean anything.

The refusal as a first-class outcome — a dark considered panel rather than the red
error treatment, with missing evidence, routing and audit reference. Making refusal
look deliberate is most of the product.

The provenance contract, and the decision that a citation which cannot resolve
renders struck-through rather than silently.

The honesty posture. Seven published limitations, a benchmark whose numbers can be
regenerated by a judge in ninety seconds, a comparison against a strawman we built
ourselves to keep honest. The cheapest trust available in a project like this, and
it costs nothing but admitting what you did not do.

## What the next iteration starts with

**A clinician confirmation step at ingest.** It is limitation 4, it is named as
the first thing to add back, and the reason it is first is that every other
limitation is downstream of it: once a bad value is a graph node, the verifier is
checking fidelity to a graph that is itself wrong. Nothing tests this, because
nothing can until the step exists.

**Boundary assertions at the output layer.** One test per recorded defect in
`attempts/`, at the level where a user would see the failure. Three tests, all of
which correspond to bugs that shipped.

**A wrong-verifier test.** Every high score reflects deterministic checks against
ground truth we generated. A bug that made the verifier over-permissive would
improve every metric in the table. Nobody has tested the checker.

**Boundary behaviour for entity resolution at the 0.015 margin, with manual review
for ambiguous pairs.** This is the limitation whose failure mode is not recoverable
by reading a disclaimer, and it is currently tested at exactly one point.

**OCR, or an honest hard stop.** Either build it, or make the upload path refuse
a scanned document by name rather than returning a confident empty extraction. The
current state — a text-layer reader with no stated boundary — is the one part of
the surface where silence is still a possible answer, and this whole project exists
because silence is indistinguishable from a negative finding.

**Load and failure testing on `/api/ask`.** 45-second timeouts were added for the
free tier, which means latency depends on an external rate-limited service and
nothing measures the distribution. The numbers a clinician would actually feel are
the numbers we have never recorded.

## The honest summary

The system does what it claims: it refuses when the evidence does not support an
answer, it can show why, and it publishes what it cannot do. The gap is not in the
architecture — it is that every defect which mattered was found by a person using
the product, and none of them by the tests. The next iteration should change that
ratio before it adds anything.