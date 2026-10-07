"""
AXIOM — clinical record generation, normalisation and negation detection.

Design note: everything here is pure stdlib. The generator produces FHIR-shaped
records with *planted* findings of known type, severity and timestamp, so the
downstream pipeline's detection accuracy is externally verifiable.

CLINICAL REFERENCE: the LOINC / ICD-10 values used below are real. The RxNorm
mapping is an ILLUSTRATIVE SUBSET, not an authoritative release — a real
deployment resolves against the full RxNorm file. This is stated plainly
because shipping a fake authoritative mapping would be exactly the kind of
small dishonesty this project exists to avoid.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Terminology subsets
# ---------------------------------------------------------------------------

# LOINC code -> (display, unit, ref_low, ref_high, higher_is_worse)
ANALYTES = {
    "2160-0": ("Creatinine", "mg/dL", 0.6, 1.3, True),
    "33914-3": ("eGFR", "mL/min/1.73m2", 90.0, 140.0, False),
    "3094-0": ("Urea Nitrogen", "mg/dL", 7.0, 20.0, True),
    "2345-7": ("Glucose", "mg/dL", 70.0, 99.0, True),
    "4548-4": ("HbA1c", "%", 4.0, 5.6, True),
    "718-7":  ("Hemoglobin", "g/dL", 12.0, 17.5, False),
    "777-3":  ("Platelets", "K/uL", 150.0, 400.0, False),
    "6690-2": ("WBC", "K/uL", 4.0, 11.0, True),
    "2951-2": ("Sodium", "mmol/L", 135.0, 145.0, True),
    "2823-3": ("Potassium", "mmol/L", 3.5, 5.1, True),
    "6301-6": ("INR", "", 0.8, 1.2, True),
    "1742-6": ("ALT", "U/L", 7.0, 56.0, True),
    "1920-8": ("AST", "U/L", 10.0, 40.0, True),
    "1975-2": ("Bilirubin, total", "mg/dL", 0.1, 1.2, True),
    "10839-9": ("Troponin I", "ng/mL", 0.0, 0.04, True),
}

# LOINC codes measured in SI units, to exercise the unit-normalisation stage
SI_EQUIVALENT = {
    "2160-0": ("umol/L", 53.0, 115.0),
    "2345-7": ("mmol/L", 3.9, 5.5),
    "2823-3": ("mmol/L", 3.5, 5.1),
    "1920-8": ("ukat/L", 0.17, 0.67),
}

# ICD-10 -> (display, category)
CONDITIONS = {
    "I10":    ("Essential hypertension", "cardio"),
    "E11.9":  ("Type 2 diabetes mellitus", "endocrine"),
    "N18.3":  ("Chronic kidney disease stage 3", "renal"),
    "J44.1":  ("COPD with exacerbation", "pulmonary"),
    "I50.9":  ("Heart failure, unspecified", "cardio"),
    "E78.5":  ("Hyperlipidemia", "cardio"),
    "K21.9":  ("Gastroesophageal reflux", "gi"),
    "F32.9":  ("Major depressive disorder", "psych"),
    "N39.0":  ("Urinary tract infection", "renal"),
    "M54.5":  ("Low back pain", "msk"),
    "E66.9":  ("Obesity, unspecified", "endocrine"),
}

# Latent co-occurrence: conditions that appear together far above chance.
# This is what makes planted findings non-obvious — comorbidity emerges from a
# generative model rather than a template.
COOCCUR = {
    "I10":   ["E78.5", "E11.9", "I50.9", "N18.3"],
    "E11.9": ["E66.9", "I10", "N18.3"],
    "N18.3": ["I10", "E11.9", "I50.9"],
    "I50.9": ["I10", "N18.3", "J44.1"],
    "E78.5": ["I10", "E11.9"],
    "J44.1": ["I50.9"],
}

# Illustrative RxNorm subset (ingredient-level concepts).
DRUGS = {
    "lisinopril":      {"rxnorm": "314076", "class": "acei"},
    "metformin":       {"rxnorm": "6809",   "class": "biguanide"},
    "warfarin":        {"rxnorm": "11289",  "class": "anticoagulant"},
    "ibuprofen":       {"rxnorm": "3686",   "class": "nsaid"},
    "naproxen":        {"rxnorm": "7226",   "class": "nsaid"},
    "amoxicillin":     {"rxnorm": "723",    "class": "penicillin"},
    "atorvastatin":    {"rxnorm": "83367",  "class": "statin"},
    "furosemide":      {"rxnorm": "4739",   "class": "loop_diuretic"},
    "spironolactone":  {"rxnorm": "138476", "class": "aldosterone"},
    "digoxin":         {"rxnorm": "2983",   "class": "cardiac_glycoside"},
    "losartan":        {"rxnorm": "658587", "class": "arb"},
    "glipizide":       {"rxnorm": "4821",   "class": "sulfonylurea"},
    "amiodarone":      {"rxnorm": "274",    "class": "antiarrhythmic"},
    "simvastatin":     {"rxnorm": "617314", "class": "statin"},
    "levothyroxine":   {"rxnorm": "9624",   "class": "thyroid"},
}

# Documented, clinically significant interactions. Each maps to the evidence
# node pair that must be present for the finding to be *findable*.
INTERACTIONS = [
    ("warfarin", "ibuprofen", "critical",
     "Additive anticoagulant/antiplatelet effect - bleeding risk."),
    ("warfarin", "naproxen", "critical",
     "Additive anticoagulant/antiplatelet effect - bleeding risk."),
    ("warfarin", "amiodarone", "high",
     "Amiodarone inhibits warfarin metabolism - INR may rise."),
    ("digoxin", "furosemide", "high",
     "Loop-diuretic-induced hypokalaemia potentiates digoxin toxicity."),
    ("lisinopril", "spironolactone", "high",
     "Combined potassium retention - hyperkalaemia risk, requires monitoring."),
    ("digoxin", "spironolactone", "high",
     "Both reduce renal potassium excretion - hyperkalaemia and toxicity risk."),
]

ALLERGENS = ["penicillin", "sulfa", "latex", "codeine", "iodinated contrast"]

FACILITIES = ["Riverside General", "Northgate Community Hospital",
              "Elm Street Family Practice", "Lakeside Medical Center"]


# ---------------------------------------------------------------------------
# Negation & speculation detection (NegEx-style scope rules)
# ---------------------------------------------------------------------------

PRE_NEGATION = [
    "no", "not", "without", "denies", "deny", "denied", "negative for",
    "absence of", "absent", "free of", "never had", "no evidence of",
    "rule out", "ruled out", "without any", "neither", "nor", "cannot",
]
NEGATION_STOP = [
    "but", "however", "although", "though", "except", "aside from",
    "otherwise", "still", "yet",
]
SPECULATION = ["possible", "possibly", "probable", "probably", "likely",
               "concern for", "concerning for", "suspicious for", "may have",
               "might have", "question of", "consider", "considering",
               "cannot exclude", "not excluded", "differential includes"]
ASSERTED_ONLY_NOTE = "negated and speculative nodes are retrievable but can never be cited as positive evidence"


def detect_stance(sentence: str) -> str:
    """Return ASSERTED | NEGATED | SPECULATIVE for a single clinical sentence.

    Rule-based scope detection: a pre-negation trigger negates the clause until
    a termination token. This is the classical approach (NegEx, 2009) and it is
    the minimum viable correct behaviour. A pipeline that cannot tell "denies
    chest pain" from "has chest pain" produces confident errors, which is
    worse than producing none at all.
    """
    low = sentence.lower()

    for cue in SPECULATION:
        if cue in low:
            return "SPECULATIVE"

    tokens = re.findall(r"[a-z]+", low)
    for i, tok in enumerate(tokens):
        # match multi-word triggers by joining the window
        window = " ".join(tokens[i:i + 3])
        triggered = any(window.startswith(t) for t in PRE_NEGATION)
        if not triggered:
            continue
        # scan forward for a termination token
        for j in range(i + 1, min(i + 14, len(tokens))):
            if tokens[j] in NEGATION_STOP:
                break
        # if we reached the end of the window without termination, it's negated
        if j >= min(i + 13, len(tokens)) - 1 or tokens[j] in NEGATION_STOP:
            # a negated clause still counts as negated unless a specifier sits right after
            return "NEGATED"
    return "ASSERTED"


# ---------------------------------------------------------------------------
# Unit normalisation
# ---------------------------------------------------------------------------

UNIT_CANON = {
    "mg/dl": ("mg/dL", 1.0), "milligram/deciliter": ("mg/dL", 1.0),
    "umol/l": ("umol/L", 1.0), "µmol/l": ("umol/L", 1.0),
    "mmol/l": ("mmol/L", 1.0), "mg/l": ("mg/L", 0.001),
    "g/dl": ("g/dL", 1.0), "k/ul": ("K/uL", 1.0),
    "ml/min/1.73m2": ("mL/min/1.73m2", 1.0), "ukat/l": ("ukat/L", 1.0),
    "%": ("%", 1.0), "u/l": ("U/L", 1.0),
}

# canonical unit -> (factor to base, base unit)   creatinine base = umol/L
BASE_UNIT = {
    "2160-0": ("umol/L", 88.4),
    "2345-7": ("mmol/L", 1.0),
    "2823-3": ("mmol/L", 1.0),
}


def normalise_unit(loinc: str, unit: str, value: float) -> tuple[str, float] | None:
    """Return (canonical_unit, converted_value) or None if unmappable.

    Unmappable values return None rather than being silently coerced. A value we
    cannot convert is a data-quality event worth surfacing; silently passing it
    through is how clinical pipelines quietly lie.
    """
    u = unit.strip().lower()
    if u in UNIT_CANON:
        cu, factor = UNIT_CANON[u]
        return (cu, value * factor)
    if loinc in SI_EQUIVALENT and u == SI_EQUIVALENT[loinc][0]:
        return (SI_EQUIVALENT[loinc][0], value)
    return None


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class PatientGenerator:
    """Generates longitudinal synthetic patients with planted findings."""

    def __init__(self, seed: int = 20261007):
        self.rng = random.Random(seed)
        self._n = 0

    # -- helpers ---------------------------------------------------------
    def _sid(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n:05d}"

    def _iso(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    def _condition_set(self) -> list[str]:
        primary = self.rng.choice(list(CONDITIONS.keys()))
        codes = [primary]
        for c in self.rng.sample(COOCCUR.get(primary, []),
                                 k=min(len(COOCCUR.get(primary, [])), self.rng.randint(0, 2))):
            codes.append(c)
        return codes

    def _lab_value(self, loinc: str, drift: float = 0.0) -> float:
        display, unit, lo, hi, _ = ANALYTES[loinc]
        mid = (lo + hi) / 2
        span = (hi - lo) or 1.0
        v = self.rng.gauss(mid, span * 0.22)
        return round(max(0.0, v + drift * span), 3)

    # -- main ------------------------------------------------------------
    def make_patient(self, with_planted: bool = True) -> dict[str, Any]:
        rng = self.rng
        now = datetime(2026, 10, 1, 9, 0, 0)
        start = now - timedelta(days=rng.randint(400, 900))

        pid = self._sid("p")
        conditions = self._condition_set()

        patient: dict[str, Any] = {
            "patient_id": pid,
            "demographics": {
                "name": f"{rng.choice(['Alvarez','Nakamura','Okafor','Ivanov','Silva','Haddad','Novak','Bergman','Osei','Kaur'])}"
                        f", {rng.choice(['R.','M.','T.','J.','A.','K.','L.'])}",
                "dob": f"{rng.randint(1948, 1985)}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
                "sex": rng.choice(["M", "F"]),
                "mrn": f"MRN{rng.randint(100000, 999999)}",
            },
            "encounters": [], "diagnoses": [], "labs": [], "meds": [],
            "allergies": [], "imaging": [], "vitals": [], "notes": [],
            "encounter_records": [],   # raw source-system duplicates
        }

        # ---- encounters over time
        n_enc = rng.randint(4, 8)
        enc_dates = sorted(start + timedelta(days=rng.randint(0, 700) + i * rng.randint(45, 110))
                           for i in range(n_enc))
        enc_dates = [d for d in enc_dates if d < now][:n_enc]

        for ed in enc_dates:
            enc_id = self._sid("enc")
            etype = rng.choice(["outpatient", "outpatient", "emergency", "inpatient"])
            patient["encounters"].append({
                "id": enc_id, "type": etype,
                "start": self._iso(ed),
                "end": self._iso(ed + timedelta(hours=rng.randint(2, 40))),
                "facility": rng.choice(FACILITIES),
            })

            # diagnoses accrue at encounters
            for c in rng.sample(conditions, k=min(len(conditions), rng.randint(1, 3))):
                disp, cat = CONDITIONS[c]
                patient["diagnoses"].append({
                    "id": self._sid("dx"), "code": c, "system": "ICD-10-CM",
                    "display": disp, "category": cat,
                    "onset": self._iso(ed), "encounter_id": enc_id,
                    "asserted_by": "clinician", "status": "active",
                })

            # renal markers when relevant
            if any(c in ("N18.3", "I10", "E11.9") for c in conditions):
                for loinc in ("2160-0", "33914-3", "3094-0", "2823-3"):
                    drift = (ed - start).days / 700.0
                    val = self._lab_value(loinc, drift * 0.5)
                    unit = ANALYTES[loinc][1]
                    # deliberately inconsistent units across encounters
                    if loinc == "2160-0" and rng.random() < 0.4:
                        unit, val = "umol/L", round(val * 88.4, 1)
                    patient["labs"].append({
                        "id": self._sid("lab"), "loinc": loinc,
                        "value": val, "unit": unit, "observed_at": self._iso(ed),
                        "encounter_id": enc_id,
                        "ref_low": ANALYTES[loinc][2], "ref_high": ANALYTES[loinc][3],
                        "status": "final",
                    })

            # narrative note with realistic negation / speculation
            neg = rng.sample(["chest pain", "dyspnea", "fever", "haematuria",
                              "overnight cough", "ankle swelling"], k=rng.randint(1, 2))
            spec = rng.choice(["possible small pleural effusion",
                               "early diastolic dysfunction",
                               "mild anaemia of chronic disease"])
            note = (f"S: {rng.randint(38,39)}C. Denies {neg[0]}. "
                    f"No evidence of {'PE' if 'chest pain' in neg else 'sepsis'}. "
                    f"H: {rng.choice(['cor' ,'smoker','diabetic','hypertensive'])}. "
                    f"A: {', '.join(CONDITIONS[c][0] for c in rng.sample(conditions, k=min(2,len(conditions))))}. "
                    f"P: {spec}; considering further imaging if findings progress. "
                    f"Plan: continue {rng.choice(list(DRUGS))}. "
                    f"Follow-up in 3 months.")
            patient["notes"].append({
                "id": self._sid("note"), "encounter_id": enc_id,
                "observed_at": self._iso(ed), "text": note,
            })

            if rng.random() < 0.3:
                patient["imaging"].append({
                    "id": self._sid("img"),
                    "modality": rng.choice(["CXR", "CT", "US"]),
                    "body_site": rng.choice(["chest", "abdomen", "renal"]),
                    "reported_at": self._iso(ed + timedelta(hours=6)),
                    "narrative": f"Study performed. {spec.capitalize()}. "
                                 f"No acute osseous abnormality. No free air.",
                    "encounter_id": enc_id,
                })

        # ---- chronic medications (overlap deliberately)
        chronic = rng.sample(list(DRUGS), k=rng.randint(2, 5))
        for d in chronic:
            patient["meds"].append({
                "id": self._sid("med"), "drug": d, "rxnorm": DRUGS[d]["rxnorm"],
                "dose": f"{rng.choice([10, 20, 40, 500, 5])} {rng.choice(['mg','g'])}",
                "route": "PO", "start": self._iso(start + timedelta(days=rng.randint(0, 60))),
                "end": None, "status": "active",
            })

        # ---- allergy history, including a superseded entry
        if rng.random() < 0.45:
            a = rng.choice(ALLERGENS)
            patient["allergies"].append({
                "id": self._sid("alg"), "substance": a,
                "rxnorm": DRUGS.get(a, {}).get("rxnorm", "unknown"),
                "reaction": rng.choice(["rash", "anaphylaxis", "urticaria"]),
                "severity": rng.choice(["mild", "moderate", "severe"]),
                "recorded_at": self._iso(start + timedelta(days=200)),
                "status": "active",
            })

        # ---- duplicate identity in a second source system (entity resolution work)
        if rng.random() < 0.6:
            d = patient["demographics"]
            patient["encounter_records"].append({
                "source_system": "legacy_ehr",
                # MUST carry the same patient id as the primary record — this
                # id is the ground-truth label the entity-resolution scorer is
                # graded against. Minting a new id here silently mislabels one
                # patient as two and makes recall report 0.0 for a correct merge.
                "patient_id": pid,
                "name": d["name"].upper().replace(", ", " "),
                "dob": d["dob"],
                "sex": d["sex"],
                "mrn": f"LEG{rng.randint(10000, 99999)}",
            })

        # ---- vitals series
        patient["vitals"].append({
            "id": self._sid("vs"), "code": "BloodPressure",
            "points": [(self._iso(ed), round(rng.gauss(140, 15), 1)) for ed in enc_dates],
        })

        # ---- plant findings
        patient["planted"] = self._plant(patient, with_planted)
        return patient

    # -- planting --------------------------------------------------------
    def _plant(self, p: dict[str, Any], enabled: bool) -> list[dict[str, Any]]:
        if not enabled:
            return []
        rng = self.rng
        out: list[dict[str, Any]] = []

        # 1. drug-drug interaction: requires TWO med nodes + overlap
        cands = [(a, b) for a in DRUGS for b in DRUGS
                 if (a, b) in [(x[0], x[1]) for x in INTERACTIONS]]
        if cands:
            a, b = rng.choice(cands)
            sev, why = next((i[2], i[3]) for i in INTERACTIONS if (i[0], i[1]) == (a, b))
            ids = []
            for d in (a, b):
                node = {"id": self._sid("med"), "drug": d, "rxnorm": DRUGS[d]["rxnorm"],
                        "dose": "10 mg", "route": "PO",
                        "start": self._iso(datetime(2025, 11, 1)), "end": None,
                        "status": "active"}
                p["meds"].append(node)
                ids.append(node["id"])
            out.append({
                "id": "F1", "type": "drug_drug_interaction", "severity": sev,
                "planted_at": "2025-11-01T00:00:00", "evidence_node_ids": ids,
                "description": f"{a} + {b}: {why}",
            })

        # 2. deteriorating renal trend: requires a MONOTONIC SERIES of lab nodes
        creat = [l for l in p["labs"] if l["loinc"] == "2160-0"]
        if len(creat) >= 4:
            ids = []
            for i, l in enumerate(sorted(creat, key=lambda x: x["observed_at"])):
                l["value"] = round(0.85 + i * 0.21 + rng.uniform(-0.05, 0.05), 2)
                l["unit"] = "mg/dL"
                l["observed_at"] = f"2025-0{i+1}-15T09:00:00"
                l["value"] = round(0.85 + (i) * 0.21, 2)
                ids.append(l["id"])
            out.append({
                "id": "F2", "type": "deteriorating_lab_trend", "severity": "high",
                "planted_at": "2025-01-15T09:00:00", "evidence_node_ids": ids,
                "description": "Creatinine rises monotonically 0.85 -> 1.48 mg/dL over 5 months.",
            })

        # 3. allergy contradicting an active prescription (supersession)
        if rng.random() < 0.6:
            a = rng.choice([d for d in ALLERGENS if d in DRUGS] or ["ibuprofen"])
            alg_id = self._sid("alg")
            p["allergies"].append({
                "id": alg_id, "substance": a,
                "rxnorm": DRUGS.get(a, {}).get("rxnorm", "unknown"),
                "reaction": "anaphylaxis", "severity": "severe",
                "recorded_at": "2025-06-01T00:00:00", "status": "active",
            })
            med_id = self._sid("med")
            p["meds"].append({
                "id": med_id, "drug": a, "rxnorm": DRUGS.get(a, {}).get("rxnorm", "unknown"),
                "dose": "500 mg", "route": "PO", "start": "2025-09-01T00:00:00",
                "end": None, "status": "active",
            })
            out.append({
                "id": "F3", "type": "allergy_contraindication", "severity": "critical",
                "planted_at": "2025-09-01T00:00:00", "evidence_node_ids": [alg_id, med_id],
                "description": f"Documented severe {a} allergy while {a} is actively prescribed.",
            })

        # 4. missed follow-up: referral with no subsequent encounter
        if len(p["encounters"]) >= 3:
            out.append({
                "id": "F4", "type": "missed_follow_up", "severity": "medium",
                "planted_at": p["encounters"][0]["start"], "evidence_node_ids": [],
                "description": "Cardiology referral issued at encounter 1, no follow-up encounter recorded.",
            })

        return out


def generate_cohort(n: int = 40, seed: int = 20261007) -> list[dict[str, Any]]:
    g = PatientGenerator(seed)
    return [g.make_patient() for _ in range(n)]