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
  assert.match(html, /홈/);
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
  const configText = fs.readFileSync(configUrl, 'utf8')
    .replace(/^.*\/\/.*$/gm, '') as string;
  const config = JSON.parse(configText) as Record<string, unknown>;

  assert.equal(config.name, 'b64-ai-reward-router');
  assert.equal(config.main, 'dist/src/worker.js');
  assert.equal(config.workers_dev, true);
  assert.equal(config.preview_urls, true);
  assert.equal('routes' in config, false);
  assert.equal('route' in config, false);
  assert.equal('custom_domains' in config, false);
  assert.equal('account_id' in config, false);
});

test('B64 Worker config declares the income D1 binding matching the worker env contract', () => {
  const configUrl = new URL('../../wrangler.jsonc', import.meta.url);
  const configText = fs.readFileSync(configUrl, 'utf8').replace(/^.*\/\/.*$/gm, '');
  const config = JSON.parse(configText) as {
    d1_databases?: { binding: string; database_name: string; database_id: string; migrations_dir: string }[];
    services?: { binding: string; service: string }[];
  };

  const binding = config.d1_databases?.find((db) => db.binding === 'B64_INCOME_DB');
  assert.ok(binding, 'wrangler.jsonc must declare the B64_INCOME_DB D1 binding');
  assert.equal(binding.database_name, 'padiem-b64');
  assert.equal(binding.migrations_dir, 'migrations/d1');

  const chatService = config.services?.find((svc) => svc.binding === 'PADIEM_CHAT_SERVICE');
  assert.ok(chatService, 'wrangler.jsonc must declare the PADIEM_CHAT_SERVICE liveness relay binding');
  assert.equal(chatService.service, 'padiem-chat');

  const migrationUrl = new URL('../../migrations/d1/0001_b64_user_income.sql', import.meta.url);
  const migrationSql = fs.readFileSync(migrationUrl, 'utf8');
  assert.match(migrationSql, /CREATE TABLE IF NOT EXISTS b64_user_income/);
  assert.match(migrationSql, /PRIMARY KEY \(user_id, id\)/);
  assert.ok(migrationSql.includes('idx_b64_user_income_user_updated'));

  const workerUrl = new URL('../../src/worker.ts', import.meta.url);
  const workerSource = fs.readFileSync(workerUrl, 'utf8');
  assert.ok(workerSource.includes('B64_INCOME_DB'), 'worker.ts must read the B64_INCOME_DB binding');
  assert.ok(workerSource.includes('PADIEM_SESSION_SECRET'), 'worker.ts must read the PADIEM_SESSION_SECRET secret');
  assert.ok(workerSource.includes('PADIEM_B64_PUBLIC_BASE_URL'), 'worker.ts must read the reviewed public origin');
  assert.ok(workerSource.includes('PADIEM_CHAT_SERVICE'), 'worker.ts must read the liveness relay binding');

  const storeUrl = new URL('../../src/income-pipeline/store.ts', import.meta.url);
  const storeSource = fs.readFileSync(storeUrl, 'utf8');
  assert.ok(!storeSource.includes('DELETE FROM'), 'the repository contract must not carry a wipe-everything path');
});
