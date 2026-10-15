# 02 — Options considered

**Date.** 2026-10-07

## Where should the language model sit in the pipeline

This is the decision the whole architecture turns on.

### Option A — the model does everything

Extract from the document, reason over it, write the answer. One call, one model.

**Rejected.** This is the thing being fixed. A single call mixes extraction,
inference and presentation, and once they are mixed there is nowhere to put the
check. Asking the model to be careful is not a verification step.

### Option B — the model for extraction, a rule for verification

Separate generation from checking, with a deterministic verifier that sees only
each atomised claim and its supporting evidence — not the model's reasoning, not
the document, not what it was asked.

**Chosen.** The verifier is deliberately blind to everything except the claim and
its evidence. That blindness is the property: it cannot be talked into agreeing by
a well-written prompt, because it never sees the prompt.

### Option C — a second LLM as verifier

Considered seriously and rejected on a ground the README states plainly:

> "Every high score reflects deterministic checks against known ground truth. An LLM
> verifier would score materially lower."

A second model shares the first model's blind spots and adds a latency cost and a
rate-limit cost. On a free, rate-limited tier that is not affordable, and it would
make the headline number dishonest.

### What was actually built

The README's stage table is the clearest statement of the decision:

| Stage | Owner | Fails how |
|---|---|---|
| PDF → text | `pypdf` | n/a |
| Lab / Rx extraction | **deterministic parser** | effectively never |
| Prose extraction | LLM | degrades to prose-only |
| Clinical graph | deterministic | never |
| **Query compilation** | **LLM — the only load-bearing call** | falls back to a rule planner |
| Verification | deterministic | never |
| Refusal | deterministic | never |

One load-bearing LLM call out of seven stages, with a rule planner as its fallback.
The reasoning:

> "A clinical system should not ask a language model to read `Potassium | 5.20 |
> mmol/L | 3.50 - 5.10 | H` when a regex reads it perfectly. Models handle prose;
> parsers handle structure."

## How should the comparison against simpler systems be made honest

### Option A — assert that a temporal graph beats chunk retrieval

**Rejected.** Unfalsifiable from outside, and the kind of claim the README
elsewhere refuses to make.

### Option B — build the strawman yourself

**Chosen.** `axiom/baseline_rag.py` is a competent, unrigourded chunk-retrieval
implementation, written specifically so the comparison is against a fair opponent
rather than a strawman the team also wrote:

> "We build `axiom/baseline_rag.py` — a competent, unrigged chunk-retrieval
> implementation — so the comparison on this point is honest rather than asserted."

Writing your own baseline costs days and it is the only way to know the baseline was
not quietly sabotaged.

## Where should clinical data come from

### Option A — scrape identifiable records from the open internet

**Rejected, and this is a regulatory refusal rather than a technical one:**

> "Identifiable patient records scraped from the open internet are either a breach
> already committed or were never de-identified; either way, processing them makes
> us a covered entity under HIPAA."

This one is worth reading twice. The reasoning is not "we couldn't." It is that the
data is either someone's breach or a lie about de-identification, and in both cases
touching it makes you a covered entity.

### Option B — MITRE Synthea or similar upstream generator

**Considered and rejected on honesty grounds.** Synthea would have been better data.
Using it would have meant the answer key was not written by the same hand as the
records. Instead:

> "Records are generated in-process from our own patient model... We wrote both the
> clinical records and the answer key, so recall measures *our pipeline against our
> own assumptions*."

Weaker claim, and the README says so above the results rather than in a footnote.

### Option C — generate in-process

**Chosen**, with the limitation published as limitation 2.

### Option D — real de-identified data via MIMIC-IV

Named in the README as the legitimate route for anyone whose project genuinely
needs it: credentialed, with a DUA, "worth the paperwork." Not available inside a
hackathon scope, and pretending otherwise would have been the easier lie.

## What was considered and never built

- **OCR and handwriting support.** Not implemented at all. Recorded as limitation 5.
- **A clinician confirmation step on ingest.** Cut for scope, and named as the first
  thing to add back — because once a bad value is a graph node, every downstream
  claim cites it confidently, and by then the graph *is* the truth the verifier
  checks against.
- **Authoritative RxNorm.** An illustrative subset only.