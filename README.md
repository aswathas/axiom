# AXIOM

**An evidence-grounded clinical intelligence layer for electronic medical records.**

> "A clinical AI that always answers is unsafe. Ours refuses when the evidence
> does not support an answer — and we measure how often that happens."

District 04 — AI-Native EMR for Intelligent Clinical Assistance.
100% synthetic data. No real PHI at any point. Clinician-assist only.

---

## Run it

No install, no dependencies beyond the Python standard library.

```bash
python3 -m axiom.demo     # the 90-second pitch, end to end
python3 -m axiom.bench    # full metric report + robustness sweep
```

---

## The idea

Naive AI-on-EMR projects generate a fluent summary and trust it. That fails in a
specific, detectable way: there is no mechanism separating what the record
supports from what the model inferred. In a clinical setting that is not a bug,
it is the product defect.

AXIOM inverts it. Every claim is atomised, bound to the nodes that support it,
then checked by an **independent** entailment verifier that sees only the claim
and its evidence. Anything that fails is suppressed — not greyed out, not
footnoted, absent. When the record cannot support an answer at all, the system
refuses, names the missing evidence, and routes it to a human.

## Architecture

| Layer | Name | Role |
|---|---|---|
| 1 | Synthetic EHR generator | Plants findings of known type, severity and timestamp |
| 2 | Ingestion + normalisation | Units, codes, **negation detection** |
| 3 | Patient entity resolution | Blocking + weighted scoring across source systems |
| 4 | **Temporal clinical graph** | Time-stamped nodes, typed edges |
| 5 | Structured temporal retrieval | Graph traversals first, semantic search only inside the subgraph |
| 6 | **Verified claim generation** | Atomic claims + independent entailment check |
| 7 | **Calibrated abstention** | Isotonic calibration, per-claim-type thresholds |
| 8 | Audit + provenance | Every statement resolves to source in two clicks |

Layers 3–5 are what a vector-RAG project structurally cannot do. Four question
classes are not expressible over flat document chunks:

- *"What changed since the last visit?"* — temporal join across encounters
- *"Was this already known?"* — supersession reasoning
- *"What is the creatinine trajectory over 18 months?"* — series over one analyte
- *"Which diagnoses have no follow-up?"* — an anti-join in time

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

Degradation is graceful rather than cliff-edged. Present this curve, not the
headline number.

---

## Limitations — read before you show anyone these numbers

1. **The verifier is rule-based, not a model.** Every high score reflects
   deterministic checks against ground truth we generated ourselves. An LLM
   verifier would score materially lower.
2. **All data is synthetic and self-authored.** We wrote both the records and
   the answer key, so recall measures our own assumptions.
3. **High scores do not generalise to real clinical text.** Real records contain
   abbreviations, typos, scanned documents and coding conventions not modelled
   here. Treat this as a working baseline, never as a performance claim.
4. **The entity-resolution margin is thin (0.015).** The highest-scoring
   non-match sits just below the merge threshold. On real data this would need
   proper calibration and manual review for ambiguous pairs.
5. **RxNorm mapping is an illustrative subset**, not the authoritative release.

Publishing these limitations alongside the results is the point. A team that
volunteers the number it missed is demonstrating more engineering maturity than
one that reports only wins — and it is the only way the rest of the numbers are
believable.

## Scope boundary

**AXIOM does not diagnose and does not prescribe.** It surfaces evidence and
reasoning to a licensed clinician who decides. It is read-only. These are
safety and regulatory constraints, not missing features, and they appear as
permanent chrome in the UI rather than a dismissible banner.

## Clinical reference

LOINC and ICD-10 values are real. The RxNorm mapping is an illustrative subset.
Clinical interaction pairs are drawn from documented, well-known interactions
and are illustrative for demonstration only — **not for clinical use**.