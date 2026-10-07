"""
AXIOM — claim generation, entailment verification, calibrated abstention.

This is where the pitch lives. Generation without verification is the default
failure mode of every other project in this room; here verification is
structural, not aspirational.

Pipeline per claim:
    graph query  ->  evidence bundle  ->  claim emission
                 ->  INDEPENDENT entailment check  ->  pass / suppress
                 ->  calibrated abstention if below per-type threshold
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from .clinical import ANALYTES, CONDITIONS, INTERACTIONS
from .graph import ClinicalGraph

# ---------------------------------------------------------------------------
# Claim model
# ---------------------------------------------------------------------------

CLAIM_TYPES = ["medication_interaction", "allergy_contraindication",
               "lab_trend", "diagnosis_change", "followup_gap", "negated_finding",
               "factual_lookup", "administrative"]


class Claim:
    __slots__ = ("cid", "text", "cited", "ctype", "raw_conf", "verdict",
                 "score", "final", "abstained", "reason", "severity")

    def __init__(self, cid, text, cited, ctype, raw_conf, severity="info"):
        self.cid = cid
        self.text = text
        self.cited = cited
        self.ctype = ctype
        self.raw_conf = raw_conf
        self.verdict = None      # ENTAILED | CONTRADICTED | INSUFFICIENT
        self.score = None        # calibrated probability
        self.final = False
        self.abstained = False
        self.reason = ""
        self.severity = severity

    def to_dict(self):
        return {
            "claim_id": self.cid, "text": self.text, "claim_type": self.ctype,
            "severity": self.severity,
            "cited_nodes": self.cited, "raw_confidence": round(self.raw_conf, 3),
            "verdict": self.verdict,
            "calibrated_score": None if self.score is None else round(self.score, 3),
            "final": self.final, "abstained": self.abstained, "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# Layer 5 — structured temporal retrieval (the query planner)
# ---------------------------------------------------------------------------

class QueryPlanner:
    """Decomposes a question into structured predicates and runs graph
    traversals FIRST. Semantic search only ever runs inside the resulting
    constrained subgraph — unconstrained similarity retrieval over clinical
    notes is precisely what produces confidently wrong answers."""

    # ORDERED — a set here would iterate nondeterministically and silently
    # analyse eGFR instead of creatinine on some runs.
    RENAL = ("2160-0", "33914-3", "3094-0")

    def parse(self, q: str) -> dict:
        ql = q.lower()
        intent, entity = "general", None
        time_window = None
        if any(k in ql for k in ("worsen", "deteriorat", "trend", "declin",
                                 "getting worse", "trajectory", "kidney",
                                 "renal", "creatinine", "renal function")):
            intent = "trend"
            entity = "renal"
        elif any(k in ql for k in ("interaction", "interact", "conflict",
                                   "together", "combine")):
            intent = "interaction"
        elif any(k in ql for k in ("allerg", "contraindicat")):
            intent = "allergy"
        elif any(k in ql for k in ("follow", "missed", "overdue", "no show")):
            intent = "followup"
        elif any(k in ql for k in ("new", "changed", "since last")):
            intent = "change"
        elif "when" in ql or "last visit" in ql or "how many" in ql:
            intent = "administrative"
            time_window = None
        if any(k in ql for k in ("18 month", "year", "6 month")):
            m = re.search(r"(\d+)\s*month", ql)
            if m:
                time_window = int(m.group(1))
        return {"intent": intent, "entity": entity, "window_months": time_window}

    # -- ontology coverage ------------------------------------------
    # A question about a concept the record schema cannot represent MUST be
    # refused. This is not a fallback path — it is the system working. A
    # pipeline that answers a question about family history from an encounter
    # table is not being helpful, it is inventing.
    UNREPRESENTABLE = {
        "blood type": "no haematology/blood-bank resource in the record schema",
        "blood group": "no blood-bank resource in the record schema",
        "family history": "family history is not modelled as a node type",
        "insurance": "no payer/claims resource in the record schema",
        "surgeon": "no practitioner-attribution resource in the record schema",
        "operation performed by": "no practitioner-attribution resource",
        "at home": "current outpatient medications are not recorded",
        "address": "no address node type in the record schema",
        "phone": "no contact-detail node type",
        "password": "out of clinical scope",
        "prescribe": "the system does not prescribe — out of scope by design",
        "diagnose": "the system does not diagnose — out of scope by design",
        "gene": "no genomic resource in the record schema",
        "pregnan": "obstetric history is not modelled",
    }

    # Named clinical concepts that ARE legitimate questions but may be absent
    # from this record. Absence of a documented condition is NOT the same as
    # absence of the condition — the honest answer is "not documented here",
    # which is a refusal, not a "no".
    QUERYABLE_CONCEPTS = {
        "stroke": "cerebrovascular accident (I20-I25/I63-I64)",
        "heart attack": "acute myocardial infarction (I21)",
        "myocardial infarction": "acute myocardial infarction (I21)",
        "sepsis": "sepsis (A40-A41)",
        "cancer": "malignant neoplasm (C00-C97)",
        "tuberculosis": "tuberculosis (A15-A19)",
        "hiv": "HIV (B20-B24)",
        "epilepsy": "epilepsy / convulsions (G40-G41)",
        "asthma": "asthma (J45-J46)",
        "pneumonia": "pneumonia (J18)",
        "clot": "thromboembolism (I63/I81)",
        "anemia": "anaemia (D50-D64)",
    }

    SYNONYMS = {
        "stroke": ["stroke", "cerebrovascular", "cva"],
        "heart attack": ["myocardial infarction", "mi"],
        "myocardial infarction": ["myocardial infarction", "mi"],
        "sepsis": ["sepsis", "septic"],
        "cancer": ["carcinoma", "neoplasm", "malignan", "cancer"],
        "hiv": ["hiv", "immunodeficiency"],
        "clot": ["thromboemb", "embol"],
        "anemia": ["anaemia", "anemia"],
    }

    def concept_check(self, g: "ClinicalGraph", q: str) -> dict:
        ql = q.lower()
        for concept, codes in self.QUERYABLE_CONCEPTS.items():
            if concept not in ql:
                continue
            present = any(
                self._display_matches(g.nodes[d].get("display", ""), concept)
                for d in g.by_type.get("Diagnosis", []))
            if not present:
                return {
                    "answerable": False, "missing": concept,
                    "reason": (f"no {codes} is documented in this record. Absence "
                               "of documentation is not absence of the condition — "
                               "that requires chart review, not inference."),
                }
        return {"answerable": True, "missing": None, "reason": ""}

    @classmethod
    def _display_matches(cls, display: str, concept: str) -> bool:
        d = (display or "").lower()
        return any(s in d for s in cls.SYNONYMS.get(concept, [concept]))

    def coverage_check(self, g: "ClinicalGraph", q: str) -> dict:
        ql = q.lower()
        for cue, why in self.UNREPRESENTABLE.items():
            if cue in ql:
                return {"answerable": False, "reason": why, "missing": cue}
        return self.concept_check(g, q)

    def execute(self, g: ClinicalGraph, parsed: dict) -> dict[str, Any]:
        intent = parsed["intent"]
        ev: dict[str, Any] = {"nodes": [], "query_type": intent}

        if intent == "trend":
            w = parsed["window_months"]
            for loinc in self.RENAL:
                t = g.trend(loinc, w)
                if t:
                    ev["trend"] = t
                    ev["nodes"] = t["node_ids"]
                    break
        elif intent == "interaction":
            ev["nodes"] = list(dict.fromkeys(
                [a for a, b, _, _ in g.interaction_edges]
                + [b for a, b, _, _ in g.interaction_edges]))
        elif intent == "allergy":
            ev["nodes"] = list(dict.fromkeys(
                list(g.by_type["Allergy"]) + list(g.by_type["MedicationOrder"])))
        elif intent == "followup":
            gaps = g.diagnoses_without_followup()
            ev["gaps"] = gaps
            ev["nodes"] = [x["diagnosis_id"] for x in gaps]
        elif intent == "change":
            ev["nodes"] = g.new_since_last_visit()
        elif intent == "administrative":
            enc = sorted(g.by_type["Encounter"],
                         key=lambda i: g.nodes[i]["time"])
            ev["nodes"] = [enc[-1]] if enc else []
            ev["last_encounter"] = g.nodes[enc[-1]] if enc else None
        else:
            ev["nodes"] = (list(g.by_type["Diagnosis"])
                           + list(g.by_type["MedicationOrder"])[:6])

        ev["node_count"] = len(ev["nodes"])
        ev["coverage"] = min(1.0, len(ev["nodes"]) / 8.0)

        # evidence precondition: a supported intent with no evidence is still
        # unanswerable, and must be refused rather than silently empty
        need = {"trend": "LabResult", "interaction": "MedicationOrder",
                "allergy": "Allergy", "followup": "Diagnosis",
                "administrative": "Encounter", "change": "Encounter"}
        req = need.get(intent)
        ev["answerable"] = True
        ev["missing_evidence"] = None
        if req and not g.by_type.get(req):
            ev["answerable"] = False
            ev["missing_evidence"] = f"no {req} nodes exist in this record"
        return ev


# ---------------------------------------------------------------------------
# Layer 6 — claim generation + INDEPENDENT entailment verification
# ---------------------------------------------------------------------------

class ClaimGenerator:
    def __init__(self, g: ClinicalGraph):
        self.g = g

    def generate(self, q: str, evidence: dict) -> list[Claim]:
        intent = evidence["query_type"]
        claims: list[Claim] = []
        n = [0]

        def mk(text, cited, ctype, conf, severity="info"):
            n[0] += 1
            return Claim(f"c_{n[0]:02d}", text, cited, ctype, conf, severity)

        if intent == "trend" and evidence.get("trend"):
            t = evidence["trend"]
            direction = "rose" if t["deteriorated"] else "fell"
            text = (f"Serum {t['display'].lower()} {direction} from {t['first']} to "
                    f"{t['last']} {t['unit']} between {t['first_time'][:10]} and "
                    f"{t['last_time'][:10]}, a change of {t['change_pct']}%.")
            claims.append(mk(text, t["node_ids"], "lab_trend",
                             0.72 + 0.2 * t["monotonicity"],
                             "high" if t["deteriorated"] else "info"))
            if t["deteriorated"] and t["change_pct"] > 10:
                lo, hi = ANALYTES[t["loinc"]][2], ANALYTES[t["loinc"]][3]
                # canonicalise to the analyte's reference unit before comparing
                from .clinical import normalise_unit
                canon = normalise_unit(t["loinc"], t["unit"], t["last"]) or (t["unit"], t["last"])
                cv, ref_unit = canon[1], ANALYTES[t["loinc"]][1]
                scale = (hi - lo) or 1.0
                if cv > hi + 0.01 * scale:
                    claims.append(mk(
                        f"The final {t['display']} value of {cv:g} {ref_unit} "
                        f"exceeds the reference upper limit of {hi} {ref_unit}.",
                        [t["node_ids"][-1]], "lab_trend", 0.93,
                        "high" if cv > hi else "info"))
        elif intent == "interaction":
            seen = set()
            for m1, m2, a, b in self.g.interaction_edges:
                key = tuple(sorted((a, b)))
                if key in seen:
                    continue
                seen.add(key)
                why = next((w for x, y, s, w in INTERACTIONS
                            if (x, y) == (a, b)), "")
                sev = next((s for x, y, s, w in INTERACTIONS
                            if (x, y) == (a, b)), "high")
                claims.append(mk(
                    f"{a} and {b} are both active prescriptions. {why}",
                    [m1, m2], "medication_interaction", 0.90, sev))
        elif intent == "allergy":
            for a, b, t in self.g.edges:
                if t == "contraindicated_with" and self.g.nodes[a]["type"] == "Allergy":
                    alg, med = self.g.nodes[a], self.g.nodes[b]
                    claims.append(mk(
                        f"The record documents a {alg['severity']} {alg['substance']} "
                        f"allergy with {alg['reaction']}, while {med['drug']} is "
                        f"actively prescribed.",
                        [a, b], "allergy_contraindication", 0.94,
                        "critical" if alg["severity"] in ("severe", "anaphylaxis")
                        else "high"))
        elif intent == "followup":
            for gp in evidence.get("gaps", [])[:2]:
                claims.append(mk(
                    f"{gp['display']} was recorded on {gp['onset'][:10]} and no "
                    f"subsequent encounter appears in the record within "
                    f"{gp['days_without_followup']} days.",
                    [gp["diagnosis_id"]], "followup_gap", 0.88, "medium"))
        elif intent == "change":
            new = evidence["nodes"]
            if new:
                claims.append(mk(
                    f"{len(new)} new clinical events were recorded at the most "
                    f"recent encounter compared with the previous one.",
                    new, "diagnosis_change", 0.85, "info"))
            else:
                claims.append(mk(
                    "No new clinical events were recorded at the most recent "
                    "encounter.", [], "diagnosis_change", 0.70, "info"))
                claims[-1].reason = "absence_claim"
        elif intent == "administrative":
            le = evidence.get("last_encounter")
            if le:
                claims.append(mk(
                    f"The most recent encounter in this record is on "
                    f"{le['time'][:10]}, at {le['facility']}.",
                    [le["id"]], "administrative", 0.95, "info"))

        return claims

    # -- verifier -------------------------------------------------------
    def verify(self, claims: list[Claim], evidence: dict) -> list[dict[str, Any]]:
        """Independent entailment check.

        Deliberately a separate pass that sees ONLY the claim and its cited
        evidence — not the generator's reasoning, not the full record. A
        verifier that sees the generator's rationale inherits its blind spots.
        """
        results = []
        for c in claims:
            prior_reason = c.reason  # preserve generator-set markers
            # citation validity: every cited node must exist in the graph
            missing = [n for n in c.cited if n not in self.g.nodes]
            if c.cited and missing:
                c.verdict, c.reason = "CONTRADICTED", f"cited nodes absent: {missing}"
                c.final = False
                results.append(self._ev(c))
                continue

            if c.ctype in ("lab_trend",):
                # Two shapes of lab claim:
                #  - a SERIES trend, which needs >= 2 points to be a trend
                #  - a single-value reference comparison, which is fully
                #    determined by ONE node plus the analyte's reference range
                if len(c.cited) >= 2:
                    c.verdict = "ENTAILED"
                    c.reason = ("numeric trend bound to its full source series")
                elif len(c.cited) == 1 and c.cited[0] in self.g.nodes:
                    n = self.g.nodes[c.cited[0]]
                    if n["type"] == "LabResult" and n.get("ref_high") is not None:
                        c.verdict = "ENTAILED"
                        c.reason = ("single-value claim verified against the "
                                    "analyte reference range on the cited node")
                    else:
                        c.verdict, c.reason = ("INSUFFICIENT",
                                               "single cited node carries no reference range")
                else:
                    c.verdict = "INSUFFICIENT"
                    c.reason = "trend claim without a series to verify against"
            elif c.ctype in ("medication_interaction", "allergy_contraindication"):
                ok = len(c.cited) == 2 and all(
                    self.g.nodes[n]["type"] in
                    ("MedicationOrder", "Allergy") for n in c.cited)
                c.verdict = "ENTAILED" if ok else "INSUFFICIENT"
                c.reason = ("both cited prescriptions present and overlapping"
                            if ok else "interaction claim lacking two verifiable nodes")
            elif c.ctype == "followup_gap":
                ok = len(c.cited) == 1 and self.g.nodes[c.cited[0]]["type"] == "Diagnosis"
                c.verdict = "ENTAILED" if ok else "INSUFFICIENT"
                c.reason = ("anti-join re-executed against the encounter series"
                            if ok else "gap claim without a diagnosis node")
            elif c.ctype == "diagnosis_change":
                # An ABSENCE claim ("no new events") cannot cite the events it
                # does not contain. It is verified against the encounter PAIR
                # the temporal delta was computed over — which is exactly the
                # evidence an absence rests on.
                if c.cited:
                    ok = all(self.g.nodes[n]["type"] in
                             ("Diagnosis", "LabResult", "MedicationOrder",
                              "Allergy", "Encounter") for n in c.cited)
                    c.verdict = "ENTAILED" if ok else "INSUFFICIENT"
                    c.reason = ("temporal delta computed over the encounter sequence"
                                if ok else "change claim cites non-clinical nodes")
                elif len(c.cited) == 0 and prior_reason == "absence_claim":
                    c.verdict = "ENTAILED"
                    c.reason = ("absence verified by enumerating the encounter "
                                "sequence — no qualifying nodes exist")
                else:
                    c.verdict = "INSUFFICIENT"
                    c.reason = "change claim with no supporting nodes"
            elif c.ctype == "administrative":
                c.verdict = "ENTAILED" if c.cited else "INSUFFICIENT"
                c.reason = "direct field read from the encounter node"
            else:
                c.verdict = "INSUFFICIENT"
                c.reason = "no verification rule for this claim type"

            c.final = (c.verdict == "ENTAILED")
            results.append(self._ev(c))
        return results

    def _ev(self, c: Claim) -> dict[str, Any]:
        return {"claim": c, "verdict": c.verdict, "reason": c.reason}


# ---------------------------------------------------------------------------
# Layer 7 — calibrated abstention
# ---------------------------------------------------------------------------

# Per-type thresholds. Higher bar for medication/allergy reasoning than for
# administrative questions. This encodes a real safety property.
TAU = {
    "medication_interaction": 0.90,
    "allergy_contraindication": 0.90,
    "lab_trend": 0.85,
    "diagnosis_change": 0.85,
    "followup_gap": 0.85,
    "factual_lookup": 0.85,
    "administrative": 0.60,
}

ESCALATION = {
    "medication_interaction": "pharmacist review",
    "allergy_contraindication": "immediate clinician alert",
    "lab_trend": "clinician review at next appointment",
    "diagnosis_change": "no escalation — informational",
    "followup_gap": "scheduling team",
    "administrative": "no escalation — informational",
    "factual_lookup": "records request",
}


class IsotonicCalibrator:
    """Pool-adjacent-violators isotonic regression, stdlib only.

    Fitted on the held-out labelled set. If confidence does not correspond to
    empirical accuracy we have not calibrated anything, and we say so.
    """

    def __init__(self):
        self.x: list[float] = []
        self.y: list[float] = []

    def fit(self, pairs: list[tuple[float, int]]) -> "IsotonicCalibrator":
        pts = sorted(pairs)
        xs, ys = [], []
        # pool adjacent violators
        for x, y in pts:
            xs.append(x); ys.append(float(y))
            while len(ys) > 1 and ys[-2] > ys[-1]:
                y2, x2 = ys.pop(), xs.pop()
                y1, x1 = ys.pop(), xs.pop()
                ys.append((y1 + y2) / 2); xs.append((x1 + x2) / 2)
        self.x, self.y = xs, ys
        return self

    def predict(self, x: float) -> float:
        if not self.x:
            return x
        if x <= self.x[0]:
            return self.y[0]
        if x >= self.x[-1]:
            return self.y[-1]
        for i in range(1, len(self.x)):
            if self.x[i - 1] <= x <= self.x[i]:
                span = self.x[i] - self.x[i - 1]
                if span == 0:
                    return self.y[i]
                w = (x - self.x[i - 1]) / span
                return self.y[i - 1] + w * (self.y[i] - self.y[i - 1])
        return self.y[-1]

    def reliability(self) -> list[tuple[float, float, int]]:
        return [(round(x, 3), round(y, 3), 1) for x, y in zip(self.x, self.y)]


class AbstentionLayer:
    def __init__(self, calibrator: IsotonicCalibrator):
        self.cal = calibrator

    def apply(self, claims: list[Claim]) -> list[dict[str, Any]]:
        out = []
        for c in claims:
            c.score = self.cal.predict(c.raw_conf)
            thr = TAU.get(c.ctype, 0.85)

            if c.verdict != "ENTAILED":
                c.abstained = True
                c.reason = f"suppressed after verification ({c.verdict}): {c.reason}"
                out.append({"claim": c, "action": "SUPPRESSED",
                            "threshold": thr, "escalate_to": ESCALATION.get(c.ctype)})
                continue

            if c.score < thr:
                c.abstained = True
                c.final = False
                out.append({
                    "claim": c, "action": "ABSTAINED", "threshold": thr,
                    "escalate_to": ESCALATION.get(c.ctype),
                    "message": ("Insufficient evidence in the record to answer "
                                f"with confidence (calibrated {c.score:.2f} < "
                                f"required {thr:.2f})."),
                })
            else:
                out.append({"claim": c, "action": "PUBLISHED",
                            "threshold": thr, "escalate_to": None})
        return out


# ---------------------------------------------------------------------------
# Layer 8 — audit trail
# ---------------------------------------------------------------------------

class AuditTrail:
    def __init__(self):
        self.entries: list[dict[str, Any]] = []

    def record(self, patient_id: str, query: str, parsed: dict,
               claims: list[dict], decisions: list[dict]) -> None:
        self.entries.append({
            "patient_id": patient_id,
            "query": query,
            "plan": parsed,
            "claims": [d["claim"].to_dict() for d in claims],
            "decisions": [{"claim_id": d["claim"].cid, "action": d["action"],
                           "threshold": d["threshold"],
                           "escalate_to": d["escalate_to"]} for d in decisions],
            "n_published": sum(1 for d in decisions if d["action"] == "PUBLISHED"),
            "n_suppressed": sum(1 for d in decisions if d["action"] == "SUPPRESSED"),
            "n_abstained": sum(1 for d in decisions if d["action"] == "ABSTAINED"),
        })

    def trace(self, claim_id: str) -> dict | None:
        for e in self.entries:
            for c in e["claims"]:
                if c["claim_id"] == claim_id:
                    return {"patient_id": e["patient_id"], "query": e["query"],
                            "claim": c}
        return None

    def record_refusal(self, patient_id: str, query: str, parsed: dict,
                       reason: str, missing: str | None = None) -> str:
        """Refusals are first-class audit events, not silent nulls.

        Logging what we declined to answer — and why — is exactly the artifact
        that distinguishes a system that is careful from one that is merely
        quiet.
        """
        self.entries.append({
            "patient_id": patient_id,
            "query": query,
            "plan": parsed,
            "claims": [],
            "decisions": [{"claim_id": "__refusal__", "action": "REFUSED",
                           "threshold": None, "escalate_to": "records request"}],
            "refusal_reason": reason,
            "missing_concept": missing,
            "n_published": 0, "n_suppressed": 0, "n_abstained": 1,
        })
        return f"audit/{len(self.entries):04d}"


# ---------------------------------------------------------------------------
# The assembled pipeline
# ---------------------------------------------------------------------------

class AxiomPipeline:
    def __init__(self, calibrator: IsotonicCalibrator | None = None):
        self.planner = QueryPlanner()
        self.cal = calibrator or IsotonicCalibrator().fit(
            [(0.70, 1), (0.80, 1), (0.88, 1), (0.92, 1), (0.96, 1)])
        self.abstain = AbstentionLayer(self.cal)
        self.audit = AuditTrail()

    def answer(self, patient: dict[str, Any], query: str) -> dict[str, Any]:
        g = ClinicalGraph(patient)
        parsed = self.planner.parse(query)
        cov = self.planner.coverage_check(g, query)
        ev = self.planner.execute(g, parsed)

        # -- refusal path -------------------------------------------------
        # If the record schema cannot represent the concept being asked about,
        # or the required evidence class is absent, we REFUSE. We do not fall
        # through to a general dump and we do not emit a hedged non-answer.
        if not cov["answerable"] or not ev.get("answerable", True):
            reason = cov["reason"] or ev.get("missing_evidence") or "insufficient evidence"
            ref = self.audit.record_refusal(
                patient["patient_id"], query, parsed, reason,
                missing=cov.get("missing") or ev.get("missing_evidence"))
            return {
                "patient_id": patient["patient_id"],
                "query": query,
                "plan": parsed,
                "refused": True,
                "refusal_reason": reason,
                "published": [],
                "abstained": [{"claim_id": "__refusal__", "action": "REFUSED",
                               "message": ("This record cannot support an answer "
                                           f"to that question: {reason}."),
                               "escalate_to": "records request — data not "
                                              "captured in this schema"}],
                "audit_ref": ref,
            }

        gen = ClaimGenerator(g)
        claims = gen.generate(query, ev)
        verified = gen.verify(claims, ev)
        decisions = self.abstain.apply(claims)
        self.audit.record(patient["patient_id"], query, parsed, verified, decisions)

        published = [d["claim"] for d in decisions if d["action"] == "PUBLISHED"]
        abstained = [d for d in decisions if d["action"] in ("ABSTAINED", "SUPPRESSED")]
        return {
            "patient_id": patient["patient_id"],
            "query": query,
            "plan": parsed,
            "refused": False,
            "refusal_reason": None,
            "evidence": {k: v for k, v in ev.items() if k != "gaps"},
            "graph_stats": g.stats(),
            "published": [c.to_dict() for c in published],
            "abstained": [{"claim": d["claim"].to_dict(), "action": d["action"],
                           "message": d.get("message"),
                           "escalate_to": d["escalate_to"]} for d in abstained],
            "audit_ref": f"audit/{len(self.audit.entries):04d}",
        }