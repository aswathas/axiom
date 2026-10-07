"""
AXIOM — patient entity resolution and the temporal clinical graph.

This is the layer that separates a real system from a vector-search demo:
time-stamped nodes joined by TYPED edges. Four question classes are simply not
expressible over flat document chunks:

    "what changed since the last visit"   -> temporal join across encounters
    "was this already known"              -> supersession / assertion-time
    "what is the creatinine trajectory"   -> series over one coded analyte
    "which diagnoses have no follow-up"   -> anti-join in time
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from .clinical import ANALYTES, CONDITIONS, DRUGS, INTERACTIONS, detect_stance

# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


def _jaro_winkler(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    match_dist = max(len(a), len(b)) // 2 - 1
    match_dist = max(match_dist, 0)
    a_m = [False] * len(a)
    b_m = [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        lo = max(0, i - match_dist)
        hi = min(i + match_dist + 1, len(b))
        for j in range(lo, hi):
            if not b_m[j] and b[j] == ca:
                a_m[i] = b_m[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    k = 0
    transpositions = 0
    for i, m in enumerate(a_m):
        if m:
            while not b_m[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
    t = transpositions / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - t) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4]):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm_dob(dob: str) -> str:
    y, m, d = dob.split("-")
    return f"{int(y):04d}{int(m):02d}{int(d):02d}"


def _dob_similarity(a: str, b: str) -> float:
    """Component-wise date comparison.

    String edit distance over a whole date is too forgiving — 1952-02-13 and
    1954-06-07 are four edits apart, which still scores 0.5, and that is far
    too generous for a full date disagreement. Birth year is the single most
    discriminating field in identity matching, so it is weighted accordingly.
    Day/month transposition (a classic data-entry error) is tolerated; a
    different year is not.
    """
    try:
        ya, ma, da = (int(x) for x in a.split("-"))
        yb, mb, db = (int(x) for x in b.split("-"))
    except ValueError:
        return 0.0
    score = 0.0
    if ya == yb:
        score += 0.50
    elif abs(ya - yb) <= 1:
        score += 0.10                  # possible typo, weak
    # month/day transposition tolerance
    if ma == mb and da == db:
        score += 0.50
    elif (ma == db and da == mb):
        score += 0.40                  # DD/MM swap — a known data-entry error
    elif ma == mb:
        score += 0.25
    elif da == db:
        score += 0.20
    return min(1.0, score)


# Feature weights: name .30, dob .25, sex .05, address .20, mrn .20.
# A feature that is ABSENT is excluded and the remaining weights are
# renormalised. Treating a missing field as evidence of DISSIMILARITY is a
# serious bug: it silently prevents legitimate patient merges, which in
# practice splits one person's chart in two. Absent data is not negative data.
W = {"name": 0.30, "dob": 0.25, "sex": 0.05, "addr": 0.20, "mrn": 0.20}
# A CONFLICTING MRN is far weaker evidence than a matching one. The same
# patient legitimately carries different MRNs in different source systems,
# so a mismatch must not be treated as strong as a disagreement on a field
# that ought to agree.
W_MRN_CONFLICT = 0.08
TAU = 0.85
BIAS = -1.00


def pair_score(a: dict, b: dict) -> float:
    """Logistic scorer over hand-weighted similarity features.

    Returns the calibrated probability that the two records are the same
    patient. Features that are missing on either side are dropped and the
    surviving weights renormalised to sum to 1.
    """
    feats: dict[str, float] = {}
    wts: dict[str, float] = {}

    na = (a.get("name") or "").lower().replace(",", "").strip()
    nb = (b.get("name") or "").lower().replace(",", "").strip()
    if na and nb:
        feats["name"] = _jaro_winkler(na, nb)
        wts["name"] = W["name"]

    if a.get("dob") and b.get("dob"):
        feats["dob"] = _dob_similarity(a["dob"], b["dob"])
        wts["dob"] = W["dob"]

    if a.get("sex") and b.get("sex"):
        feats["sex"] = 1.0 if a["sex"] == b["sex"] else 0.0
        wts["sex"] = W["sex"]

    addr_a, addr_b = (a.get("address") or "").lower(), (b.get("address") or "").lower()
    if addr_a and addr_b:                       # only if BOTH are populated
        feats["addr"] = _jaro_winkler(addr_a, addr_b)
        wts["addr"] = W["addr"]

    mrn_a, mrn_b = a.get("mrn") or "", b.get("mrn") or ""
    if mrn_a and mrn_b:
        if mrn_a == mrn_b:
            return 0.995                        # auto-positive, skip the blend
        feats["mrn"] = 0.0
        wts["mrn"] = W_MRN_CONFLICT

    if not feats:
        return 0.0

    wsum = sum(wts[k] for k in feats) or 1.0
    z = (sum(wts[k] * v for k, v in feats.items()) / wsum) - BIAS
    return 1.0 / (1.0 + pow(2.718281828, -z))


def resolve_identities(records: list[dict]) -> list[dict[str, Any]]:
    """Block on (dob, sex) and (mrn); score within blocks; merge above tau.

    Returns clusters with the canonical record plus the merged source records.
    """
    canon = {"name": "c", "dob": "c", "sex": "c", "mrn": "c"}
    all_recs = []
    for p in records:
        all_recs.append({**p["demographics"], "_pid": p["patient_id"],
                         "_src": "primary"})
        for r in p.get("encounter_records", []):
            all_recs.append({"name": r["name"], "dob": r["dob"], "sex": r["sex"],
                             "mrn": r["mrn"], "address": "",
                             "_pid": r["patient_id"], "_src": "legacy_ehr"})

    blocks: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(all_recs):
        blocks[("ds", r["dob"], r["sex"])].append(i)
        blocks[("mrn", r["mrn"])].append(i)

    pairs: set[tuple[int, int]] = set()
    for _, idxs in blocks.items():
        for x in range(len(idxs)):
            for y in range(x + 1, len(idxs)):
                pairs.add((idxs[x], idxs[y]))

    parent = list(range(len(all_recs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tp = fp = fn = 0
    for i, j in pairs:
        s = pair_score(all_recs[i], all_recs[j])
        same_true = all_recs[i]["_pid"] == all_recs[j]["_pid"]
        if s >= TAU:
            tp += 1 if same_true else 0
            fp += 0 if same_true else 1
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
        else:
            fn += 1 if same_true else 0

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(len(all_recs)):
        clusters[find(i)].append(i)

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    out = []
    for _, idxs in clusters.items():
        primary = next((all_recs[i] for i in idxs
                        if all_recs[i]["_src"] == "primary"), all_recs[idxs[0]])
        out.append({
            "canonical": primary,
            "sources": [all_recs[i] for i in idxs],
            "cluster_size": len(idxs),
        })
    # reporting a perfect score because no pairs were ever scored would be a
    # silent lie — surface an explicit 0.0 and the pair count instead
    return [{"clusters": out, "precision": prec, "recall": rec, "f1": f1,
             "pairs_scored": len(pairs)}]


# ---------------------------------------------------------------------------
# Temporal clinical graph
# ---------------------------------------------------------------------------

EDGE_TYPES = ["occurs_during", "precedes", "co_occurs_with", "supersedes",
              "contradicts", "contraindicated_with"]


class ClinicalGraph:
    """Nodes are observations. Edges are typed and, where relevant, time-aware."""

    def __init__(self, patient: dict[str, Any]):
        self.patient = patient
        self.nodes: dict[str, dict] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.by_type: dict[str, list[str]] = defaultdict(list)
        self.by_category: dict[str, list[str]] = defaultdict(list)
        self._build()

    # -- construction ----------------------------------------------------
    def _add(self, nid: str, ntype: str, ts: str, payload: dict) -> None:
        # Structural keys are authoritative and must survive payload expansion.
        # Encounter payloads carry their own `type` (the visit kind:
        # "inpatient"/"outpatient"), which used to overwrite the node type.
        # That collision was invisible in by_type — it indexes before the
        # spread — so it silently broke every consumer filtering nodes by type.
        # The visit kind is preserved under `encounter_type`, which cannot collide.
        payload = dict(payload)
        if "type" in payload and ntype == "Encounter":
            payload["encounter_type"] = payload.pop("type")
        self.nodes[nid] = {**payload, "id": nid, "type": ntype, "time": ts}
        self.by_type[ntype].append(nid)

    def _edge(self, a: str, b: str, etype: str) -> None:
        if a in self.nodes and b in self.nodes:
            self.edges.append((a, b, etype))

    def _build(self) -> None:
        p = self.patient
        for e in p["encounters"]:
            self._add(e["id"], "Encounter", e["start"], e)
        for d in p["diagnoses"]:
            self._add(d["id"], "Diagnosis", d["onset"], d)
            self.by_category[d["category"]].append(d["id"])
        for l in p["labs"]:
            disp, unit, lo, hi, worse = ANALYTES[l["loinc"]]
            self._add(l["id"], "LabResult", l["observed_at"], {**l, "display": disp,
                                                              "hi_is_worse": worse})
        for m in p["meds"]:
            self._add(m["id"], "MedicationOrder", m["start"], m)
        for a in p["allergies"]:
            self._add(a["id"], "Allergy", a["recorded_at"], a)
        for i in p["imaging"]:
            self._add(i["id"], "ImagingStudy", i["reported_at"], i)
        for n in p["notes"]:
            self._add(n["id"], "Note", n["observed_at"], n)
        for v in p["vitals"]:
            if v["points"]:
                self._add(v["id"], "VitalSeries", v["points"][0][0], v)

        enc = sorted(self.by_type["Encounter"], key=lambda i: self.nodes[i]["time"])

        # occurs_during + precedes (encounter ordering)
        for e in enc:
            for ntype in ("Diagnosis", "LabResult", "ImagingStudy", "Note"):
                for nid in self.by_type[ntype]:
                    if self.nodes[nid].get("encounter_id") == e:
                        self._edge(nid, e, "occurs_during")
        for a, b in zip(enc, enc[1:]):
            self._edge(a, b, "precedes")

        # co_occurrence between diagnoses in the same encounter
        for e in enc:
            dxs = [d for d in self.by_type["Diagnosis"]
                   if self.nodes[d].get("encounter_id") == e]
            for i, d1 in enumerate(dxs):
                for d2 in dxs[i + 1:]:
                    self._edge(d1, d2, "co_occurs_with")

        # supersession: a later Allergy supersedes an earlier one for same substance
        algs = sorted(self.by_type["Allergy"], key=lambda i: self.nodes[i]["time"])
        for i, a1 in enumerate(algs):
            for a2 in algs[i + 1:]:
                if self.nodes[a1]["substance"].lower() == self.nodes[a2]["substance"].lower():
                    self._edge(a2, a1, "supersedes")

        # contraindication: allergy vs active prescription of that substance
        for a in algs:
            for m in self.by_type["MedicationOrder"]:
                if (self.nodes[a]["substance"].lower()
                        == self.nodes[m]["drug"].lower()):
                    self._edge(a, m, "contraindicated_with")

        # documented drug-drug interactions between overlapping prescriptions
        self.interaction_edges: list[tuple[str, str, str, str]] = []
        meds = self.by_type["MedicationOrder"]
        for a, b, _sev, _why in INTERACTIONS:
            for m1 in meds:
                if self.nodes[m1]["drug"] != a:
                    continue
                for m2 in meds:
                    if self.nodes[m2]["drug"] != b:
                        continue
                    # overlap: either still active, or date windows intersect
                    if (self.nodes[m1].get("end") is None
                            or self.nodes[m2].get("end") is None):
                        self._edge(m1, m2, "contraindicated_with")
                        self.interaction_edges.append((m1, m2, a, b))
                    else:
                        self._edge(m1, m2, "contraindicated_with")
                        self.interaction_edges.append((m1, m2, a, b))

    # -- graph queries (the four unanswerable-by-retrieval questions) ----
    def neighbours(self, nid: str, etype: str | None = None,
                   direction: str = "out") -> list[str]:
        out = []
        for a, b, t in self.edges:
            if etype and t != etype:
                continue
            if direction == "out" and a == nid:
                out.append(b)
            elif direction == "in" and b == nid:
                out.append(a)
        return out

    def latest_encounter(self) -> str | None:
        enc = self.by_type["Encounter"]
        return max(enc, key=lambda i: self.nodes[i]["time"]) if enc else None

    def series(self, loinc: str) -> list[dict]:
        pts = [self.nodes[n] for n in self.by_type["LabResult"]
               if self.nodes[n]["loinc"] == loinc]
        # A trajectory is a statement about change over time. An observation
        # with no timestamp cannot be placed on that timeline, and sorting on
        # None raised TypeError — which killed the creatinine trend, the single
        # most important question in the demo. Undated values remain in the
        # graph and remain citable; they are simply not points on a line.
        pts = [p for p in pts if p.get("time") is not None]
        return sorted(pts, key=lambda n: n["time"])

    def trend(self, loinc: str, window_months: int | None = None) -> dict | None:
        """Deterioration analysis over a coded analyte series."""
        s = self.series(loinc)
        if len(s) < 4:
            return None
        if window_months:
            last = datetime.fromisoformat(s[-1]["time"])
            cutoff = last.timestamp() - window_months * 30 * 86400
            s = [n for n in s if datetime.fromisoformat(n["time"]).timestamp() >= cutoff]
            if len(s) < 4:
                return None
        worse = self.nodes[s[0]["id"]]["hi_is_worse"]
        first, last = s[0], s[-1]
        delta = last["value"] - first["value"]
        if worse:
            deteriorated = delta > 0
            change_pct = 100.0 * delta / first["value"] if first["value"] else 0.0
        else:
            deteriorated = delta < 0
            change_pct = 100.0 * delta / first["value"] if first["value"] else 0.0
        # monotonicity: Spearman-style rank agreement on direction
        dirs = []
        for a, b in zip(s, s[1:]):
            d = b["value"] - a["value"]
            dirs.append(1 if (d > 0 if worse else d < 0) else (-1 if d != 0 else 0))
        mono = (sum(1 for d in dirs if d > 0) / len(dirs)) if dirs else 0.0
        return {
            "loinc": loinc, "display": self.nodes[s[0]["id"]]["display"],
            "n": len(s), "first": first["value"], "last": last["value"],
            "first_time": first["time"], "last_time": last["time"],
            "unit": first["unit"], "delta": round(delta, 3),
            "change_pct": round(change_pct, 1),
            "deteriorated": bool(deteriorated),
            "monotonicity": round(mono, 2),
            "node_ids": [n["id"] for n in s],
        }

    def diagnoses_without_followup(self) -> list[dict]:
        """Anti-join in time: diagnoses with no later encounter at all."""
        enc = sorted(self.by_type["Encounter"], key=lambda i: self.nodes[i]["time"])
        if len(enc) < 2:
            return []
        last_enc_time = self.nodes[enc[-1]]["time"]
        out = []
        for d in self.by_type["Diagnosis"]:
            dt = self.nodes[d]["time"]
            if dt is None:
                continue  # an undated diagnosis cannot be placed in a gap
            if dt < last_enc_time:
                gap_days = (datetime.fromisoformat(last_enc_time)
                            - datetime.fromisoformat(dt)).days
                out.append({
                    "diagnosis_id": d, "code": self.nodes[d]["code"],
                    "display": self.nodes[d]["display"],
                    "onset": dt, "days_without_followup": gap_days,
                })
        out.sort(key=lambda x: -x["days_without_followup"])
        return out[:5]

    def new_since_last_visit(self) -> list[str]:
        """What changed since the previous encounter."""
        enc = sorted(self.by_type["Encounter"], key=lambda i: self.nodes[i]["time"])
        if len(enc) < 2:
            return []
        prev, cur = self.nodes[enc[-2]]["time"], self.nodes[enc[-1]]["time"]
        out = []
        for ntype in ("Diagnosis", "LabResult", "MedicationOrder", "Allergy"):
            for nid in self.by_type[ntype]:
                t = self.nodes[nid]["time"]
                # A node with no timestamp cannot participate in a temporal
                # comparison. Prose extraction can produce undated facts ("a
                # creatinine rise of 0.85 to 1.48" states no dates), and
                # comparing str to None raised TypeError, which surfaced as a
                # spurious refusal on a question the record *can* support.
                # The observation is still in the graph — it just cannot be
                # placed on a timeline, and pretending otherwise would be worse.
                if t is None:
                    continue
                if prev < t <= cur:
                    out.append(nid)
        return out

    def note_stances(self) -> list[dict]:
        out = []
        for nid in self.by_type["Note"]:
            n = self.nodes[nid]
            for sent in re.split(r"(?<=[.!?])\s+", n["text"]):
                s = sent.strip()
                if len(s) < 8:
                    continue
                st = detect_stance(s)
                if st != "ASSERTED":
                    out.append({"note_id": nid, "sentence": s, "stance": st})
        return out

    def stats(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "by_type": {k: len(v) for k, v in sorted(self.by_type.items())},
            "edge_types": {t: sum(1 for _, _, x in self.edges if x == t)
                           for t in EDGE_TYPES if any(x == t for _, _, x in self.edges)},
        }