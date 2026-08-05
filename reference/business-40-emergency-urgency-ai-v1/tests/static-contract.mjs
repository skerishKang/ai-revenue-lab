import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = path.resolve(import.meta.dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'styles/main.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'scripts/review.js'), 'utf8');
const states = ['cover','report','indicators','conflicts','review','handoff','mobile'];
const labels = [
'SYNTHETIC TRAINING INCIDENT','SOURCE REPORT — UNVERIFIED','SOURCE PROVENANCE',
'OBSERVABLE INDICATOR — SYNTHETIC','INTERPRETATION — NOT VERIFIED FACT','CONFIDENCE — NOT CERTAINTY',
'MISSING INFORMATION','CONFLICTING EVIDENCE','ALTERNATIVE INTERPRETATION','CLARIFICATION REQUIRED',
'PROVISIONAL URGENCY RATIONALE','HUMAN CORRECTION','FINAL PRIORITY AUTHORITY — HUMAN ONLY',
'NO AUTONOMOUS TRIAGE','NO MEDICAL DIAGNOSIS','NO THREAT PREDICTION','NO DISPATCH OR RESOURCE ALLOCATION',
'UNRESOLVED UNCERTAINTY','HUMAN-REVIEWED URGENCY SUPPORT RECORD','VISUAL REFERENCE ONLY',
'NO LIVE CALL, LOCATION, SENSOR, OR HEALTH-DATA CONNECTION'];
for (const state of states) assert.equal((html.match(new RegExp(`data-state="${state}"`,'g'))||[]).length,1,`state ${state}`);
assert.equal((html.match(/role="tabpanel"/g)||[]).length,7);
assert.equal((html.match(/role="tab"/g)||[]).length,7);
for (const label of labels) assert.ok(html.includes(label),`missing authority label: ${label}`);
const svgRefs = [...html.matchAll(/assets\/[^"?]+\.svg/g)].map(m=>m[0]);
assert.ok(new Set(svgRefs).size >= 11, 'at least 11 SVG references');
assert.ok(!/https?:\/\//.test(html.replace(/https:\/\/ai-revenue-business-40-emergency-urgency-ai\.pages\.dev\//g,'')), 'no external runtime URL');
assert.ok(js.includes("event.animationName !== 'motion-reveal'"));
assert.ok(!js.includes('setTimeout('));
assert.ok(css.includes('animation-delay:680ms'));
assert.ok(css.includes('@media (prefers-reduced-motion:reduce)'));
console.log(JSON.stringify({pass:true,states:states.length,authorityLabels:labels.length,svgRefs:new Set(svgRefs).size,assetVersion:'business-40-v1-20260729'},null,2));
