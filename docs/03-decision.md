# 03 — The decisions

**Date.** 2026-10-07, with the final two decisions taken 2026-10-10.

This file records what was chosen and, for each one, what specifically ruled out
the alternative. A decision someone cannot revisit in six months is not a
decision, it is a preference. Where a decision was later reversed by running the
system, that is recorded here as a supersession rather than edited out — see
`attempts/001`, which is the failure record behind decision 10.

---

## 1. Verification is deterministic, and the verifier is deliberately blind

**Chosen.** Every claim is atomised, bound to the nodes that support it, and
checked by a rule-based verifier that sees only the claim and its evidence — not
the document, not the model's reasoning, not the question it was asked.

**What ruled out the alternatives.** The LLM verifier was the serious contender
and it was rejected on the score, not on taste. An LLM verifier shares the first
model's blind spots and scores materially lower, which means the headline number
in the README would be measuring something the system does not actually do. The
specific failure we would not accept: publishing a number earned by a verifier we
know is more permissive than the one that would run in production. Adding a
latency and rate-limit cost on a free tier to obtain a number we would then have
to apologise for is a bad trade twice over.

The blindness is the load-bearing part, and it is why the LLM verifier could not
be rescued by better prompting: the verifier cannot be argued into agreeing,
because it never sees the prompt.

**What would change it.** An LLM verifier becomes viable if — and only if — the
scores are published for both, side by side, with the rule-based number labelled
as the one the product actually enforces. It would not replace the deterministic
check; it would sit above it as a second, weaker gate. Until then the headline
metric belongs to the check that ships.

## 2. Extraction is deterministic first, LLM second

**Chosen.** Lab reports and prescriptions are parsed by regex. The model sees
prose only. The one load-bearing model call in the whole pipeline is query
compilation.

**What ruled out the alternatives.** Sending everything to the model was the
cheapest option in code and the most expensive in behaviour. The failure mode is
specific: a model asked to read `Potassium | 5.20 | mmol/L | 3.50 - 5.10 | H`
transcribes it today and misreads the reference bound tomorrow, and the error
lands in the graph as a permanent node that downstream claims will cite
confidently. There is no detection step between the transcription and the graph.
A parser has no such failure mode, and the work it takes is bounded.

Routing prose to the model is not a concession to convenience — prose is the one
input a regex genuinely cannot reach, so the split is where the model is useful
rather than where it is tolerable.

**What would change it.** If a table format appeared that defeated the parsers,
the routing is one module (`axiom/extract/`) and nothing downstream changes. The
benchmarks would show it first.

## 3. Clinical data is generated in-process, by us

**Chosen.** Records come from `axiom.clinical.PatientGenerator`, rendered through
`axiom.render.synthea`, and the answer key was written by the same hand.

**What ruled out the alternatives.** Three, in order of how seriously they were
considered.

Scraping identifiable records from the open internet was refused on regulatory
rather than technical grounds — the data is either a breach already committed or
was never de-identified, and in both cases processing it makes us a covered
entity under HIPAA. MIMIC-IV is named in the README as the legitimate route for
anyone who genuinely needs real records: credentialed, with a DUA, worth the
paperwork. It was not available inside a 48-hour scope, and pretending otherwise
would have been the easier lie.

MITRE Synthea would have produced better data and was rejected on honesty
grounds: it would have meant the records and the answer key came from different
hands, which is the thing the benchmark is supposed to be measuring against.
Self-generation is a strictly weaker claim, and it is published as limitation 2,
above the results rather than in a footnote.

The original README said the data came from an upstream project. It did not, and
commit `correct data provenance to reflect self-generated synthetic clinical
records` fixes it. The reason that correction matters is recorded in `01-problem.md`.

**What would change it.** Evaluation against a third-party corpus. Until that
exists, recall measures our pipeline against our own assumptions, and every
number here should be read that way.

## 4. Reuse the engine; build around it, not beside it

**Chosen.** The existing `axiom/` package — `ClinicalGraph`, `QueryPlanner.parse`,
`ClaimGenerator.verify`, `AbstentionLayer`, `AuditTrail`, `AxiomPipeline.answer` —
kept its signatures and its internals. The new work was ingest, store, API and UI.

**What ruled out the alternatives.** A clean-room rewrite of the clinical core
was available and would have produced a nicer codebase. It was ruled out because
the core was already benchmarked and working, and the benchmark is the only
evidence in this repository that the safety property holds. Rewriting the thing
the evidence is about would have meant re-earning the evidence from nothing,
inside a 48-hour window. The spec puts it plainly under "what we do NOT rewrite":
modifying, not forking.

**What would change it.** Nothing in this project's lifetime. If the graph
needed a shape the engine cannot express, the honest move is a new module beside
it with its own benchmark, not an edit underneath the existing one.

## 5. The Next.js surface, not a single self-contained HTML file

**Chosen.** Retool the existing Next.js app against the live API.

**What ruled out the alternatives.** `docs/archive/UI_BUILD_PLAN.md` argues for a
single self-contained `index.html` with the data inlined, and its reasoning is
good — nothing to install on stage, no port conflict, no `npm install` on venue
wifi. It was rejected because the plan it belongs to commits to a fixture-driven,
read-only demo surface, and that is exactly the property we cannot have.

The plan's own risk table names it: "Fixture goes stale after a pipeline change"
and "Judge asks to try a different query — the scripted path is fixed." The whole
product claim is that refusal is the feature and that the numbers come from the
run, not from the deck. A demo whose data cannot be re-derived from `bench.py`
cannot support that claim, and the pitch deck is generated from live benchmark
output for the same reason. The archived plan is kept in `docs/archive/` rather
than deleted, because "we considered this and here's why it lost" is worth more
than the silence of never having considered it.

**What would change it.** A venue with no network and no ability to run `npm
install` would make the trade the other way. That is the one condition the
original plan was right about.

## 6. Parallel agents against frozen contracts, with an integrator

**Chosen.** `docs/CONTRACTS.md` froze six interfaces before the build, with a
ports table assigning file ownership per agent and naming shared files
(`axiom/facts.py`, `axiom/patient.py`, `axiom/__init__.py`) as integrator-owned.

**What ruled out the alternatives.** Building each module in sequence was the
obvious alternative and it does not fit 48 hours with four people. The cost of
the parallel approach is that agents build against a written description of the
engine rather than the engine.

That cost landed, three times, and the file records it deliberately rather than
quietly fixing it. An earlier revision of Contract 2 said the patient identity
key was `id`; the engine emits `patient_id`. A second revision got `meds[].name`
where the engine uses `meds[].drug`. Both produced real failures — the second
raised `KeyError: 'drug'` the moment a patient had two overlapping
prescriptions, which is precisely the case the drug-interaction demo needs. The
recorded lesson is the part worth keeping: **where the contract and the engine
disagree, the engine is canonical.** A contract written from memory of a
codebase is a liability.

**What would change it.** Nothing about the freezing. What should change is the
generation of contracts — they were written from memory instead of extracted from
the code, and every defect found here was that mistake repeating.

## 7. Read-only, clinician-assist only — a constraint, not a missing feature

**Chosen.** AXIOM does not diagnose and does not prescribe. It surfaces evidence
and reasoning to a licensed clinician who decides, and the boundary appears as
permanent chrome in the UI rather than a dismissible banner.

**What ruled out the alternatives.** Writing to the record. This was listed as
out of scope in the archived UI plan and kept out of scope here, and the reason
is that read-only is a safety property rather than a feature gate: a system that
can edit the chart is a system that can corrupt it, and the verifier's whole job
is to check claims against a graph it does not write to.

**What would change it.** Only a regulatory and clinical review that we do not
have the standing to perform.

## 8. Full auto-accept at ingest — no clinician confirmation

**Chosen.** Ingestion is automatic. No review screen, no confidence flags in the
UI.

**What ruled out the alternatives.** A confirmation step on ingest is the obvious
thing to build and it was cut deliberately. The consequence is stated plainly in
the README as limitation 4: a mis-extracted value becomes a permanent graph node,
and downstream claims cite it confidently — because the verifier tests whether a
claim is faithful to the graph, and by then the bad value *is* the graph. A
confirmation step costs a screen and a per-fact decision, and it was scope that
was not available.

It is partially mitigated rather than solved: the `extractor` field and per-page
OCR confidence are retained on every node, so a bad extraction stays identifiable
after the fact even though nothing stops it going in.

**What would change it.** Nothing about the reasoning — this is named as the first
thing to add back, and `06-verification.md` records that nothing tests what
happens downstream once a bad value has been cited.

## 9. Encounter attribution is conservative, on purpose

**Chosen.** An observation with no containing encounter window is left
unattributed rather than snapped to the nearest visit.

**What ruled out the alternatives.** Nearest-visit attribution would have raised
the edge count immediately and every one of those edges would have been a guess
presented as a clinical fact. The commit that made attribution work
(`attribute observations to encounters so temporal edges fire`) states the trade
in one line: a wrong attribution manufactures a confident clinical claim, a
missing one is a visible gap. On the demo patient this took the graph from 21
nodes and 0 edges to 27 nodes and 25 edges, of which 20 are `occurs_during`.

**What would change it.** A documented admission window from the source record
would make attribution a lookup instead of an inference.

## 10. Fail loudly — no fixture fallback

**Chosen.** When the backend is unreachable, the UI says so and names the startup
command. The offline ask path returns an honest coverage refusal naming the
missing backend or evidence. It never returns an answer.

**What ruled out the alternatives.** Canned fixtures, which shipped first and
were removed in `remove canned fixtures on offline backend and make extraction
pipeline visible`. The reasoning and the full failure record are in
`attempts/001`; the short form is that a fixture fallback is only safe when the
fallback is visibly fake, and a synthetic lab report is not visibly fake to
anyone who has not been told which it is. The fallback was also masking every
backend error during development, so the UI looked finished while the API was
still being built underneath it.

**This supersedes nothing in decision 5.** The archived UI plan inlined its data;
this decision is about what happens when the live data is not there.

**What would change it.** Nothing. There is no scenario in which showing invented
clinical records without saying so is correct.

---

## Decisions that were closed by running the system, not by argument

Three were. They are recorded as `attempts/001`, `002` and `003` and are listed
here only so this file is the single place a reader can find what was decided:

- **An empty answer is a refusal** (`attempts/002`). Silence is not an
  acceptable output in a clinical display, because silence is indistinguishable
  from a clean result.
- **One unfamiliar LOINC must not void a chart** (`attempts/003`). Builders
  degrade per-node, not per-document.
- **A fixture fallback is an unlabelled source of truth** (`attempts/001`).