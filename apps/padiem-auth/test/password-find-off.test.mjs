// #7679 password find is a second switch on top of the #7652 recovery switch.
// With it off, the recovery surface must be exactly what it was: every screen,
// every answer and every call made to Chat.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createApp } from '../worker.mjs';
import { findOffResponses } from './password-find-off-fixture.mjs';

const baseline = JSON.parse(readFileSync(new URL('./password-find-off-baseline.json', import.meta.url), 'utf8'));
const records = async (options) => (await findOffResponses(createApp, options)).map(({ body, ...record }) => record);

test('recovery ON and password find OFF keeps the pre-change bytes and the pre-change Chat calls', async () => {
  assert.deepEqual(await records(), baseline.responses);
});

test('anything but an explicit true leaves password find off, and a deferral hook changes nothing while it is off', async () => {
  for (const passwordFindEnabled of [false, 'false', '', '1', 'yes', null]) {
    assert.deepEqual(await records({ passwordFindEnabled }), baseline.responses, String(passwordFindEnabled));
  }
  const deferred = [];
  assert.deepEqual(await records({ defer: work => deferred.push(work) }), baseline.responses);
  assert.equal(deferred.length, 0, 'the request is still answered after its work, as before');
});

test('password find ON changes the recovery screens and the entry, and nothing else in the capture', async () => {
  const changed = await findOffResponses(createApp, { passwordFindEnabled: true });
  const before = new Map(baseline.responses.map(record => [record.name, record]));
  const different = changed.filter(record => record.body_sha256 !== before.get(record.name).body_sha256).map(record => record.name);
  assert.deepEqual(different, [
    // The entry link is renamed on every form screen and the neutral refusal names it.
    'plain-login-ko', 'plain-signup-ko', 'brand-login-en', 'brand-signup-en',
    'signup-ownership-refused', 'signup-existing-chat', 'login-wrong-password', 'login-epoch-refused', 'login-deleted',
    'recovery-request-page-ko', 'recovery-request-page-en', 'recovery-confirm-page-ko', 'recovery-confirm-page-en',
    'recovery-request-absent-target', 'recovery-request-absent-not-target', 'recovery-request-live-account', 'recovery-request-invalid-email',
    'recovery-confirm-malformed', 'recovery-confirm-refused', 'recovery-confirm-complete',
  ]);
  // Status codes and headers do not move, and a finished login is untouched.
  for (const record of changed) {
    assert.equal(record.status, before.get(record.name).status, record.name);
    assert.equal(record.headers_sha256, before.get(record.name).headers_sha256, record.name);
  }
  // A restoration is still requested with the same calls as before.
  for (const name of ['recovery-request-absent-target', 'recovery-request-absent-not-target', 'recovery-request-invalid-email']) {
    assert.equal(changed.find(record => record.name === name).calls_sha256, before.get(name).calls_sha256, name);
  }
});
