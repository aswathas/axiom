# Attempt 002 — An empty answer rendered as silence

**Opened.** 2026-10-15, found only by running the real ingested chart.
**Closed.** 2026-10-15, commit "an empty answer is a refusal, and undated nodes
cannot crash the graph". Fixed.

**Hypothesis.** The pipeline is correct. If the model is deterministic where it
should be, the verifier checks every claim, and unsupported claims are suppressed,
then the output is safe by construction.

**How we tested it.** Benchmark metrics. 97.1% detection, 0.0% unsupported claims,
100% citation validity, 6/6 unanswerable questions refused. All green.

Then ran an actual ingested patient chart through `/api/ask` and asked a real
question:

> "Does this patient have a pulmonary embolism?"

**What actually happened.** The API returned `refused=false` with an empty
published list.

The commit states why that matters more than the metric gap:

> "To a clinician that renders as silence, and silence reads as 'nothing to report'
> — the exact confident-negative this system exists to refuse."

This is the single most important defect in the project, and it is worth being exact
about it. The system had a `refused` boolean. The system had a guarantee that
unsupported claims are suppressed. And a suppressed claim, with no refusal flag set,
is not a refusal — it is an absence. The absence renders as nothing, and nothing, in
a clinical display, is a clean bill of health.

The safety property was implemented correctly and still failed, because safety at the
output boundary is not the same as safety at the data boundary. A verifier that
suppresses everything correctly produces an empty answer, and an empty answer was not
required to be marked as a refusal.

Every metric was green. The metric was measuring the verifier. The bug was in what
the caller did with the verifier's output.

### The second defect in the same commit

Undated facts from prose extraction crashed `series()` and `new_since_last_visit` on
a str/None comparison:

> "turning supported questions into spurious refusals and killing the creatinine
> trend."

The prose extractor reads "Creatinine rose 0.85 to 1.48" — which states no dates.
Crashing on that turned a *supported* question into a refusal, which is the opposite
error, and it silently deleted the creatinine trajectory, which is one of the four
temporal questions the architecture exists to answer.

Fixed by keeping undated observations in the graph and citable, but not placing them
on a timeline. A second instance of the same shape: a missing field should degrade a
capability, not destroy the record.

**Outcome.** Fixed. An empty answer is now a refusal.

### Why this one is the most valuable record in the repository

Not because it is the worst bug — the KeyError in `attempts/003` destroyed more data
— but because **the test suite could not have caught it**.

Every benchmark metric passed while this was live. The benchmarks assert about claims:
were they supported, do they cite, are they refused. This defect was in the
transformation from "no supported claims" to "what the API returns", which is below
the level any of those assertions observe.

A green suite and a live safety hole coexisted for as long as nobody asked a real
question of a real chart.

**What this attempt is a reminder of**

**Test what the user sees, not only what the component produced.**

The verifier's contract was upheld perfectly. The contract was simply incomplete: it
promised unsupported claims would not be published, and said nothing about what
should happen when none survived. Silence is not a safe default in a domain where
absence reads as a negative finding.

The general form: **any system whose failure mode is "produce nothing" needs to
distinguish "nothing to say" from "nothing found".** In most contexts they are the
same. In this one they are opposites.

### The rule this produced

An empty answer is a refusal. Silence is not an acceptable output in a clinical
display, because silence is indistinguishable from a clean result.