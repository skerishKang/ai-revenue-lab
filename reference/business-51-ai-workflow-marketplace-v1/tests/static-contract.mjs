import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');
const html = read('index.html');
const css = read('styles/main.css');
const js = read('scripts/review.js');

const exactStates = ['cover', 'package', 'workflow', 'compatibility', 'evidence', 'listing', 'mobile'];
const requiredLabels = [
  'SYNTHETIC WORKFLOW PACKAGE', 'PUBLISHER — FICTIONAL', 'WORKFLOW OBJECTIVE', 'INTENDED USER',
  'PREREQUISITE', 'AUTHORIZED INPUT', 'ORDERED STEP', 'EXPECTED OUTPUT', 'HUMAN CHECKPOINT',
  'PUBLISHER CLAIM — UNVERIFIED', 'INDEPENDENT VALIDATION', 'CURRENT VERSION',
  'DEPRECATED VERSION — DO NOT INSTALL', 'COMPATIBILITY — LIMITED SCOPE', 'UNSUPPORTED ENVIRONMENT',
  'PERMISSION REQUIRED — NOT GRANTED', 'SAFE TRIAL ONLY', 'PRODUCTION USE NOT APPROVED',
  'LICENCE AND ATTRIBUTION', 'UNRESOLVED CONDITION', 'LISTED PRICE — SYNTHETIC',
  'NO TRANSACTION PERFORMED', 'NOT INSTALLED',
  'MARKETPLACE APPROVAL ≠ LEGAL OR SECURITY CERTIFICATION',
  'HUMAN-APPROVED WORKFLOW MARKETPLACE LISTING', 'VISUAL REFERENCE ONLY',
  'NO LIVE EXECUTION, INSTALLATION, ACCOUNT CONNECTION, OR PAYMENT'
];
const failures = [];
const check = (condition, message) => { if (!condition) failures.push(message); };

const tabStates = [...html.matchAll(/role="tab"[^>]*data-state="([^"]+)"/g)].map((m) => m[1]);
const panelStates = [...html.matchAll(/role="tabpanel"[^>]*data-panel="([^"]+)"/g)].map((m) => m[1]);
check(JSON.stringify(tabStates) === JSON.stringify(exactStates), `tab states mismatch: ${JSON.stringify(tabStates)}`);
check(JSON.stringify(panelStates) === JSON.stringify(exactStates), `panel states mismatch: ${JSON.stringify(panelStates)}`);
check((html.match(/role="tab"/g) || []).length === 7, 'tab count is not 7');
check((html.match(/role="tabpanel"/g) || []).length === 7, 'panel count is not 7');
check(new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1])).size === [...html.matchAll(/id="([^"]+)"/g)].length, 'duplicate IDs found');

for (const state of exactStates) {
  check(html.includes(`id="tab-${state}"`), `missing tab ID ${state}`);
  check(html.includes(`aria-controls="panel-${state}"`), `missing aria-controls ${state}`);
  check(html.includes(`id="panel-${state}"`), `missing panel ID ${state}`);
  check(html.includes(`aria-labelledby="tab-${state}"`), `missing aria-labelledby ${state}`);
}
check(html.includes('aria-selected="true"') && html.includes('tabindex="-1"'), 'ARIA selection or roving tabindex missing');
check(js.includes("ArrowRight") && js.includes("ArrowLeft") && js.includes("Home") && js.includes("End"), 'full tab keyboard controls missing');
check(css.includes(':focus-visible'), 'visible focus styling missing');

for (const label of requiredLabels) check(html.includes(label), `missing authority label: ${label}`);

const assetRefs = [...new Set([...html.matchAll(/(?:src|href)="((?:assets|styles|scripts)\/[^"?]+)/g)].map((m) => m[1]))];
for (const asset of assetRefs) check(fs.existsSync(path.join(root, asset)), `missing local asset: ${asset}`);
const documentedAssets = [...read('IMAGE_SOURCES.md').matchAll(/`assets\/([^`]+)`/g)].map((m) => `assets/${m[1]}`);
check(documentedAssets.length >= 8, `documented asset count below 8: ${documentedAssets.length}`);
for (const asset of documentedAssets) check(fs.existsSync(path.join(root, asset)), `documented asset missing: ${asset}`);
check(documentedAssets.filter((p) => ['package-cover.svg','workflow-route.svg','compatibility-boundary.svg','listing-seal.svg'].some((n) => p.endsWith(n))).length >= 3, 'fewer than 3 focal assets');

check(!/(?:src|href)="https?:\/\//i.test(html), 'external runtime request found in HTML');
check(!/url\(["']?https?:\/\//i.test(css), 'external runtime request found in CSS');
check(!/fetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon/i.test(js), 'runtime network API found in JavaScript');
check(!/install|checkout|buy now|connect account|grant permission/i.test([...html.matchAll(/<button[^>]*>(.*?)<\/button>/gs)].map((m) => m[1]).join(' ')), 'forbidden live action button found');

check(js.includes("addEventListener('animationend'") || js.includes('addEventListener("animationend"'), 'final animationend completion authority missing');
check(js.includes("event.animationName !== 'final-listing'"), 'final animation name guard missing');
check(!js.includes('setTimeout') && !js.includes('setInterval'), 'fixed timer found in application JavaScript');
check(css.includes('650ms') && css.includes('90ms') && css.includes('final-listing'), '740ms final animation timing missing');
check(css.includes('@media (prefers-reduced-motion: reduce)') && js.includes('prefers-reduced-motion: reduce'), 'reduced-motion contract missing');
check(js.includes('motionComplete') && js.includes("dataset.motionComplete = 'true'"), 'motion completion state missing');

for (const label of ['DEPRECATED VERSION — DO NOT INSTALL','PERMISSION REQUIRED — NOT GRANTED','SAFE TRIAL ONLY','UNRESOLVED CONDITION','NO TRANSACTION PERFORMED','NOT INSTALLED']) {
  const persistentStart = html.indexOf('class="persistent-boundaries"');
  const persistentEnd = html.indexOf('</div>', persistentStart);
  check(persistentStart >= 0 && html.slice(persistentStart, persistentEnd).includes(label), `persistent completion boundary missing: ${label}`);
}

if (failures.length) {
  console.error(JSON.stringify({ status: 'FAIL', failures }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({
  status: 'PASS', exactStates, tabs: 7, panels: 7, combinations: 21,
  documentedAssets: documentedAssets.length, externalRuntimeRequests: 0,
  motion: { completionAuthority: 'actual final animationend', nominalMs: 740, fixedTimeout: false },
  reducedMotion: 'immediate complete'
}, null, 2));
