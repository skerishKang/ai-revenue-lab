import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createPublicSupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import { buildIncomePipelineViewModel, renderIncomePipelineWeb } from '../src/income-pipeline/consumer-view.js';
import { B64_FONT_STYLESHEET_HREF } from '../src/ui/theme.js';

/**
 * #6077: B64's design tokens have named Pretendard since #6006, but the Worker
 * shipped no @font-face, so the typeface only rendered on machines that already
 * had it installed. These tests hold the two halves of the fix — the files are
 * actually present and reachable, and the CSP is widened only as far as a
 * same-origin font needs.
 */

const handler = createPublicSupplyConsumerHttpHandler();
const FONT_CSS_ON_DISK = new URL('../../public/fonts/pretendard/pretendard-variable-dynamic-subset.css', import.meta.url);

async function htmlAt(path: string): Promise<string> {
  return (await handler(new Request(`https://b64.example${path}`))).text();
}

test('every consumer shell asks for the Pretendard stylesheet', async () => {
  for (const path of ['/', '/browse', '/today', '/detail?id=pub-prolific-participate']) {
    const html = await htmlAt(path);
    assert.ok(html.includes(`<link rel="stylesheet" href="${B64_FONT_STYLESHEET_HREF}" />`),
      `${path} must load the same font declaration as the pipeline`);
  }
  const pipeline = renderIncomePipelineWeb(buildIncomePipelineViewModel({ userId: null, records: [] }));
  assert.ok(pipeline.includes(B64_FONT_STYLESHEET_HREF), 'the signed-out pipeline loads it too');
});

test('the stylesheet the pages reference is the file that ships', () => {
  assert.equal(B64_FONT_STYLESHEET_HREF, '/fonts/pretendard/pretendard-variable-dynamic-subset.css');
  assert.ok(fs.existsSync(FONT_CSS_ON_DISK), 'the declared stylesheet must exist in the assets directory');
});

test('every url the stylesheet declares resolves to a real asset', () => {
  const css = fs.readFileSync(FONT_CSS_ON_DISK, 'utf8');
  const urls = css
    .match(/url\((\.?\/?[^)]+\.woff2)\)/g)
    ?.map((entry) => entry.slice(4, -1)) ?? [];
  assert.ok(urls.length >= 90, `the dynamic subset should declare its full slice set, saw ${urls.length}`);
  const missing = urls.filter((relative) => {
    const target = new URL(relative.replace(/^\.\//, ''), FONT_CSS_ON_DISK);
    return !fs.existsSync(target);
  });
  assert.deepEqual(missing, [], 'a missing slice would answer 404 for exactly the glyphs in its range');
});

test('the official license travels with the fonts', () => {
  const license = fs.readFileSync(new URL('../../public/fonts/LICENSE-Pretendard.txt', import.meta.url), 'utf8');
  assert.match(license, /SIL OPEN FONT LICENSE/i, 'Pretendard is redistributed under OFL 1.1');
  const css = fs.readFileSync(FONT_CSS_ON_DISK, 'utf8');
  assert.match(css, /Kil Hyung-jin/, 'the copyright header stays in the shipped stylesheet');
});

test('the CSP grows only as far as a same-origin font needs', async () => {
  const response = await handler(new Request('https://b64.example/'));
  const csp = response.headers.get('content-security-policy') ?? '';
  assert.match(csp, /font-src 'self'/, 'the font must come from B64 itself, not a third-party host');
  assert.match(csp, /style-src 'self' 'unsafe-inline'/, 'the linked stylesheet must load, inline CSS must keep working');
  // The protections that must not move.
  assert.match(csp, /default-src 'none'/);
  assert.match(csp, /script-src 'none'/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.match(csp, /base-uri 'none'/);
  assert.match(csp, /form-action 'self'/);
  assert.doesNotMatch(csp, /\*/, 'no wildcard is introduced');
  assert.doesNotMatch(csp, /https?:/, 'no external origin is introduced');
});

test('the design tokens still lead with Pretendard and nothing else moved', async () => {
  const html = await htmlAt('/');
  assert.match(html, /font-family: "Pretendard Variable", Pretendard, "Apple SD Gothic Neo"/);
  assert.match(html, /--fs-display: clamp\(/, 'the #6006 type scale is untouched');
});
