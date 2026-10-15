# 01 — The problem

**Date.** 2026-10-07

## The problem, in one paragraph

A clinical AI that always answers is unsafe. It fails in a specific, detectable
way: there is no mechanism separating what the record supports from what the model
inferred. In a clinical setting that is not a bug, it is the product defect.

Every clinical assistant in existence generates a fluent summary and trusts it. The
sentence "creatinine is mildly elevated, possibly related to dehydration" carries a
model's inference in it, phrased exactly like an observation, and a clinician
reading it at the end of a shift cannot tell which is which. Nothing in the output
marks the seam.

## What it costs

A hallucinated observation does not announce itself. It reads as a finding. A
clinician who acts on an inferred "renal impairment" that the record does not
support is acting on the model's reasoning rather than on the patient.

The failure is asymmetric in a way that makes it worse than an ordinary model error.
An obviously wrong answer gets caught. A wrong answer phrased exactly like the right
ones does not.

## What makes it hard to solve honestly

The obvious fix — "make the model more careful" — does not produce a guarantee.
Prompting for epistemic humility produces softer prose, not an audit trail. You
cannot verify a sentence by reading it, because the failure is precisely that the
sentence does not mark itself.

So the problem cannot be solved inside the generation step. It has to be solved by
separating generation from checking, and by making the check independent of
everything the generator believed.

## The scope this was built under

District 04 — AI-Native EMR for Intelligent Clinical Assistance. Hackathon
timeline, synthetic clinical data throughout, clinician-assist only.

That last constraint is doing real work and is worth stating plainly: **AXIOM does
not diagnose and does not prescribe.** It surfaces evidence and reasoning to a
licensed clinician who decides. These are safety and regulatory constraints, not
missing features, and they appear as permanent chrome in the UI rather than a
dismissible banner.

## A second problem, found later and worth naming

The first version of the README described the synthetic data as coming from an
upstream project. It did not. Commit `correct data provenance to reflect
self-generated synthetic clinical records` fixes it.

That is not a trivial correction. If you generate both the clinical records and the
answer key, recall measures your pipeline against your own assumptions — it proves
the pipeline recovers what you planted under your own rules, not that it generalises
to medicine. Both facts now appear as limitation 2 in the README, above the
results.