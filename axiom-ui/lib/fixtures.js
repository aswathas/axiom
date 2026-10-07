/**
 * Inline fallback fixtures.
 *
 * These exist so `npm run build` is provable without a backend and so the UI
 * still renders during the window where the demo is running one process and
 * not the other. They are NEVER merged with live data and they are NEVER shown
 * as if they were live — every screen that falls back here is marked
 * `offline` and the chrome says so. A demo that silently serves canned data
 * through a live-looking UI would be exactly the failure mode this project
 * argues against.
 *
 * Shapes below mirror Contract 5 / Contract 2 / Contract 3 exactly.
 */

/* ------------------------------------------------------------------ */
/* Contract 3 layout text — the same synthetic document the Python      */
/* renderers produce, so character offsets are real, not invented.      */
/* ------------------------------------------------------------------ */

export const LAB_PAGE = `                    QUEST DIAGNOSTICS
              8401 Wilson Boulevard, Tampa, FL 33618

Patient: Bergman, L.          MRN: MRN762900
DOB: 04/12/1964               Collected: 04/15/2025 09:42
Accession: 2518473920         Ordering Physician: Ramanathan, K.

CHEMISTRY - RENAL PANEL

Analyte                     Result     Units       Reference Range    Flag
--------------------------------------------------------------------------------
Creatinine                     1.48      mg/dL       0.60 - 1.30          H
eGFR                            41     mL/min/1.73m2  90 - 140           L
Potassium                      5.20      mmol/L      3.50 - 5.10          H
Sodium                        131.0      mmol/L      135.0 - 145.0       L

End of Report
`;

export const DISCHARGE_PAGE = `ST. MARGARET'S MEDICAL CENTER
Department of Internal Medicine

DISCHARGE SUMMARY

Patient: Bergman, L.        DOB: 04/12/1964        MRN: MRN762900
Admit Date: 01/15/2025      Discharge Date: 01/22/2025
Attending: Ramanathan, K.

DIAGNOSIS
1. Chronic kidney disease, stage 3 (N18.3)
2. Essential hypertension (I10)
3. Type 2 diabetes mellitus (E11.9)

PRESENTING HISTORY
Patient is a 60-year-old female presenting with progressive fatigue and
worsening exertional dyspnea. She denies chest pain. She denies hematuria.
Creatinine rose from 0.85 to 1.48 over the admission.

MEDICATIONS ON DISCHARGE
- Metformin 500 mg PO BID
- Lisinopril 10 mg PO daily
- Warfarin 5 mg PO daily

DISPOSITION
Follow up with Cardiology within 2 weeks. Renal nephrology referral placed.
`;

export const PHARMACY_PAGE = `HARBORVIEW PHARMACY
Prescription History

Patient: Bergman, L.     DOB: 04/12/1964     MRN: MRN762900

Medication            Strength     Directions              Start
------------------------------------------------------------------------------
Metformin             500 mg       Take 1 tablet PO BID     01/15/2025
Lisinopril             10 mg       Take 1 tablet PO daily   01/15/2025
Warfarin                5 mg       Take 1 tablet PO daily   03/02/2025
`;

export const DOCS = {
  doc_lab0425: {
    doc_id: 'doc_lab0425',
    kind: 'lab_report',
    filename: 'quest_renal_panel_2025-04-15.pdf',
    page_count: 1,
    pages: { 1: LAB_PAGE },
  },
  doc_dc0115: {
    doc_id: 'doc_dc0115',
    kind: 'discharge_summary',
    filename: 'discharge_summary_2025-01-22.txt',
    page_count: 1,
    pages: { 1: DISCHARGE_PAGE },
  },
  doc_rx0302: {
    doc_id: 'doc_rx0302',
    kind: 'med_list',
    filename: 'harborview_prescriptions_2025-03-02.txt',
    page_count: 1,
    pages: { 1: PHARMACY_PAGE },
  },
};

/* ------------------------------------------------------------------ */
/* Contract 2 patient dict                                             */
/* ------------------------------------------------------------------ */

function span(text, needle) {
  const i = text.indexOf(needle);
  if (i < 0) return [0, 0];
  return [i, i + needle.length];
}

export const PATIENTS = [
  {
    id: 'pat_001',
    name: 'Bergman, L.',
    dob: '1964-04-12',
    mrn: 'MRN762900',
    doc_count: 3,
    node_count: 0, // filled by buildGraph below
  },
  {
    id: 'pat_002',
    name: 'Oyelaran, T.',
    dob: '1951-11-03',
    mrn: 'MRN418822',
    doc_count: 2,
    node_count: 0,
  },
];

const P1_ENC = span(DISCHARGE_PAGE, 'Chronic kidney disease, stage 3');
const P1_MED = span(PHARMACY_PAGE, 'Metformin');
const P1_WAR = span(PHARMACY_PAGE, 'Warfarin');
const P1_LIS = span(PHARMACY_PAGE, 'Lisinopril');

export const PATIENT_DETAIL = {
  pat_001: {
    id: 'pat_001',
    name: 'Bergman, L.',
    dob: '1964-04-12',
    mrn: 'MRN762900',
    encounters: [
      {
        id: 'enc_001', start: '2025-01-15', type: 'inpatient',
        source_doc_id: 'doc_dc0115', source_page: 1,
      },
    ],
    diagnoses: [
      {
        id: 'dx_ckd3', code: 'N18.3', display: 'Chronic kidney disease, stage 3',
        onset: '2025-01-15', category: 'renal',
        source_doc_id: 'doc_dc0115', source_page: 1,
      },
      {
        id: 'dx_htn', code: 'I10', display: 'Essential hypertension',
        onset: '2025-01-15', category: 'cardiovascular',
        source_doc_id: 'doc_dc0115', source_page: 1,
      },
      {
        id: 'dx_t2dm', code: 'E11.9', display: 'Type 2 diabetes mellitus',
        onset: '2025-01-15', category: 'endocrine',
        source_doc_id: 'doc_dc0115', source_page: 1,
      },
    ],
    labs: [
      { id: 'lab_cr_01', loinc: '2160-0', value: 0.85, unit: 'mg/dL', observed_at: '2024-07-18', ref_low: 0.6, ref_high: 1.3 },
      { id: 'lab_cr_02', loinc: '2160-0', value: 1.02, unit: 'mg/dL', observed_at: '2024-10-22', ref_low: 0.6, ref_high: 1.3 },
      { id: 'lab_cr_03', loinc: '2160-0', value: 1.31, unit: 'mg/dL', observed_at: '2025-01-16', ref_low: 0.6, ref_high: 1.3 },
      { id: 'lab_cr_04', loinc: '2160-0', value: 1.48, unit: 'mg/dL', observed_at: '2025-04-15', ref_low: 0.6, ref_high: 1.3 },
      { id: 'lab_na_01', loinc: '2951-2', value: 131.0, unit: 'mmol/L', observed_at: '2025-04-15', ref_low: 135.0, ref_high: 145.0 },
      { id: 'lab_k_01', loinc: '2823-3', value: 5.2, unit: 'mmol/L', observed_at: '2025-04-15', ref_low: 3.5, ref_high: 5.1 },
    ],
    meds: [
      { id: 'med_met', name: 'Metformin', rxnorm: '860975', dose: '500 mg', frequency: 'BID', start: '2025-01-15', end: null, active: true, source_doc_id: 'doc_rx0302', source_page: 1 },
      { id: 'med_lis', name: 'Lisinopril', rxnorm: '314076', dose: '10 mg', frequency: 'daily', start: '2025-01-15', end: null, active: true, source_doc_id: 'doc_rx0302', source_page: 1 },
      { id: 'med_war', name: 'Warfarin', rxnorm: '855332', dose: '5 mg', frequency: 'daily', start: '2025-03-02', end: null, active: true, source_doc_id: 'doc_rx0302', source_page: 1 },
    ],
    allergies: [],
    imaging: [],
    notes: [
      {
        id: 'note_001', text: 'Denies chest pain. Denies hematuria.',
        observed_at: '2025-01-15', stance: 'negated',
        source_doc_id: 'doc_dc0115', source_page: 1,
      },
    ],
    vitals: [],
  },
  pat_002: {
    id: 'pat_002',
    name: 'Oyelaran, T.',
    dob: '1951-11-03',
    mrn: 'MRN418822',
    encounters: [
      { id: 'enc_101', start: '2025-02-08', type: 'outpatient', source_doc_id: 'doc_dc0115', source_page: 1 },
    ],
    diagnoses: [
      { id: 'dx_afib', code: 'I48.91', display: 'Atrial fibrillation', onset: '2025-02-08', category: 'cardiovascular', source_doc_id: 'doc_dc0115', source_page: 1 },
    ],
    labs: [
      { id: 'lab_inr_01', loinc: '6301-6', value: 3.4, unit: '', observed_at: '2025-02-08', ref_low: 2.0, ref_high: 3.0 },
      { id: 'lab_inr_02', loinc: '6301-6', value: 3.9, unit: '', observed_at: '2025-03-10', ref_low: 2.0, ref_high: 3.0 },
    ],
    meds: [
      { id: 'med_asp', name: 'Aspirin', rxnorm: '1191', dose: '81 mg', frequency: 'daily', start: '2025-02-08', end: null, active: true, source_doc_id: 'doc_rx0302', source_page: 1 },
    ],
    allergies: [
      { id: 'alg_101', substance: 'Penicillin', reaction: 'anaphylaxis', recorded_at: '2019-06-14' },
    ],
    imaging: [],
    notes: [],
    vitals: [],
  },
};

// referenced above by span() only for readability; retained for provenance math
export const PROVENANCE_ANCHORS = { P1_ENC, P1_MED, P1_WAR, P1_LIS };

/* ------------------------------------------------------------------ */
/* Graph built the same way ClinicalGraph builds it                   */
/* ------------------------------------------------------------------ */

const ANALYTES = {
  '2160-0': { display: 'Creatinine', unit: 'mg/dL', lo: 0.6, hi: 1.3, worseHigh: true },
  '2951-2': { display: 'Sodium', unit: 'mmol/L', lo: 135.0, hi: 145.0, worseHigh: false },
  '2823-3': { display: 'Potassium', unit: 'mmol/L', lo: 3.5, hi: 5.1, worseHigh: true },
  '6301-6': { display: 'INR', unit: '', lo: 2.0, hi: 3.0, worseHigh: true },
};

export function buildGraph(patient) {
  const nodes = {};
  const edges = [];
  const byType = {};
  const add = (id, type, time, payload) => {
    nodes[id] = { id, type, time, ...payload };
    (byType[type] = byType[type] || []).push(id);
  };

  patient.encounters.forEach((e) => add(e.id, 'Encounter', e.start, { ...e }));
  patient.diagnoses.forEach((d) => add(d.id, 'Diagnosis', d.onset, { ...d }));
  patient.labs.forEach((l) => {
    const a = ANALYTES[l.loinc];
    add(l.id, 'LabResult', l.observed_at, {
      ...l,
      display: a ? a.display : l.loinc,
      hi_is_worse: a ? a.worseHigh : true,
    });
  });
  patient.meds.forEach((m) => add(m.id, 'MedicationOrder', m.start, { ...m }));
  patient.allergies.forEach((a) => add(a.id, 'Allergy', a.recorded_at, { ...a }));
  patient.imaging.forEach((i) => add(i.id, 'ImagingStudy', i.reported_at, { ...i }));
  patient.notes.forEach((n) => add(n.id, 'Note', n.observed_at, { ...n }));
  patient.vitals.forEach((v) => {
    if (v.points && v.points.length) add(v.id, 'VitalSeries', v.points[0][0], { ...v });
  });

  const enc = (byType.Encounter || []).slice().sort((a, b) => (nodes[a].time < nodes[b].time ? -1 : 1));
  enc.forEach((e) => {
    Object.keys(byType).forEach((t) => {
      byType[t].forEach((n) => {
        if (n !== e && nodes[n].time >= nodes[e].time && nodes[n].time < '2999') {
          edges.push([n, e, 'occurs_during']);
        }
      });
    });
  });
  for (let i = 1; i < enc.length; i += 1) edges.push([enc[i - 1], enc[i], 'precedes']);

  // penicillin allergy vs aspirin — the offline demo's typed contraindication
  const algs = byType.Allergy || [];
  const meds = byType.MedicationOrder || [];
  algs.forEach((a) => {
    meds.forEach((m) => {
      const rx = nodes[m].name || '';
      if (rx && nodes[a].substance && rx.toLowerCase().includes(nodes[a].substance.toLowerCase())) {
        edges.push([a, m, 'contraindicated_with']);
      }
    });
  });

  const stats = {
    nodes: Object.keys(nodes).length,
    edges: edges.length,
    by_type: Object.fromEntries(
      Object.entries(byType).map(([k, v]) => [k, v.length]),
    ),
    edge_types: edges.reduce((acc, [, , t]) => {
      acc[t] = (acc[t] || 0) + 1;
      return acc;
    }, {}),
  };

  return { patient_id: patient.id, nodes: Object.values(nodes), edges, stats };
}

Object.values(PATIENT_DETAIL).forEach((p) => {
  const g = buildGraph(p);
  const row = PATIENTS.find((r) => r.id === p.id);
  if (row) row.node_count = g.stats.nodes;
});

/* ------------------------------------------------------------------ */
/* Fallback /api/ask responses                                         */
/* ------------------------------------------------------------------ */

export const ASK_ANSWERED = {
  patient_id: 'pat_001',
  query: 'Is the renal function deteriorating?',
  plan: { intent: 'trend', entity: 'creatinine', window_months: 12 },
  refused: false,
  refusal_reason: null,
  status: 'answered',
  published: [
    {
      claim_id: 'clm_0007',
      text: 'Renal function is deteriorating: creatinine rose from 0.85 mg/dL to 1.48 mg/dL over 9 months, crossing the 1.30 mg/dL upper reference limit at the 2025-01-16 draw.',
      claim_type: 'deterioration',
      severity: 'high',
      cited_nodes: ['lab_cr_01', 'lab_cr_02', 'lab_cr_03', 'lab_cr_04', 'dx_ckd3'],
      raw_confidence: 0.93,
      verdict: 'ENTAILED',
      calibrated_score: 0.91,
      final: true,
      abstained: false,
      reason: '',
    },
  ],
  abstained: [],
  audit_ref: 'audit/0041',
};

export const ASK_REFUSED = {
  patient_id: 'pat_001',
  query: "What is this patient's blood type?",
  plan: { intent: 'lookup', entity: 'blood_type', window_months: null },
  refused: true,
  refusal_reason:
    'no blood-bank or transfusion resource exists in this record schema — the concept is not representable, so no query plan was executed',
  status: 'refused',
  missing: ['blood_bank'],
  missing_evidence: 'no ABO/Rh resource in the record schema',
  published: [],
  abstained: [
    {
      action: 'REFUSED',
      message:
        'This record cannot support an answer to that question: no blood-bank or transfusion resource exists in this record schema.',
      escalate_to: 'records request — data not captured in this schema',
    },
  ],
  audit_ref: 'audit/0042',
};

export const UPLOAD_RESULT = {
  doc_id: 'doc_lab0425',
  kind: 'lab_report',
  sha256: '0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0',
  filename: 'quest_renal_panel_2025-04-15.pdf',
  facts: [
    {
      kind: 'lab', name: 'Creatinine', value: 1.48, unit: 'mg/dL',
      timestamp: '2025-04-15', loinc: '2160-0',
      ref_low: 0.6, ref_high: 1.3, abnormal: true, negated: false, meta: {},
      source_doc_id: 'doc_lab0425', source_page: 1,
      source_char_start: LAB_PAGE.indexOf('1.48'),
      source_char_end: LAB_PAGE.indexOf('1.48') + 4,
      extractor: 'regex',
    },
    {
      kind: 'lab', name: 'eGFR', value: 41, unit: 'mL/min/1.73m2',
      timestamp: '2025-04-15', loinc: '33914-3',
      ref_low: 90, ref_high: 140, abnormal: true, negated: false, meta: {},
      source_doc_id: 'doc_lab0425', source_page: 1,
      source_char_start: LAB_PAGE.indexOf('41'),
      source_char_end: LAB_PAGE.indexOf('41') + 2,
      extractor: 'regex',
    },
    {
      kind: 'lab', name: 'Potassium', value: 5.2, unit: 'mmol/L',
      timestamp: '2025-04-15', loinc: '2823-3',
      ref_low: 3.5, ref_high: 5.1, abnormal: true, negated: false, meta: {},
      source_doc_id: 'doc_lab0425', source_page: 1,
      source_char_start: LAB_PAGE.indexOf('5.20'),
      source_char_end: LAB_PAGE.indexOf('5.20') + 4,
      extractor: 'regex',
    },
    {
      kind: 'lab', name: 'Sodium', value: 131.0, unit: 'mmol/L',
      timestamp: '2025-04-15', loinc: '2951-2',
      ref_low: 135.0, ref_high: 145.0, abnormal: true, negated: false, meta: {},
      source_doc_id: 'doc_lab0425', source_page: 1,
      source_char_start: LAB_PAGE.indexOf('131.0'),
      source_char_end: LAB_PAGE.indexOf('131.0') + 5,
      extractor: 'regex',
    },
  ],
  pages: [{ page_no: 1, chars: LAB_PAGE.length, kind: 'lab_report' }],
};

/* ------------------------------------------------------------------ */
/* Live-only extras the fallback deliberately omits                    */
/* ------------------------------------------------------------------ */

export const FALLBACK_LIMITATIONS = [
  'This build is running against the inline fallback dataset, not a live backend. Every figure on screen describes synthetic demo records.',
  'The robustness sweep and planted-truth accuracy figures require the Python benchmark harness (`python -m axiom.bench`) and are not derivable from the HTTP API alone.',
  'Claim calibration is only as good as the labelling set the calibrator was fit on; the shipped isotonic fit is a five-point curve, not a measured reliability diagram.',
];