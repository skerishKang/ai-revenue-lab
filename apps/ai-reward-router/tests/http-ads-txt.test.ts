import test from 'node:test';
import assert from 'node:assert/strict';
import { createEmptySupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import { B64_ADS_TXT_PATH, B64_AYET_ADS_TXT, B64_AYET_ADS_TXT_LINES } from '../src/http/ads-txt.js';

/**
 * ayeT's Ads.txt tab names the lines it expects at the domain root and re-checks
 * the file within 24 hours (#6001, D16). The live placement answered
 * `ads.txt: checking` while `GET /ads.txt` answered 404, so this route is the
 * connection that keeps the placement reviewable.
 */

const handler = createEmptySupplyConsumerHttpHandler();

function get(path: string, method: 'GET' | 'HEAD' | 'POST' = 'GET'): Promise<Response> {
  return handler(new Request(`https://b64.example${path}`, {method}));
}

test('the publisher-required lines are served verbatim', async () => {
  const response = await get(B64_ADS_TXT_PATH);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'text/plain; charset=utf-8');
  const body = await response.text();
  assert.equal(
    body,
    '# AYET-STUDIOS \nayetstudios.com, AYETSTUDIOS, DIRECT\nayetstudios.com, PL-25819, DIRECT\n\n',
  );
  assert.ok(body.includes('# AYET-STUDIOS '), 'the comment line ayeT prints is part of the file');
});

test('every record line is a three-field ads.txt entry', () => {
  const records = B64_AYET_ADS_TXT_LINES.filter((line) => line.trim() !== '' && !line.startsWith('#'));
  assert.equal(records.length, 2);
  for (const line of records) {
    const fields = line.split(',').map((field) => field.trim());
    assert.equal(fields.length, 3, `${line} must be domain, seller id, DIRECT/RESELLER`);
    assert.equal(fields[0], 'ayetstudios.com');
    assert.equal(fields[2], 'DIRECT');
  }
  assert.match(records[1] ?? '', /^ayetstudios\.com, PL-\d+, DIRECT$/, 'the placement line carries the placement id');
});

test('HEAD is answered without a body and POST stays a method error', async () => {
  const head = await get(B64_ADS_TXT_PATH, 'HEAD');
  assert.equal(head.status, 200);
  assert.equal(await head.text(), '');

  const post = await get(B64_ADS_TXT_PATH, 'POST');
  assert.equal(post.status, 405);
});

test('the file is public but keeps the consumer security headers', async () => {
  const response = await get(B64_ADS_TXT_PATH);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.match(response.headers.get('content-security-policy') ?? '', /script-src 'none'/);
  assert.match(response.headers.get('content-security-policy') ?? '', /frame-ancestors 'none'/);
});

test('the new route did not widen the surface for other paths', async () => {
  assert.equal((await get('/app-ads.txt')).status, 404);
  assert.equal((await get('/ads.txt/extra')).status, 404);
  assert.equal((await get('/ads-txt')).status, 404);
});

test('the exported body and the exported lines cannot drift apart', () => {
  assert.equal(B64_AYET_ADS_TXT, `${B64_AYET_ADS_TXT_LINES.join('\n')}\n`);
  assert.ok(B64_AYET_ADS_TXT.endsWith('\n\n'), 'ayeT prints a trailing blank line');
});
