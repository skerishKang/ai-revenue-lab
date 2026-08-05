import fs from 'node:fs';

const h = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const j = fs.readFileSync(new URL('../scripts/review.js', import.meta.url), 'utf8');
const c = fs.readFileSync(new URL('../styles/main.css', import.meta.url), 'utf8');

const s = ['cover', 'intake', 'signals', 'conflicts', 'impact', 'handoff', 'mobile'];

for (const x of s) {
  if (!h.includes(`data-state="${x}"`) || !h.includes(`data-panel="${x}"`)) throw Error(x);
}
if ((h.match(/role="tabpanel"/g) || []).length !== 7) throw Error('states');
if (!j.includes('animationend') || j.includes('setTimeout')) throw Error('motion');
for (const x of ['DIRECT USER FEEDBACK', 'CONFLICTING FEEDBACK', 'MISSING FEEDBACK', 'NO AUTOMATIC WINNER', 'ACTION AUTHORITY — HUMAN ONLY', 'EXECUTION WITHHELD']) {
  if (!h.includes(x)) throw Error(x);
}

function tagWith(html, attr, value) {
  const re = new RegExp(`<([a-z]+)[^>]*${attr}="${value}"[^>]*>`, 'i');
  const m = html.match(re);
  if (!m) throw Error(`missing element ${attr}=${value}`);
  return m[0];
}
function attr(tag, name) {
  const m = tag.match(new RegExp(`${name}="([^"]*)"`, 'i'));
  return m ? m[1] : null;
}

const seenIds = new Set();
for (const x of s) {
  const tab = tagWith(h, 'data-state', x);
  const panel = tagWith(h, 'data-panel', x);
  const tabId = attr(tab, 'id');
  const panelId = attr(panel, 'id');
  const controls = attr(tab, 'aria-controls');
  const labelledby = attr(panel, 'aria-labelledby');
  if (!tabId) throw Error(`tab ${x} missing id`);
  if (!panelId) throw Error(`panel ${x} missing id`);
  if (tabId !== `tab-${x}`) throw Error(`tab ${x} id ${tabId}`);
  if (panelId !== `panel-${x}`) throw Error(`panel ${x} id ${panelId}`);
  if (controls !== panelId) throw Error(`tab ${x} aria-controls ${controls} != ${panelId}`);
  if (labelledby !== tabId) throw Error(`panel ${x} aria-labelledby ${labelledby} != ${tabId}`);
  for (const id of [tabId, panelId]) {
    if (seenIds.has(id)) throw Error(`duplicate id ${id}`);
    seenIds.add(id);
  }
}
if ((h.match(/aria-controls="/g) || []).length !== 7) throw Error('aria-controls count');
if ((h.match(/aria-labelledby="/g) || []).length !== 7) throw Error('aria-labelledby count');

const handoffStart = h.indexOf('data-panel="handoff"');
const handoffSection = h.slice(h.lastIndexOf('<section', handoffStart), h.indexOf('</section>', handoffStart));
for (const x of ['CONFLICTING FEEDBACK', 'MISSING FEEDBACK', 'REPRESENTATIVENESS NOT ESTABLISHED', 'NO AUTOMATIC WINNER', 'ACTION AUTHORITY — HUMAN ONLY', 'EXECUTION WITHHELD']) {
  if (!handoffSection.includes(x)) throw Error(`handoff boundary missing ${x}`);
}

function seconds(v) { return Math.round(parseFloat(v) * 1000); }
const riseM = c.match(/\.is-replaying \.motion>\*\{animation:rise ([\d.]+)s/);
if (!riseM) throw Error('rise duration not found');
const precedingDuration = seconds(riseM[1]);
const delays = [...c.matchAll(/\.is-replaying \.motion>\*:nth-child\(\d+\)\{animation-delay:([\d.]+)s\}/g)].map(m => seconds(m[1]));
const maxPrecedingDelay = delays.length ? Math.max(...delays) : 0;
const finalM = c.match(/\.is-replaying #motion-final\{animation:seal ([\d.]+)s ease ([\d.]+)s both\}/);
if (!finalM) throw Error('final seal timing not found');
const finalDuration = seconds(finalM[1]);
const finalDelay = seconds(finalM[2]);
const lastPrecedingEnd = maxPrecedingDelay + precedingDuration;
const finalEnd = finalDelay + finalDuration;
if (precedingDuration !== 420) throw Error(`preceding duration ${precedingDuration}`);
if (maxPrecedingDelay !== 240) throw Error(`max preceding delay ${maxPrecedingDelay}`);
if (lastPrecedingEnd !== 660) throw Error(`last preceding end ${lastPrecedingEnd}`);
if (finalDelay !== 680) throw Error(`final delay ${finalDelay}`);
if (finalDuration !== 100) throw Error(`final duration ${finalDuration}`);
if (!(finalEnd > lastPrecedingEnd)) throw Error(`final end ${finalEnd} !> last preceding ${lastPrecedingEnd}`);
if (!(finalEnd >= 700 && finalEnd <= 800)) throw Error(`final end ${finalEnd} outside 700-800`);

console.log('STATIC_CONTRACT_PASS');
