import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { googleProductUserId } from '../google_identity_contract.mjs';

test('uses the exact existing Chat Google user id format', async () => {
  for (const subject of ['1234567890', 'stable-subject_2']) {
    const expected = 'usr_' + createHash('sha256').update('google:' + subject, 'utf8').digest('hex').slice(0, 32);
    assert.equal(await googleProductUserId(subject), expected);
  }
});
test('refuses empty, non-text, whitespace and oversize subject', async () => {
  for (const value of ['', null, 'a b', 'a'.repeat(256)]) await assert.rejects(googleProductUserId(value));
});
