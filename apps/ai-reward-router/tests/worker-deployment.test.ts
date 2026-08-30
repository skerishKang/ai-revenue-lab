import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import worker from '../src/worker.js';

test('dedicated Worker serves honest zero-supply P0 consumer surface', async () => {
  const response = await worker.fetch(new Request('https://b64.example/'));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /text\/html/);

  const html = await response.text();
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/);
  assert.match(html, /바로 적립/);
  assert.doesNotMatch(html, /설문|마이크로태스크|단기 프로젝트|구직/);
});

test('dedicated Worker health route keeps live provider permission disabled', async () => {
  const response = await worker.fetch(new Request('https://b64.example/healthz'));
  assert.equal(response.status, 200);

  const body = await response.json() as Record<string, unknown>;
  assert.equal(body.service, 'b64-ai-reward-router');
  assert.equal(body.supplyActivation, 'OWNER_ACTION_PENDING');
  assert.equal(body.providerPermissionGranted, false);
});

test('dedicated Worker preserves method and unknown-route fail-closed guards', async () => {
  const post = await worker.fetch(new Request('https://b64.example/earn', { method: 'POST' }));
  assert.equal(post.status, 405);
  assert.equal(post.headers.get('allow'), 'GET, HEAD');

  const missing = await worker.fetch(new Request('https://b64.example/survey'));
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), 'Not Found');
});

test('B64 Worker config is independent and declares no DNS or production route mutation', () => {
  const configUrl = new URL('../../wrangler.jsonc', import.meta.url);
  const config = JSON.parse(fs.readFileSync(configUrl, 'utf8')) as Record<string, unknown>;

  assert.equal(config.name, 'b64-ai-reward-router');
  assert.equal(config.main, 'dist/src/worker.js');
  assert.equal(config.workers_dev, true);
  assert.equal(config.preview_urls, true);
  assert.equal('routes' in config, false);
  assert.equal('route' in config, false);
  assert.equal('custom_domains' in config, false);
  assert.equal('account_id' in config, false);
});
