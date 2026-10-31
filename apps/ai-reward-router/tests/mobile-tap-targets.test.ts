import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicSupplyConsumerHttpHandler } from '../src/http/consumer-http.js';

/**
 * #6074, measured at 390px on workers.dev: the primary buttons were 44-46px and
 * the theme toggle 44x44, but the secondary text links — "자세히 보기 →" on every
 * opportunity card and "오늘의 추천 보기 →" under the hero — were 21px and 20px
 * tall. WCAG 2.2 AA target size asks for 24x24 CSS px, and those two sit directly
 * under a large button, which is where a mis-tap costs the visitor.
 *
 * The rendered stylesheet is the contract here: the browser measurement that
 * proves the hit areas are now >= 24px is recorded on the PR, and this test keeps
 * the declaration from being dropped by a later restyle.
 */

const handler = createPublicSupplyConsumerHttpHandler();

async function homeCss(): Promise<string> {
  const response = await handler(new Request('https://b64.example/'));
  assert.equal(response.status, 200);
  return response.text();
}

test('the secondary links carry a 24px minimum hit height', async () => {
  const html = await homeCss();
  const cta = html.match(/\.cta-link \{[^}]*\}/)?.[0] ?? '';
  const detail = html.match(/\.detail-link \{[^}]*\}/)?.[0] ?? '';
  assert.ok(cta.includes('min-height: 24px'), `.cta-link lost its minimum: ${cta}`);
  assert.ok(detail.includes('min-height: 24px'), `.detail-link lost its minimum: ${detail}`);
  for (const rule of [cta, detail]) {
    assert.match(rule, /display: inline-flex/, 'min-height needs a flex box to apply to');
    assert.match(rule, /align-items: center/, 'the label stays centred in the taller box');
  }
});

test('the sizes that already passed are pinned so a restyle cannot shrink them', async () => {
  const html = await homeCss();
  const ctaBtn = html.match(/\.reward-cta \{[\s\S]*?\n    \}/)?.[0] ?? '';
  assert.match(ctaBtn, /min-height: 46px/, 'the card action stays a full-size button');
  const nav = html.match(/\.nav-item \{[^}]*\}/)?.[0] ?? '';
  assert.match(nav, /padding: 7px 13px/, 'the measured 34px nav box comes from this padding');
});

test('the change is CSS only — no new element, script, or colour', async () => {
  const html = await homeCss();
  assert.match(html, /<a class="cta-link cta-link--secondary" href="\/today">오늘의 추천 보기/,
    'the secondary link markup is unchanged');
  assert.doesNotMatch(html, /<script/, 'the consumer surface still ships no script');
});
