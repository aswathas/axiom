"""Patient record assembly — turns extracted Facts into the dict shape that
``ClinicalGraph`` consumes.

See docs/CONTRACTS.md Contract 2. The shape mirrors ``axiom.clinical.make_patient``
output exactly, because the graph engine indexes all eight collections by key
and will raise KeyError if any is missing.

The separation matters: extraction produces unordered, possibly duplicated
observations from several documents. This module's job is to deduplicate,
order them in time, and hand the graph a record it can trust.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from .facts import Fact, is_abnormal

COLLECTIONS = ("encounters", "diagnoses", "labs", "meds",
               "allergies", "imaging", "notes", "vitals")

# Reverse lookup from analyte display name to LOINC, built once from the single
# authoritative source rather than a second hardcoded copy in the parser.
def _loinc_index() -> dict[str, str]:
    from .clinical import ANALYTES
    return {display.lower(): code for code, (display, *_rest) in ANALYTES.items()}


_LOINC = _loinc_index()


def empty_patient(pid: str, name: str = "Unknown", dob: str = "",
                  mrn: str = "") -> dict[str, Any]:
    """A valid patient with every collection present and empty."""
    return {
        # `patient_id` is canonical: axiom.clinical emits it (clinical.py:256)
        # and axiom.pipeline indexes it in three places. An earlier contract
        # specified `id`, which made those two disagree. The engine is right.
        "patient_id": pid,
        "name": name,
        "dob": dob,
        "mrn": mrn,
        **{c: [] for c in COLLECTIONS},
    }


def _next_id(prefix: str, used: set[str]) -> str:
    n = 1
    while f"{prefix}_{n:04d}" in used:
        n += 1
    nid = f"{prefix}_{n:04d}"
    used.add(nid)
    return nid


def build_patient(facts: Iterable[Fact], pid: str = "pat_001",
                  name: str = "Unknown", dob: str = "", mrn: str = "") -> dict[str, Any]:
    """Assemble a patient record from extracted facts.

    Facts are deduplicated on (kind, name, timestamp, value) — the same lab
    value uploaded twice from two portals is one observation, not two.
    """
    p = empty_patient(pid, name, dob, mrn)
    used: set[str] = set()
    seen: set[tuple] = set()

    ordered = sorted(facts, key=lambda f: (f.timestamp or "", f.kind, f.name))

    for f in ordered:
        key = (f.kind, f.name.lower(), f.timestamp, str(f.value))
        if key in seen:
            continue
        seen.add(key)
        prov = {"source_doc_id": f.source_doc_id, "source_page": f.source_page,
                "source_char_start": f.source_char_start,
                "source_char_end": f.source_char_end,
                "extractor": f.extractor}

        if f.kind == "encounter":
            # Contract 2 shape. `type` is the visit kind (inpatient/outpatient);
            # ClinicalGraph._add renames it to `encounter_type` on the node so it
            # cannot shadow the structural node type.
            p["encounters"].append({
                "id": _next_id("enc", used),
                "start": f.timestamp,
                "type": f.meta.get("type", "unspecified"),
                "admit": f.meta.get("admit"), "discharge": f.meta.get("discharge"),
                "facility": f.meta.get("facility"),
                "service": f.meta.get("service"), **prov,
            })

        elif f.kind == "lab":
            loinc = f.loinc or _LOINC.get(f.name.lower())
            if loinc is None:
                continue  # unmappable analytes are not publishable as lab nodes
            abnormal = is_abnormal(f.value, f.ref_low, f.ref_high)
            p["labs"].append({
                "id": _next_id("lab", used),
                "loinc": loinc, "value": f.value, "unit": f.unit,
                "observed_at": f.timestamp, "ref_low": f.ref_low,
                "ref_high": f.ref_high, "abnormal": abnormal, **prov,
            })

        elif f.kind == "med":
            p["meds"].append({
                "id": _next_id("med", used),
                # `drug`, not `name`: axiom.clinical emits `drug`
                # (clinical.py:345) and graph.py's interaction pass indexes
                # nodes[m]["drug"] at lines 337/345/348. A contract that said
                # `name` produced a KeyError the moment a patient had two
                # overlapping prescriptions — which is exactly the case the
                # interaction demo depends on.
                "drug": f.name, "rxnorm": f.meta.get("rxnorm"),
                "dose": f.meta.get("dose"), "frequency": f.meta.get("frequency"),
                "start": f.timestamp, "end": f.meta.get("end"),
                "active": f.meta.get("active", True), **prov,
            })

        elif f.kind == "dx":
            p["diagnoses"].append({
                "id": _next_id("dx", used),
                "code": f.meta.get("code", ""), "display": f.name,
                "onset": f.timestamp,
                "category": f.meta.get("category", "unspecified"), **prov,
            })

        elif f.kind == "allergy":
            p["allergies"].append({
                "id": _next_id("alg", used), "substance": f.name,
                "reaction": f.meta.get("reaction", ""),
                "recorded_at": f.timestamp, **prov,
            })

        elif f.kind == "imaging":
            p["imaging"].append({
                "id": _next_id("img", used),
                "modality": f.meta.get("modality", ""), "display": f.name,
                "reported_at": f.timestamp, **prov,
            })

        elif f.kind == "note_stance":
            p["notes"].append({
                "id": _next_id("note", used), "text": f.name,
                "observed_at": f.timestamp,
                "stance": "negated" if f.negated else "asserted", **prov,
            })

        elif f.kind == "vital":
            p["vitals"].append({
                "id": _next_id("vs", used), "display": f.name, "unit": f.unit,
                "points": [[f.timestamp, f.value]], **prov,
            })

    for coll in ("encounters", "diagnoses", "labs", "meds", "notes",
                 "imaging", "allergies", "vitals"):
        p[coll].sort(key=lambda n: (n.get("onset") or n.get("observed_at")
                                    or n.get("start") or n.get("recorded_at") or ""))

    _attribute_to_encounters(p)
    return p


def _attribute_to_encounters(p: dict[str, Any]) -> None:
    """Join observations to the encounter they occurred during.

    ``ClinicalGraph`` gates ``occurs_during`` edges on a node carrying an
    ``encounter_id`` (``graph.py:313``). Without this join every edge in the
    chart is ``precedes``, and the temporal question classes that make this
    project worth building stay dead.

    The rule is deliberately conservative. An observation is attributed only
    when an encounter window demonstrably contains it — an admission spans
    ``admit..discharge``, an outpatient encounter is its collection date.
    Anything that cannot be placed is left unattributed rather than snapped to
    the nearest plausible visit, because a wrong attribution yields a confident
    clinical claim ("this value was drawn during the January admission") that
    nothing in the record supports. Absence of an attribution is a visible,
    honest gap; a fabricated one is not.

    An admission window outranks a same-day outpatient draw: it is the stronger
    claim about where the patient actually was.
    """
    encounters = [e for e in p.get("encounters", []) if e.get("start")]
    if not encounters:
        return

    stays = [(e["start"], e.get("discharge") or e["start"], e["id"])
             for e in encounters if e.get("discharge")]
    points = [(e["start"], e["id"]) for e in encounters]

    def place(ts: Optional[str]) -> Optional[str]:
        if not ts:
            return None
        for start, end, eid in stays:
            if start <= ts <= end:
                return eid
        for t, eid in points:
            if t == ts:
                return eid
        return None

    for coll, ts_key in (("labs", "observed_at"), ("meds", "start"),
                         ("imaging", "reported_at"), ("notes", "observed_at"),
                         ("diagnoses", "onset")):
        for node in p.get(coll, []):
            eid = place(node.get(ts_key))
            if eid is not None:
                node["encounter_id"] = eid


def merge_sources(documents: list[dict[str, Any]]) -> dict[str, list[Fact]]:
    """Group facts by source document, preserving page order.

    A document dict is {"doc_id": str, "facts": [Fact, ...]}.
    """
    grouped: dict[str, list[Fact]] = {}
    for doc in documents:
        grouped.setdefault(doc["doc_id"], []).extend(doc.get("facts", []))
    for facts in grouped.values():
        facts.sort(key=lambda f: (f.source_page, f.source_char_start))
    return grouped