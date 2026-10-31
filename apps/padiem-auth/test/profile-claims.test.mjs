import test from 'node:test';
import assert from 'node:assert/strict';
import { profileClaimAllowlist, verifiedProfile } from '../profile-claims.mjs';

const fields = ['email', 'email_verified', 'name', 'picture'];
const valid = { sub: 'private-google-sub', email: 'test@example.invalid', email_verified: true, name: 'Test', picture: '' };

test('client without allowlist receives no profile or subject', () => {
  assert.deepEqual(profileClaimAllowlist({}), []);
  assert.equal(verifiedProfile(valid, profileClaimAllowlist({})), null);
});

test('configured service receives only four verified fields, never sub', () => {
  const profile = verifiedProfile(valid, profileClaimAllowlist({profile_claims: fields}));
  assert.deepEqual(profile, {email: valid.email, email_verified: true, name: 'Test', picture: ''});
  assert.equal('sub' in profile, false);
});

test('reject unknown, duplicated, incomplete allowlists and unverified profiles', () => {
  for (const profile_claims of [null, ['email'], [...fields, 'sub'], [...fields, 'email']]) {
    assert.throws(() => profileClaimAllowlist({profile_claims}));
  }
  for (const claims of [{...valid, email_verified: false}, {...valid, email: ''}, {...valid, picture: 123}]) {
    assert.throws(() => verifiedProfile(claims, fields));
  }
});
