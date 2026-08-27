import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const html = readFileSync(join(root, 'index.html'), 'utf8');
const css = readFileSync(join(root, 'styles/main.css'), 'utf8');
const js = readFileSync(join(root, 'scripts/review.js'), 'utf8');
const exactStates = ['cover','profile','assessment','session','form','adaptation','mobile'];
const labels = [
'SYNTHETIC USER PROFILE','SELF-REPORTED GOAL','SELF-REPORTED CONSTRAINT','MOVEMENT OBSERVATION — NOT DIAGNOSIS','OBSERVATION CONFIDENCE','UNKNOWN / NOT ASSESSED','SESSION PLAN — SYNTHETIC','FORM CUE — GENERAL GUIDANCE','NO AUTOMATED FORM CERTIFICATION','REGRESSION OPTION','PROGRESSION OPTION','USER CHOICE','EXERTION CHECK','STOP OR PAUSE CONDITION','REVIEW CORRECTION','NOT MEDICAL ADVICE','NOT A REHABILITATION PLAN','HUMAN-REVIEWED ADAPTIVE MOVEMENT PLAN','VISUAL REFERENCE ONLY','NO LIVE CAMERA, BIOMETRIC, OR HEALTH-DATA CONNECTION'];

test('implements exact seven states', () => {
  const tabs = [...html.matchAll(/data-state-tab="([^"]+)"/g)].map(m => m[1]);
  const panels = [...html.matchAll(/data-state-panel="([^"]+)"/g)].map(m => m[1]);
  assert.deepEqual(tabs, exactStates);
  assert.deepEqual(panels, exactStates);
});

test('includes all authority labels', () => labels.forEach(label => assert.ok(html.includes(label), label)));

test('contains 11+ local SVG assets and versioned references', () => {
  const svgs = readdirSync(join(root, 'assets')).filter(name => name.endsWith('.svg'));
  assert.ok(svgs.length >= 11);
  svgs.forEach(name => assert.ok(readFileSync(join(root,'assets',name),'utf8').startsWith('<svg')));
  const refs = [...html.matchAll(/assets\/[^"?]+\.svg\?v=b38-atelier-20260729/g)];
  assert.ok(refs.length >= 11);
});

test('uses animationend authority without completion timeout', () => {
  assert.match(js, /addEventListener\('animationend'/);
  assert.match(js, /animationName !== 'motionFinal'/);
  assert.doesNotMatch(js, /setTimeout|setInterval/);
  assert.match(css, /animation-name:motionFinal/);
  assert.match(css, /animation-duration:100ms/);
  assert.match(css, /animation-delay:680ms/);
});

test('supports keyboard tabs and roving tabindex', () => {
  assert.match(js, /ArrowRight/); assert.match(js, /ArrowLeft/); assert.match(js, /Home/); assert.match(js, /End/);
  assert.match(js, /tabIndex = active \? 0 : -1/);
  assert.match(html, /aria-selected="true" tabindex="0"/);
});

test('contains no external runtime URL', () => {
  assert.doesNotMatch(html, /https?:\/\//);
  assert.doesNotMatch(css, /https?:\/\//);
  assert.doesNotMatch(js, /https?:\/\//);
});
