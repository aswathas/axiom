# 06 — Verification

**Date.** 2026-10-07, with additions 2026-10-15.

## What passed

**`python -m axiom.bench` produces every number in the README**, and the pitch deck
is generated from live benchmark output rather than written by hand — commit
`District 04 pitch deck, generated from live benchmark output`.

```
detection rate (planted findings)     97.1%   102/105
unsupported claim rate                 0.0%   0/270 claims
citation validity                     100%    every claim resolves to a real node
false positive rate                    0.0%   29 clean patients, 0 spurious findings
abstention recall                     100%    6/6 unanswerable questions refused
negation accuracy                     100%    120 sentences checked
entity resolution  P/R/F1           1.00     180 negative pairs, margin 0.015
```

**The robustness sweep is the part that predicts behaviour**, and the README says so
directly rather than letting the headline number stand alone:

```
noise 0.00   1.000  ####################################
noise 0.25   0.950  ##################################
noise 0.50   0.950  ##################################
noise 0.75   0.925  #################################
noise 1.00   0.875  ###############################
```

Graceful degradation rather than a cliff. The instruction attached to it —
*"Present this curve, not the headline number"* — is the correct instruction for
anyone quoting this work.

**The patient registry has tests.** Commit `add patient registry with validation,
document attachment, and tests`.

**`docs/CONTRACTS.md` is frozen**, so parallel agents do not collide. It is described
in the README's contributing section as required reading, with the reason stated:
"breaking it breaks everyone."

**UI screenshots were taken from the live backend**, not from a mock. The commit
`UI screenshots from the live backend` is the same instinct as the fixtures removal,
in the opposite direction.

## What failed

**Every one of the three records in `attempts/` was found by running the real thing,
not by the benchmark.** All three:

| Attempt | Found by |
|---|---|
| 001 — canned fixtures | Running the frontend with no backend |
| 002 — empty answer is silence | Asking a real question of a real ingested chart |
| 003 — one LOINC erases a chart | Running real ingested data |

The benchmark was green while attempts 002 and 003 were live. `attempts/002`
explains the mechanism: the metrics assert about claims, and both defects were in the
transformation from claims to API response and from Facts to graph.

**A default model id did not resolve.** `fix(llm): default to a model id that resolves
on OpenRouter; make 404 loud`. `apodex/apodex-1.1-mini` 404s; the resolvable id carries
a `:free` suffix. Caught by an agent that had only tested a paid default — which is
what "make 404 loud" is for.

**Three integration defects in one commit** — node type collision, patient upsert on
upload, production lifespan. All found by running the assembled system rather than
its parts.

**The README's data provenance was wrong** and was corrected in its own commit. Both
the records and the answer key are self-generated; the original wording implied an
upstream source. Now limitation 2, above the results.

**An em-dash rendered as mojibake** in a user-facing refusal string when a hop
decoded UTF-8 as cp1252. In a system where refusals are the primary output, the
refusal string is the most consequential string in the product.

## Still untested

**The verifier has never been tested with a wrong verifier.** Every high score
reflects deterministic checks against known ground truth — ground truth the team
generated. A bug in the verifier that made it over-permissive would improve every
metric in the table.

**Correction, 2026-10-16: the refusal path now has a regression test.** This file
previously recorded that the `attempts/002` fix had none. That is no longer true.
`tests/test_no_silent_answers.py` exists and asserts exactly the defect — including
`test_empty_published_list_becomes_a_refusal` — against the `/api/ask` route.
`python -m pytest tests/test_no_silent_answers.py` → 5 passed. The reference in
`attempts/002` to "no regression test" is superseded by this note.

**No test for the KeyError class.** `attempts/003` fixed one bare dictionary lookup.
Whether any other builder stage raises on unexpected input was not checked, and the
ingest path accepts free text from an LLM extractor, so unexpected input is expected.

**Real clinical text is untested, by design.** Abbreviations, typos, scanned
documents, OCR, handwriting — none implemented, none tested. Limitation 5.

**The entity-resolution margin is 0.015 and nothing tests behaviour at the boundary.**
Limitation 6 in the README, and unlike the others it is a merge error rather than a
display error. Two patients merged is not recoverable by a clinician reading a
disclaimer.

**RxNorm is an illustrative subset** and is not validated against the authoritative
release. Limitation 7.

**Ingestion has no clinician confirmation**, cut for scope, named in the README as the
first thing to add back. Nothing tests what happens when a mis-extracted value has
already been cited by downstream claims — because by then the bad value *is* the
graph, and the verifier is checking fidelity to a graph that is itself wrong.

**Concurrency and multi-patient scale untested.** 29 clean patients, 180 negative
pairs, 105 planted findings. The architecture is a temporal graph per patient; nothing
records behaviour at the scale a real EMR would carry.

**The API has no load or failure testing.** 45-second timeouts were added to
accommodate LLM and verification passes on the free tier, which means latency depends
on an external rate-limited service, and nothing measures the distribution.