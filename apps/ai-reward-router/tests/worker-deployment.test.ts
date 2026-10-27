import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import worker from '../src/worker.js';

test('dedicated Worker home leads with verified public supply, ad lane stays honest (#5830)', async () => {
  const response = await worker.fetch(new Request('https://b64.example/'));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /text\/html/);

  const html = await response.text();
  assert.match(html, /data-public-card-count="6"/, 'verified public opportunities are the first actionable content');
  assert.match(html, /data-empty-state="NO_LIVE_REWARD_SUPPLY"/, 'the unapproved ad lane keeps its honest status');
  assert.match(html, /공급자 승인 대기/);
  assert.doesNotMatch(html, /지금 바로|즉시 적립|바로 적립 가능/, 'no unapproved lane is advertised as startable');
  assert.doesNotMatch(html, /publisher|onboarding|API key/i);
  assert.match(html, /홈/);
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
    .replace(/^\s*\/\/.*$/gm, '') as string;
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
  const configText = fs.readFileSync(configUrl, 'utf8').replace(/^\s*\/\/.*$/gm, '');
  const config = JSON.parse(configText) as {
    d1_databases?: { binding: string; database_name: string; database_id: string; migrations_dir: string }[];
    services?: { binding: string; service: string }[];
    vars?: Record<string, string>;
  };

  const binding = config.d1_databases?.find((db) => db.binding === 'B64_INCOME_DB');
  assert.ok(binding, 'wrangler.jsonc must declare the B64_INCOME_DB D1 binding');
  assert.equal(binding.database_name, 'padiem-b64');
  assert.equal(binding.migrations_dir, 'migrations/d1');

  // Independence (owner decision 2026-10-27): B64 authenticates its own
  // members, so it binds no other product's Worker. A service binding here
  // would mean B64 login depends on another product staying up.
  assert.equal(config.services, undefined, 'wrangler.jsonc must declare no service bindings');

  const vars = config.vars as Record<string, string> | undefined;
  const origin = vars?.B64_PUBLIC_BASE_URL;
  assert.ok(origin, 'the reviewed mutation origin must be declared for the same-origin guard');
  assert.ok(origin.startsWith('https://'), origin);
  assert.notEqual(origin, 'https://chat.padiem.net', 'B64 does not assume another product origin');

  const migrationUrl = new URL('../../migrations/d1/0001_b64_user_income.sql', import.meta.url);
  const migrationSql = fs.readFileSync(migrationUrl, 'utf8');
  assert.match(migrationSql, /CREATE TABLE IF NOT EXISTS b64_user_income/);
  assert.match(migrationSql, /PRIMARY KEY \(user_id, id\)/);
  assert.ok(migrationSql.includes('idx_b64_user_income_user_updated'));

  const accountMigration = fs.readFileSync(
    new URL('../../migrations/d1/0002_b64_member.sql', import.meta.url),
    'utf8',
  );
  assert.match(accountMigration, /CREATE TABLE IF NOT EXISTS b64_member/);
  assert.match(accountMigration, /UNIQUE \(email\)/, 'one account per address is a storage rule, not only a code path');
  assert.match(accountMigration, /CREATE TABLE IF NOT EXISTS b64_session/);

  const workerUrl = new URL('../../src/worker.ts', import.meta.url);
  const workerSource = fs.readFileSync(workerUrl, 'utf8');
  assert.ok(workerSource.includes('B64_INCOME_DB'), 'worker.ts must read the B64_INCOME_DB binding');
  assert.ok(workerSource.includes('B64_SESSION_SECRET'), 'worker.ts must read B64 own session key');
  assert.ok(workerSource.includes('B64_PUBLIC_BASE_URL'), 'worker.ts must read the reviewed public origin');
  for (const coupling of ['PADIEM_SESSION_SECRET', 'PADIEM_CHAT_SERVICE', 'CONTROL_PLANE_IDENTITY']) {
    assert.ok(!workerSource.includes(coupling), `worker.ts must not depend on ${coupling}`);
  }

  const storeUrl = new URL('../../src/income-pipeline/store.ts', import.meta.url);
  const storeSource = fs.readFileSync(storeUrl, 'utf8');
  assert.ok(!storeSource.includes('DELETE FROM'), 'the repository contract must not carry a wipe-everything path');
});

test('B64 serves its whole consumer surface on its own host (#987 independence)', async () => {
  const own = 'https://b64-ai-reward-router.charliekant.workers.dev';
  for (const path of ['/', '/earn', '/today', '/browse', '/pipeline', '/income', '/healthz']) {
    const response = await worker.fetch(new Request(`${own}${path}`));
    assert.equal(response.status, 200, `${path} must answer on the B64 host`);
  }
  assert.equal((await worker.fetch(new Request(`${own}/detail?id=pub-prolific-participate`))).status, 200);

  // The account entry is on the same host: no other product's origin, login
  // page or Worker appears in the anonymous dashboard.
  const anonymous = await (await worker.fetch(new Request(`${own}/pipeline`))).text();
  assert.match(anonymous, /action="\/join"/, 'the join form is served by B64 itself');
  assert.match(anonymous, /action="\/login"/, 'the login form is served by B64 itself');
  assert.doesNotMatch(anonymous, /PADIEM 계정/);

  // A stray GET on a POST-only identity endpoint lands somewhere useful.
  const stray = await worker.fetch(new Request(`${own}/join`));
  assert.equal(stray.status, 303);
  assert.equal(stray.headers.get('location'), '/pipeline');
});

test('no repository config assigns B64 to another product origin (owner decision 2026-10-27)', () => {
  const configText = fs.readFileSync(new URL('../../wrangler.jsonc', import.meta.url), 'utf8');
  assert.ok(!/chat\.padiem\.net/.test(configText), 'B64 config must not name another product origin');
});
