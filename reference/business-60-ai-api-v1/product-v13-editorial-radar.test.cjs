'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = __dirname;
const read = file => fs.readFileSync(path.join(root, file), 'utf8');

test('v13 is wired as the final presentation layer', () => {
  const html = read('index.html');
  assert.match(html, /product-v13-editorial-radar\.css/);
  assert.match(html, /data\/editorial-media\.js/);
  assert.match(html, /product-v13-editorial-radar\.js/);
  assert.ok(html.indexOf('korean-v1.js') < html.indexOf('product-v13-editorial-radar.js'));
});

test('editorial surface uses raster photography and no SVG filler', () => {
  const media = read('data/editorial-media.js');
  const js = read('product-v13-editorial-radar.js');
  assert.doesNotMatch(media, /\.svg(?:[?'"\s]|$)/i);
  assert.doesNotMatch(js, /<svg\b/i);
  assert.ok((media.match(/sourcePage:/g) || []).length >= 5);
});

test('benefit-first information architecture is explicit in native Korean', () => {
  const js = read('product-v13-editorial-radar.js');
  for (const label of ['지금 무료', '상시 무료', '종료 임박', '최근 확인', '확인 중']) {
    assert.match(js, new RegExp(label));
  }
  assert.match(js, /AI 무료 레이더/);
});

test('ending soon still requires verified official expiry evidence', () => {
  const js = read('product-v13-editorial-radar.js');
  assert.match(js, /signal\.expiresAt && signal\.expiryVerification === 'VERIFIED_OFFICIAL_WEB'/);
  assert.match(js, /확인되지 않은 종료일이나 프로모션 문구는 지금 무료\/종료 임박으로 승격하지 않습니다/);
});

test('legacy cinematic is visually dormant while deep explore remains available', () => {
  const css = read('product-v13-editorial-radar.css');
  const js = read('product-v13-editorial-radar.js');
  assert.match(css, /\.cinematic,[\s\S]*\.signal,[\s\S]*\.source[\s\S]*display:\s*none\s*!important/);
  assert.match(js, /document\.getElementById\('explore'\)/);
  assert.match(js, /dispatchEvent\(new PopStateEvent\('popstate'/);
});

test('manual curation presentation remains frontend-only', () => {
  const js = read('product-v13-editorial-radar.js');
  assert.doesNotMatch(js, /fetch\s*\(/);
  assert.doesNotMatch(js, /XMLHttpRequest|WebSocket|EventSource/);
  assert.match(js, /수동 큐레이션/);
});
