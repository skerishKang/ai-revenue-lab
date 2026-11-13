import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createApp } from '../worker.mjs';
import { offResponses } from './email-recovery-off-fixture.mjs';

test('switch OFF preserves exact pre-change signup and login response bytes', async () => {
  const baseline = JSON.parse(readFileSync(new URL('./email-recovery-off-baseline.json', import.meta.url), 'utf8'));
  const actual = (await offResponses(createApp)).map(({ body, ...record }) => record);
  assert.deepEqual(actual, baseline.responses);
});

test('enabled recovery entry is shown to every signup and login visitor and refusals are neutral', async () => {
  const responses = await offResponses(createApp, { enabled: true });
  for (const result of responses.filter(value => value.status === 200)) {
    assert.match(result.body, /href="\/password\/recovery"/);
    if (result.name.startsWith('brand-')) assert.match(result.body, /Recover your email account/);
  }
  for (const name of ['signup-ownership-refused', 'signup-existing-chat', 'login-epoch-refused']) {
    const { body } = responses.find(value => value.name === name);
    assert.doesNotMatch(body, /이미 PADIEM 계정이 있는 이메일|이미 사용 중인 이메일|이 이메일의 PADIEM 계정/);
    assert.match(body, /이메일 계정 복구/);
  }
});
