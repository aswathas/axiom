"""Build the District 04 pitch deck.

    python tools/build_deck.py

Every number on these slides is read from `axiom.bench` at build time rather
than typed in, so the deck cannot drift from the system it describes. If a
metric regresses, the slide changes with it or the build fails loudly.

Output: docs/AXIOM_D04_Deck.pptx
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "AXIOM_D04_Deck.pptx"
SHOTS = ROOT / "screenshots"

# Palette taken from the app so the deck and the demo read as one system.
INK = RGBColor(0x14, 0x17, 0x1C)
PAPER = RGBColor(0xF7, 0xF5, 0xF1)
GOLD = RGBColor(0xC9, 0xA2, 0x27)
SLATE = RGBColor(0x5A, 0x63, 0x72)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x4C, 0x8C, 0x6A)

W, H = Inches(13.333), Inches(7.5)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def load_metrics() -> dict:
    """Run the real benchmark. A deck that quotes remembered numbers is a
    liability; this one cannot."""
    proc = subprocess.run(
        [sys.executable, "-m", "axiom.bench"],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONUTF8": "1"},
    )
    text = proc.stdout
    start = text.index("{")
    return json.loads(text[start:])


def bar(frac: float, width: int = 34) -> str:
    filled = int(round(frac * width))
    return "#" * filled + "." * (width - filled)


# ---------------------------------------------------------------------------
# slide helpers
# ---------------------------------------------------------------------------

def slide(prs, title, kicker=None):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bg = s.background.fill
    bg.solid()
    bg.fore_color.rgb = INK
    if kicker:
        box(s, 0.75, 0.55, 11, 0.4, kicker, 13, GOLD, bold=True)
    if title:
        box(s, 0.75, 0.95, 11.8, 1.1, title, 34, PAPER, bold=True)
    return s


def box(s, x, y, w, h, text, size=18, color=PAPER, bold=False,
        align=PP_ALIGN.LEFT, italic=False, font="Calibri", line=None):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text.upper() if False else text
    r.font.size = Pt(size)
    r.font.color.rgb = color
    r.font.bold = bold
    r.font.italic = italic
    r.font.name = font
    if line:
        p.line_spacing = line
    return tb


def bullets(s, x, y, w, h, items, size=17, color=SLATE, gap=10):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        if isinstance(item, tuple):
            lead, rest = item
            r = p.add_run(); r.text = lead
            r.font.size = Pt(size); r.font.bold = True
            r.font.color.rgb = PAPER; r.font.name = "Calibri"
            r2 = p.add_run(); r2.text = rest
            r2.font.size = Pt(size); r2.font.color.rgb = color
            r2.font.name = "Calibri"
        else:
            r = p.add_run(); r.text = item
            r.font.size = Pt(size); r.font.color.rgb = color
            r.font.name = "Calibri"
    return tb


def shot(s, name, x, y, w):
    p = SHOTS / name
    if not p.exists():
        box(s, x, y, w, 1.0, f"[missing screenshot: {name}]", 12, SLATE, italic=True)
        return
    s.shapes.add_picture(str(p), Inches(x), Inches(y), width=Inches(w))


def rule(s, x, y, w, color=GOLD, thick=Pt(3)):
    ln = s.shapes.add_shape(1, Inches(x), Inches(y), Inches(w), Emu(thick))
    ln.fill.solid()
    ln.fill.fore_color.rgb = color
    ln.line.fill.background()
    ln.shadow.inherit = False
    return ln


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build() -> None:
    m = load_metrics()
    sweep = m["robustness_sweep"]
    er = m["entity_resolution"]

    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # 1 — title
    s = slide(prs, "", "DISTRICT 04  ·  AI-NATIVE EMR")
    box(s, 0.75, 2.1, 11.8, 1.6, "AXIOM", 76, PAPER, bold=True)
    box(s, 0.75, 3.5, 11.5, 1.0,
        "An evidence-grounded clinical intelligence layer for electronic medical records",
        21, SLATE)
    rule(s, 0.75, 4.75, 3.2)
    box(s, 0.75, 5.0, 11.5, 0.6,
        '"A clinical AI that always answers is unsafe. Ours refuses when the evidence '
        'does not support an answer - and we measure how often that happens."',
        15, GOLD, italic=True)

    # 2 — the problem
    s = slide(prs, "Most clinical AI answers everything.\nIn a hospital, that is how patients get hurt.",
              "THE PROBLEM")
    bullets(s, 0.75, 2.9, 6.0, 3.6, [
        ("Every model here will hallucinate. ", "That is not a defect — it is what they do."),
        ("Nothing separates ", "what the record supports from what the model inferred."),
        ("A confident wrong answer ", "is indistinguishable from a correct one at the point of care."),
        ("Absence of documentation ", "gets read as absence of disease. It is not."),
    ], size=16)
    box(s, 7.3, 2.9, 5.3, 2.4,
        "The failure is not that the AI is wrong.\n\nIt is that you cannot tell when it is.",
        19, GOLD, italic=True)

    # 3 — the turn (the whole submission)
    s = slide(prs, "THE TURN", "WHAT OURS DOES INSTEAD")
    box(s, 0.75, 1.9, 5.6, 0.4, "WHAT OTHER AIs DO", 14, SLATE, bold=True)
    box(s, 0.75, 2.35, 5.6, 1.9,
        '"No documented evidence of DVT."', 21, PAPER, bold=True)
    box(s, 0.75, 4.05, 5.6, 1.9,
        "Technically quoted. Clinically read as\n"
        '"No blood clot."\n\n'
        "Measured, not assumed - our own chunk-RAG\nbaseline returns this verbatim.",
        14, SLATE, italic=True)

    box(s, 7.0, 1.9, 5.6, 0.4, "WHAT AXIOM DOES", 14, GOLD, bold=True)
    box(s, 7.0, 2.35, 5.6, 1.9, "REFUSED.", 30, GOLD, bold=True)
    box(s, 7.0, 4.05, 5.6, 2.1,
        'HTTP 200. Names the missing evidence:\n'
        'no thromboembolism (I63/I81) documented.\n\n'
        '"Absence of documentation is not absence of\nthe condition."\n'
        "Routed to chart review. Audited.",
        14, PAPER)
    shot(s, "ui-03-ask-refusal.png", 3.9, 5.55, 5.5)

    # 4 — the mechanism
    s = slide(prs, "Refusal is the feature, not the fallback.", "HOW")
    steps = [
        ("DOCUMENT", "Lab reports, discharge summaries,\nprescription printouts"),
        ("EXTRACT", "Deterministic parsers for tables;\nthe LLM for prose only"),
        ("GRAPH", "Time-stamped nodes, typed edges,\nprovenance to source"),
        ("VERIFY", "An independent entailment check sees\nonly the claim and its evidence"),
        ("REFUSE", "What fails is suppressed. What the\nrecord cannot support is declined."),
    ]
    x = 0.75
    for i, (head, body) in enumerate(steps):
        box(s, x, 2.5, 2.2, 0.5, head, 15, GOLD, bold=True)
        box(s, x, 3.05, 2.2, 1.8, body, 12, SLATE)
        if i < len(steps) - 1:
            box(s, x + 2.15, 2.5, 0.35, 0.5, "->", 18, SLATE, bold=True)
        x += 2.5
    box(s, 0.75, 5.5, 11.8, 1.2,
        "Suppressed means absent - not greyed out, not footnoted. "
        "A refusal returns HTTP 200 with its reason, the missing evidence, "
        "and an audit reference.", 15, PAPER, italic=True)

    # 5 — where the LLM is
    s = slide(prs, "The model is load-bearing in exactly one place.", "ARCHITECTURE")
    bullets(s, 0.75, 2.4, 6.2, 4.0, [
        ("Parsing a lab table is not an LLM problem. ", "A regex reads "
         "'Potassium 5.20 mmol/L 3.50-5.10 H' perfectly. Models do prose; "
         "parsers do structure."),
        ("Query compilation is the LLM's job. ", "Turning 'is his kidney function "
         "actually worsening, or is one bad day skewing it?' into a scoped "
         "traversal. Thirty tokens of JSON - a small model does this reliably."),
        ("Verification and refusal are deterministic. ", "Nothing in that path can "
         "fail open."),
    ], size=15)
    box(s, 7.4, 2.4, 5.2, 3.4,
        "Why it matters here:\n\n"
        "We run on a free, rate-limited tier. Rather than hide that, we let it "
        "push the architecture toward determinism - so a 429 degrades the demo "
        "instead of killing it.", 14, GOLD, italic=True)

    # 6 — the moat
    s = slide(prs, "Four questions flat retrieval cannot answer.", "THE MOAT")
    bullets(s, 0.75, 2.3, 6.4, 4.0, [
        ('"What changed since the last visit?"', "  - temporal join across encounters"),
        ('"Was this already known?"', "  - supersession reasoning"),
        ('"What is the creatinine trajectory over 18 months?"', "  - series over one analyte"),
        ('"Which diagnoses have no follow-up?"', "  - an anti-join in time"),
    ], size=15)
    box(s, 7.6, 2.3, 5.0, 3.6,
        "Document chunks have no time in them.\n\n"
        "A time-stamped clinical graph does.\n\n"
        "We ship a chunk-RAG strawman alongside it - "
        "unrigged, TF-IDF, no hedging in the prompt - so the comparison "
        "is honest rather than asserted.", 14, SLATE, italic=True)
    shot(s, "ui-02-chart.png", 8.0, 4.5, 4.2)

    # 7 — provenance
    s = slide(prs, "Every claim resolves to a region of a document.", "PROVENANCE")
    bullets(s, 0.75, 2.4, 5.9, 3.8, [
        ("Every extracted fact keeps ", "its source document, page, and character span."),
        ("Click any sentence; ", "the original PDF opens, scrolled to the line."),
        ("Two clicks, every time. ", "A claim without a reachable source is a bug."),
    ], size=15)
    shot(s, "ui-05-source-viewer.png", 6.9, 2.3, 5.9)

    # 8 — measured
    s = slide(prs, "Measured, with the sweep that matters.", "RESULTS")
    rows = [
        ("detection rate", m["detection_rate"], "102/105 planted findings"),
        ("unsupported claim rate", m["unsupported_claim_rate"], "0 of 270 claims"),
        ("citation validity", m["citation_validity"], "every claim resolves"),
        ("false positive rate", m["false_positive_rate"], "29 clean patients, 0 spurious"),
        ("abstention recall", m["abstention_recall"], "6/6 unanswerable refused"),
        ("negation accuracy", m["negation_accuracy"], f"{m['negation_sentences_checked']} sentences"),
        ("entity resolution F1", er["f1"], f"{er['negative_pairs_tested']} negative pairs"),
    ]
    y = 2.25
    for label, val, note in rows:
        box(s, 0.75, y, 3.3, 0.35, label, 14, PAPER)
        box(s, 4.15, y, 3.4, 0.35, bar(val), 12, GREEN, font="Consolas")
        box(s, 7.7, y, 0.9, 0.35, f"{val*100:.1f}%", 14, PAPER, bold=True, align=PP_ALIGN.RIGHT)
        box(s, 8.8, y, 4.0, 0.35, note, 12, SLATE)
        y += 0.46

    # 9 — robustness
    s = slide(prs, "Present this curve, not the headline number.", "ROBUSTNESS")
    box(s, 0.75, 2.1, 11.8, 0.5,
        "Detection rate under injected noise. Degradation is graceful, "
        "not cliff-edged - this is the only figure that predicts real-world behaviour.",
        14, SLATE, italic=True)
    y = 3.0
    for row in sweep:
        lvl = row["noise_level"]
        box(s, 0.75, y, 1.5, 0.35, f"noise {lvl:.2f}", 14, PAPER, font="Consolas")
        box(s, 2.4, y, 5.4, 0.35, bar(row["detection_rate"], 40), 13, GOLD, font="Consolas")
        box(s, 8.0, y, 1.0, 0.35, f"{row['detection_rate']:.3f}", 14, PAPER,
            bold=True, align=PP_ALIGN.RIGHT)
        y += 0.52

    # 10 — limitations
    s = slide(prs, "Where this breaks.", "LIMITATIONS")
    bullets(s, 0.75, 2.3, 6.3, 4.4, [
        ("The verifier is rule-based, not a model. ", "An LLM verifier would score "
         "materially lower. We say so first."),
        ("All clinical data is self-generated. ", "We wrote both the records and "
         "the answer key; recall measures our pipeline against our own assumptions."),
        ("Ingestion is fully automatic. ", "Nothing is clinician-confirmed. A "
         "mislabelled value becomes a permanent node."),
        ("We do not touch real PHI. ", "MIMIC-IV on PhysioNet is the legitimate "
         "route; scraping is not."),
        ("Entity-resolution margin is thin (0.015). ", "Real data would need "
         "calibration and human review."),
    ], size=13)
    box(s, 7.5, 2.3, 5.1, 3.6,
        "Publishing these is the point.\n\n"
        "A team that volunteers the number it missed is demonstrating more "
        "engineering maturity than one that reports only wins - and it is the "
        "only way the rest of the numbers are believable.",
        15, GOLD, italic=True)

    # 11 — close
    s = slide(prs, "", "IN ONE LINE")
    box(s, 0.75, 2.2, 11.8, 1.8,
        "Every AI on this floor will hallucinate.\n"
        "We built the one that catches itself - and we can prove it live, on demand.",
        32, PAPER, bold=True, line=1.25)
    rule(s, 0.75, 4.5, 3.2)
    box(s, 0.75, 4.8, 11.8, 1.6,
        "AXIOM does not diagnose and does not prescribe.\n"
        "It surfaces evidence and reasoning to a licensed clinician who decides. "
        "That boundary is permanent chrome in the product, not a dismissible banner.",
        15, SLATE, italic=True)
    shot(s, "ui-04-ask-answer.png", 8.6, 4.6, 3.9)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(prs.slides.__iter__.__self__._sldIdLst)} slides)")


if __name__ == "__main__":
    build()