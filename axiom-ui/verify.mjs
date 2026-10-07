import React from 'react';
import { renderToString } from 'react-dom/server';
import { createRequire } from 'module';
const require = createRequire('/workspace/axiom-ui/');
const fixture = require('/workspace/axiom-ui/public/fixture.json');
let fails = 0;
const check = (name, ok) => { console.log(`  ${ok?'✓':'✗'} ${name}`); if(!ok) fails++; };

const s1=fixture.scenes[0], s2=fixture.scenes[1], s3=fixture.scenes[2],
      s4=fixture.scenes[3], s5=fixture.scenes[4];
console.log('FIXTURE → UI CONTRACT VERIFICATION\n');

console.log('Scene s1 — patient chart');
check('has patient demographics', !!(s1&&fixture.patient.demographics.name));
check('graph stats present', fixture.graph.stats.nodes>0 && fixture.graph.stats.edges>0);

console.log('\nScene s2 — evidence card');
check('published claims exist', s2.published.length>0);
check('every claim carries citations', s2.published.every(c=>(c.source_records||[]).length>0));
check('every citation has a raw record', s2.published.every(c=>c.source_records.every(r=>r.raw)));
check('every claim verified ENTAILED', s2.published.every(c=>c.verdict==='ENTAILED'));
check('every claim has calibrated score', s2.published.every(c=>typeof c.calibrated_score==='number'));

console.log('\nScene s3 — interaction');
check('interaction claims published', s3.published.length>0);
check('published claims all cited', s3.published.every(c=>(c.cited_nodes||[]).length>=2));
check('contraindication edges in graph', fixture.graph.contraindications.length>0);
check('interaction edges in graph', fixture.graph.interaction_edges.length>0);

console.log('\nScene s4 — THE TURN (refusal)');
check('refused flag true', s4.refused===true);
check('zero published claims', s4.published.length===0);
check('has refusal reason', !!s4.refusal_reason);
check('has audit ref', !!s4.audit_ref);
check('has escalation target', !!(s4.abstained[0]||{}).escalate_to);
check('has abstained record', (s4.abstained||[]).length>0);

console.log('\nSeverity provenance (regression guard)');
// Severity MUST come from the pipeline. An earlier build inferred it in the UI
// by fuzzy string matching and rendered CRITICAL interactions as LOW.
const allPub = fixture.scenes.flatMap(s=>s.published||[]);
check('every published claim carries a severity', allPub.every(c=>typeof c.severity==='string' && c.severity.length>0));
check('at least one CRITICAL finding surfaced', allPub.some(c=>c.severity==='critical'));
check('interaction claims are not all low', allPub.filter(c=>c.claim_type==='medication_interaction').every(c=>['critical','high'].includes(c.severity)));
check('severity values are in the known set', allPub.every(c=>['critical','high','medium','low','info'].includes(c.severity)));

console.log('\nTimeline / trend');
check('trend series >= 4 points', fixture.trend.series.length>=4);
check('trend has reference range', fixture.trend.ref_low<fixture.trend.ref_high);
check('trend summary present', !!fixture.trend.summary);
check('nodes carry type+time', fixture.graph.nodes.every(n=>n.type&&n.time));

console.log('\nBenchmark');
check('detection rate numeric', typeof fixture.benchmark.detection_rate==='number');
check('missed count correct', fixture.benchmark.MISSED===fixture.benchmark.planted_total-fixture.benchmark.planted_detected);
check('5 robustness points', fixture.benchmark.robustness_sweep.length===5);
check('limitations present', fixture.limitations.length>=3);
check('entity resolution reported', typeof fixture.benchmark.entity_resolution.f1==='number');

console.log(fails===0?'\nALL CHECKS PASSED':`\n${fails} FAILURE(S)`);
process.exit(fails?1:0);
