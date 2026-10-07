# AXIOM — Application Build Plan

**Status:** plan only, nothing built. This document defines what the UI is,
what it renders, who builds it, in what order, and what "done" means.

---

## 1. The architecture decision

**Build a single self-contained HTML file. No server, no build step, no npm.**

Rationale, in priority order:

1. **It cannot break on stage.** No install, no server start, no port conflict,
   no dependency resolution. You double-click `index.html` in a browser and the
   demo runs. On a hackathon stage with unknown wifi and a borrowed HDMI
   adapter, this is the single highest-value property a demo surface can have.
2. **No network dependency at runtime.** The data is inlined at build time.
3. **The data already exists.** `AxiomPipeline.answer()` returns everything a
   UI needs. This is a rendering job, not a rebuild.
4. **Cost:** no live interactivity across arbitrary queries. You accept a fixed
   but fully scripted demo path in exchange for zero failure modes. For a
   90-second pitch with a rehearsed sequence, that trade is correct.

### Explicitly rejected

| Option | Why not |
|---|---|
| Streamlit | Not installed; `pip` unavailable in this environment. Adds a server process that must start before the demo |
| Flask + JS | Server again. Same failure mode, more code |
| Next.js + Recharts | `npm install` before the demo is a coin flip on hackathon wifi |

### Reconsider only if

The judges' rubric explicitly rewards a working product over a demo. That is
unlikely for a pitch-format hackathon, and it is not worth the risk.

---

## 2. Build shape

Two commands, that's the whole toolchain.

```bash
python3 -m axiom.demo --json > fixture.json   # pipeline → fixture
python3 build_ui.py                           # fixture → index.html (inlined)
```

`build_ui.py` reads the fixture and writes one `index.html` with the data in a
`<script>` tag. No fetch, no CORS, no server. Output lands in `/workspace`.

**Why inline rather than `fetch()`:** browsers block `fetch` on `file://` due
to CORS. Inlining sidesteps that entirely.

---

## 3. Screen inventory

Five screens. Each maps to a beat in the 90-second pitch.

| # | Screen | Pitch beat | Purpose |
|---|---|---|---|
| S1 | Patient chart | 0:00 | Header, attention queue, permanent safety boundary |
| S2 | Evidence card | 0:10 | One claim expanded: text, citations, trend, raw record |
| S3 | Timeline scrubber | 0:25 | Clinical graph as a scrubable timeline |
| S4 | **Refusal** | 0:40 | The turn. The system declines, names what's missing, routes it |
| S5 | Benchmark + audit | 0:55 | Measured results, and the one we missed. Audit drawer |

### S1 — Patient chart

- Header: name, DOB, sex, MRN. Permanent banner: *"AI assist — not a diagnosis.
  Clinician decides."* Not dismissible. This is the safety boundary and it is
  chrome, not a popup.
- **Attention queue:** 3–5 findings ranked by severity and recency. This is the
  product — it replaces 40 minutes of chart archaeology.
- Each queue item: severity chip, one-line finding, calibrated score.
- Query bar at the bottom for the scripted demo questions.

### S2 — Evidence card

The credibility screen. Clicking a queue item expands:

- The full claim text
- **Citation chips** — clickable; each shows the node ID and opens the raw record
- Lab trend as an inline SVG line chart with reference band
- The verification verdict and reason string
- The raw source record for every cited node

Every factual sentence has a visible citation. No citation, no sentence.

### S3 — Timeline scrubber

Encounters on a horizontal axis, events plotted by type. Colour-coded node
types, edges visible on hover. Makes temporal reasoning *visible* rather than
magical — this is the slide-5 argument rendered.

### S4 — Refusal  ← the beat that wins

- The question, in the query bar
- The refusal, in confident present-tense prose. Not an error state.
- **What is missing** — the specific schema gap
- **Where it routed** — escalation target
- Audit ref

Copy for the demo:

> Q: What is this patient's blood type?
> **REFUSED** — No blood-bank resource exists in this record schema.
> Routed to: records request
> *Absence of documentation is not absence of the condition.*

### S5 — Benchmark + audit

- The six measured metrics from `bench.py`
- The robustness sweep as a bar chart — **show this, not the headline 97%**
- The "here's what we missed" panel: 3 of 105 planted findings undetected,
  named and counted
- Audit drawer: any claim → cited nodes → source record, two clicks

---

## 4. Data contract

The Python side emits this. The UI consumes it and renders nothing else.

```json
{
  "patient": { "demographics": {}, "planted": [] },
  "graph":   { "nodes": [], "edges": [[from, to, type]] },
  "scenes": [
    {
      "id": "beat_1",
      "beat": "0:00",
      "title": "Patient chart",
      "query": "Is there any sign the kidney function is worsening?",
      "published": [
        {
          "claim_id": "c_01",
          "text": "Serum creatinine rose from 0.85 to 1.69 mg/dL...",
          "claim_type": "lab_trend",
          "cited_nodes": ["lab_00085", "lab_00093"],
          "calibrated_score": 1.0,
          "verdict": "ENTAILED",
          "source_records": [ { "id": "lab_00085", "raw": {...} } ]
        }
      ],
      "abstained": [],
      "audit_ref": "audit/0001"
    }
  ],
  "benchmark": { "detection_rate": 0.971, "robustness_sweep": [] },
  "limitations": ["..."]
}
```

**Contract rule:** the UI must never compute a clinical number. Every value on
screen is either copied from the fixture or a bar width derived from a fixture
number. If you find yourself calculating something in JavaScript, it belongs in
Python.

---

## 5. Build order

Ordered by pitch dependency. S1–S2 first: they carry beats 1 and 2. S4 before
S3 or S5, because it is the beat that differentiates.

| Step | Work | Est. | Depends on |
|---|---|---|---|
| 1 | `build_ui.py` reads fixture, writes inlined HTML shell | 30 min | fixture exists |
| 2 | S1 chart + attention queue | 60 min | 1 |
| 3 | S2 evidence card + citation click-through | 90 min | 2 |
| 4 | **S4 refusal screen** | 45 min | 1 |
| 5 | S5 benchmark + limitations panel | 60 min | 1 |
| 6 | S3 timeline scrubber | 90 min | 2 |
| 7 | Styling pass to match deck | 60 min | all |
| 8 | Offline verification on stage hardware | 30 min | all |

Total ≈ 7.5 hours. Steps 1–5 are 4.75 hours and cover four of five beats.
**If you run out of time, cut step 6** — the timeline is the only screen that
is not load-bearing for the pitch.

---

## 6. Acceptance criteria

Done means all of these pass. Test each explicitly; do not assume.

- [ ] `index.html` opens by double-click, offline, wifi off
- [ ] Opens in Chrome, Firefox and Safari without console errors
- [ ] Every published claim renders a clickable citation
- [ ] Every citation opens the correct raw source record
- [ ] The refusal screen renders from the real pipeline response, not hardcoded copy
- [ ] Safety boundary visible on every screen, not dismissible
- [ ] Benchmark numbers read from the fixture, never hardcoded
- [ ] The limitations panel is visible on the benchmark screen
- [ ] Renders at 1920×1080 and 1366×768 without clipping
- [ ] Full 90-second walkthrough completes in under 2 minutes

---

## 7. Roles

| Who | Owns |
|---|---|
| Frontend | Steps 1–7, acceptance checklist |
| Pipeline | Fixture export, `build_ui.py` |
| Benchmark | S5 accuracy, keeps the fixture honest |
| Floating | Offline fallback, takes the first-priority defect |

The floating role exists because in practice nobody owns reliability until
something breaks. Assign it explicitly.

---

## 8. UI-specific risks

| Risk | Mitigation |
|---|---|
| Fixture goes stale after a pipeline change | Regenerate the fixture as part of every commit. Never hand-edit `index.html` |
| Styling eats 3 hours | Hard-cap at 60 min (step 7). The demo reads on unstyled HTML |
| Screen 3 timeline takes too long | Cut it. Beats still complete |
| Fixture leaks something PHI-shaped | Synthetic only. But grep the fixture for names/DOBs before the pitch — a reviewer spotting a "real-looking" identifier undermines the no-PHI claim |
| Hardcoded numbers drift from `bench.py` | Fixture-driven only. Acceptance criterion above |
| Judge asks to try a different query | The scripted path is fixed. Answer honestly: *"the current build demonstrates one path; the pipeline accepts arbitrary questions."* Do not fake generality |

---

## 9. Out of scope

- Editing or writing to the record (read-only is a safety property)
- Real patient data (there is nothing to breach, and saying so is a strength)
- Multi-patient list, login, persistence — this is a demo surface, not an EMR
- Mobile layout. Judges will view on a projector

---

## 10. Definition of done

The demo runs offline, end to end, in under two minutes, with every number on
screen traceable to `bench.py`, every claim traceable to a source record, and
the limitations panel visible.

Not "it renders." Traceable.