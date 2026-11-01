/**
 * The front door must not hand a browser a JSON body.
 *
 * A navigation (Accept names text/html, which every browser sends) gets the
 * Korean page and one retry link. Everything else keeps the exact JSON it
 * parses today — including the requests these tests' predecessors used, which
 * sent no Accept header at all and therefore never exercised the browser case
 * that reached the owner as `{"error":{"code":"upstream_timeout",…}}`.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createFront } from '../worker.mjs';
import { copyFor, errorPageHtml, wantsHtml } from '../error-copy.mjs';

const ORIGIN = 'https://host.example';
const sign = async (request) => new Headers(request.headers);
const env = { FRONT_ORIGIN: ORIGIN, UPSTREAM_TIMEOUT_MS: '5', FALLBACK_MODE: 'static' };

function slow() {
  return async (input) => {
    await new Promise((resolve) => setTimeout(resolve, 40));
    if (input.signal && input.signal.aborted) throw new DOMException('aborted', 'AbortError');
    return new Response('too late', { status: 200 });
  };
}

const BROWSER_ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8';

test('a browser navigation that times out gets a Korean page, not the JSON body', async () => {
  const handle = createFront({ sign, fetchImpl: slow() });
  const response = await handle(new Request('https://chat.padiem.net/', {
    headers: { accept: BROWSER_ACCEPT },
  }), env);
  const body = await response.text();
  assert.equal(response.status, 504);
  assert.match(response.headers.get('content-type'), /text\/html/);
  assert.match(body, /<html lang="ko">/);
  assert.match(body, /응답이 너무 오래 걸려서 멈췄어요/);
  assert.match(body, /다시 시도/);
  // The machine-readable code stays out of the page the owner reads.
  assert.doesNotMatch(body, /upstream_timeout/);
  assert.doesNotMatch(body, /"error"/);
});

test('an API call keeps the JSON contract it parses', async () => {
  const handle = createFront({ sign, fetchImpl: slow() });
  const response = await handle(new Request('https://chat.padiem.net/api/conversations', {
    headers: { accept: 'application/json' },
  }), { ...env, API_READ_TIMEOUT_MS: '5' });
  assert.equal(response.status, 504);
  assert.match(response.headers.get('content-type'), /application\/json/);
  assert.equal((await response.json()).error.code, 'upstream_timeout');
});

test('a request that names no Accept keeps today behaviour exactly', async () => {
  const handle = createFront({ sign, fetchImpl: slow() });
  const response = await handle(new Request('https://chat.padiem.net/api/conversations'),
    { ...env, API_READ_TIMEOUT_MS: '5' });
  assert.equal((await response.json()).error.code, 'upstream_timeout');
});

test('a transport failure on a navigation reads as 연결 실패, not as a status code', async () => {
  const handle = createFront({ sign, fetchImpl: async () => { throw new Error('socket hang up'); } });
  const response = await handle(new Request('https://chat.padiem.net/some/page', {
    headers: { accept: BROWSER_ACCEPT },
  }), env);
  const body = await response.text();
  assert.equal(response.status, 502);
  assert.match(body, /서버와 연결하지 못했어요/);
  assert.doesNotMatch(body, /502|upstream_transport_failed/);
});

test('the login callback sends its retry back to the front page, without the query', async () => {
  const handle = createFront({ sign, fetchImpl: slow() });
  const response = await handle(new Request(
    'https://chat.padiem.net/auth/shared/callback?state=SECRETSTATE&code=SECRETCODE',
    { headers: { accept: BROWSER_ACCEPT } },
  ), { ...env, AUTH_CALLBACK_TIMEOUT_MS: '5' });
  const body = await response.text();
  assert.match(body, /href="\/"/);
  // state and code never reach the rendered page.
  assert.doesNotMatch(body, /SECRETSTATE|SECRETCODE/);
});

test('an unknown code falls back to the generic sentence and escapes the path', () => {
  assert.equal(copyFor('not_a_known_code').title, '요청을 처리하지 못했어요');
  const page = errorPageHtml('upstream_timeout', '/"><script>alert(1)</script>');
  assert.doesNotMatch(page, /<script>alert/);
  assert.match(page, /&lt;script&gt;/);
});

test('wantsHtml only answers yes to a request that names text/html', () => {
  const yes = new Request('https://chat.padiem.net/', { headers: { accept: BROWSER_ACCEPT } });
  const no = new Request('https://chat.padiem.net/', { headers: { accept: 'application/json' } });
  assert.equal(wantsHtml(yes), true);
  assert.equal(wantsHtml(no), false);
  assert.equal(wantsHtml(undefined), false);
});
