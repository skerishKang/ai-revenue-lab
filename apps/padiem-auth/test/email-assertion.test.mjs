import test from 'node:test';
import assert from 'node:assert/strict';
import {
  emailAssertionField, verifyEmailAssertion, EMAIL_ASSERTION_CLIENT,
  EMAIL_ASSERTION_AUDIENCE, EMAIL_ASSERTION_TTL,
} from '../email-assertion.mjs';

const SECRET = 'unit-test-secret-not-a-real-key';
const NOW = 1_760_000_000;
const PROFILE = { email: 'Owner@Example.TEST ', email_verified: true };

async function issue(overrides = {}) {
  return emailAssertionField({
    clientId: EMAIL_ASSERTION_CLIENT, secret: SECRET, profile: PROFILE,
    sub: 'sub_test123', now: NOW, ...overrides,
  });
}

test('서명된 필드는 소문자 이메일과 고정 aud·만료를 담는다', async () => {
  const field = await issue();
  const assertion = field.email_assertion;
  assert.match(assertion, /^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);
  const claim = await verifyEmailAssertion({ assertion, secret: SECRET, now: NOW });
  assert.deepEqual(claim, {
    sub: 'sub_test123', email: 'owner@example.test', email_verified: true,
    aud: EMAIL_ASSERTION_AUDIENCE, iat: NOW, exp: NOW + EMAIL_ASSERTION_TTL,
  });
});

test('변조된 payload·서명은 거부한다', async () => {
  const { email_assertion: assertion } = await issue();
  const parts = assertion.split('.');
  const flipped = parts[1].slice(0, -1) + (parts[1].endsWith('A') ? 'B' : 'A');
  assert.equal(await verifyEmailAssertion({ assertion: `v1.${flipped}.${parts[2]}`, secret: SECRET, now: NOW }), null);
  assert.equal(await verifyEmailAssertion({ assertion: `${parts[0]}.${parts[1]}.${flipped}`, secret: SECRET, now: NOW }), null);
  assert.equal(await verifyEmailAssertion({ assertion, secret: 'another-secret', now: NOW }), null);
});

test('만료와 aud 불일치를 거부한다', async () => {
  const { email_assertion: assertion } = await issue();
  assert.equal(await verifyEmailAssertion({ assertion, secret: SECRET, now: NOW + EMAIL_ASSERTION_TTL }), null);
  assert.equal(await verifyEmailAssertion({ assertion, secret: SECRET, now: NOW, aud: 'other' }), null);
});

test('비밀·다른 client·이메일이 없으면 필드를 넣지 않는다', async () => {
  assert.deepEqual(await issue({ secret: '' }), {});
  assert.deepEqual(await issue({ clientId: 'b62' }), {});
  assert.deepEqual(await issue({ profile: {} }), {});
  assert.deepEqual(await issue({ profile: { email: '' } }), {});
});

test('password 경로의 email_verified=false도 그대로 서명한다', async () => {
  const field = await issue({ profile: { email: 'User@Test.Example', email_verified: false } });
  const claim = await verifyEmailAssertion({ assertion: field.email_assertion, secret: SECRET, now: NOW });
  assert.equal(claim.email, 'user@test.example');
  assert.equal(claim.email_verified, false);
});

test('문서의 시험 벡터가 그대로 검증된다', async () => {
  const vector = 'v1.eyJzdWIiOiJzdWJfZG9jX3ZlY3RvciIsImVtYWlsIjoib3duZXJAZXhhbXBsZS50ZXN0IiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImF1ZCI6ImxvdmV0cmVlIiwiaWF0IjoxNzYwMDAwMDAwLCJleHAiOjE3NjAwMDA2MDB9.Fi7D0cVLibuEzWaK2jAiidMgcZm0cSEsyK1StFM3gf0';
  const claim = await verifyEmailAssertion({
    assertion: vector, secret: 'doc-vector-fake-secret', now: 1_760_000_000,
  });
  assert.deepEqual(claim, {
    sub: 'sub_doc_vector', email: 'owner@example.test', email_verified: true,
    aud: 'lovetree', iat: 1_760_000_000, exp: 1_760_000_600,
  });
});
