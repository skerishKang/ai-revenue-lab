import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PASSWORD_KDF_ITERATIONS,
  WORKERS_PBKDF2_MAX_ITERATIONS,
  hashPassword,
  verifyPassword,
  normalizeEmail,
  validatePassword,
  CredentialError,
  PasswordHashingUnavailableError,
} from '../src/identity/password.js';
import {
  B64_SESSION_COOKIE_NAME,
  b64SessionCookieValue,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
  verifyB64SessionToken,
} from '../src/identity/session.js';

/**
 * B64's own credential primitives (#987).
 *
 * Issue #5978 is why the platform-ceiling tests below exist: the KDF cost was
 * copied from another product at 220,000 iterations, the hosted Workers runtime
 * caps PBKDF2 at 100,000 and throws before doing any work, and the local
 * runtime does not enforce the cap — so CI was green while every live signup
 * failed.
 */

test('the KDF cost stays inside the ceiling the Workers runtime enforces (#5978)', () => {
  assert.ok(
    PASSWORD_KDF_ITERATIONS <= WORKERS_PBKDF2_MAX_ITERATIONS,
    `PBKDF2 cost ${PASSWORD_KDF_ITERATIONS} exceeds the ${WORKERS_PBKDF2_MAX_ITERATIONS} hosted Workers allows — signup fails live while CI stays green`,
  );
  assert.equal(PASSWORD_KDF_ITERATIONS, WORKERS_PBKDF2_MAX_ITERATIONS,
    'B64 runs at the platform maximum; lowering it further is a security decision, not a default');
});

test('a stored hash above the platform ceiling is refused, never retried at a weaker cost', async () => {
  const foreignCost = 'pbkdf2_sha512$220000$YjY0LWR1bW15LXNhbHQwMQ==$KWtPj698O4tdOcmcUqYAEre8G3O3XSGNDwoYVqcC5k0=';
  await assert.rejects(
    () => verifyPassword('anything at all 123', foreignCost),
    PasswordHashingUnavailableError,
    'an out-of-range cost must surface rather than be quietly re-derived',
  );
});

test('when the runtime refuses PBKDF2 the failure is named, not reported as storage', async () => {
  const original = crypto.subtle.deriveBits.bind(crypto.subtle);
  // Exactly what hosted workerd does above its cap.
  (crypto.subtle as { deriveBits: unknown }).deriveBits = async () => {
    throw new Error('iteration counts above 100000 are not supported');
  };
  try {
    await assert.rejects(() => hashPassword('a real password 12'), PasswordHashingUnavailableError);
    const { createConsumerHttpHandler } = await import('../src/http/consumer-http.js');
    const { InMemoryB64MemberStore } = await import('../src/identity/member-store.js');
    const handler = createConsumerHttpHandler({
      loadCandidates: () => [],
      memberStore: new InMemoryB64MemberStore(),
      sessionSecret: 'test-secret-value-0123456789abcdef',
      expectedBrowserOrigin: 'https://b64.example.test',
    });
    const response = await handler(new Request('https://b64.example.test/join', {
      method: 'POST',
      headers: {
        'content-type': 'application/x-www-form-urlencoded',
        origin: 'https://b64.example.test',
      },
      body: new URLSearchParams({ email: 'kdf-probe@example.test', password: 'a real password 12' }).toString(),
    }));
    assert.equal(response.status, 503);
    assert.equal((await response.json() as { error: string }).error, 'kdf_unsupported',
      '#5978: a refused KDF reported as storage_unavailable sent the investigation to D1');
  } finally {
    (crypto.subtle as { deriveBits: unknown }).deriveBits = original;
  }
});

test('the stored credential shape stays the reviewed one at the platform cost', async () => {
  const hash = await hashPassword('correct horse battery staple');
  assert.equal(
    hash,
    hash.replace(/^pbkdf2_sha512\$\d+\$/, `pbkdf2_sha512$${PASSWORD_KDF_ITERATIONS}$`),
    'the embedded cost is the cost B64 uses',
  );
  assert.match(hash, /^pbkdf2_sha512\$100000\$[A-Za-z0-9+/]+={0,2}\$[A-Za-z0-9+/]+={0,2}$/);
  assert.equal(await verifyPassword('correct horse battery staple', hash), true);
  assert.equal(await verifyPassword('wrong password entirely', hash), false);
});

test('verifyPassword rejects a wrong password and a tampered hash', async () => {
  const stored = await hashPassword('a real passw0rd here');
  assert.equal(await verifyPassword('a real passw0rd here', stored), true);
  assert.equal(await verifyPassword('A real passw0rd here', stored), false);
  const [prefix, cost, salt, digest] = stored.split('$');
  const flipped = `${prefix}$${cost}$${salt}$${digest!.slice(0, -2)}AA`;
  assert.equal(await verifyPassword('a real passw0rd here', flipped), false, 'a changed digest does not verify');
  assert.equal(await verifyPassword('a real passw0rd here', `${prefix}$1000$${salt}$${digest}`), false,
    'a downgraded cost is refused rather than honoured');
});

test('a missing or malformed stored hash still costs one KDF and never verifies', async () => {
  for (const stored of [null, '', 'garbage', 'pbkdf2_sha512$9$x$y']) {
    assert.equal(await verifyPassword('anything at all 123', stored), false, JSON.stringify(stored));
  }
});

test('each hash carries its own salt', async () => {
  const [a, b] = await Promise.all([hashPassword('same password 12'), hashPassword('same password 12')]);
  assert.notEqual(a.split('$')[2], b.split('$')[2], 'two registrations of one password differ in salt');
  assert.notEqual(a, b);
  assert.equal(await verifyPassword('same password 12', a), true);
  assert.equal(await verifyPassword('same password 12', b), true);
});

test('email and password input is validated before any storage call', () => {
  assert.equal(normalizeEmail('  Member@Example.COM '), 'member@example.com');
  for (const bad of ['', 'no-at-sign', 'a@b', 'a b@example.com', 'x@y.z '.repeat(90)]) {
    assert.throws(() => normalizeEmail(bad), CredentialError, JSON.stringify(bad));
  }
  assert.throws(() => normalizeEmail(null), CredentialError);
  assert.throws(() => validatePassword('1234567'), CredentialError);
  assert.throws(() => validatePassword('x'.repeat(129)), CredentialError);
  assert.equal(validatePassword('12345678'), '12345678');
});

test('a B64 session token round-trips and carries only server-owned claims', async () => {
  const memberId = newB64MemberId();
  const sessionId = newB64SessionId();
  const expiresAt = Math.floor(Date.now() / 1000) + 3600;
  const token = await mintB64SessionToken({ sessionSecret: 'secret-value-1234567890', memberId, sessionId, expiresAtSeconds: expiresAt });
  const claims = await verifyB64SessionToken(token, 'secret-value-1234567890');
  assert.deepEqual(claims, { memberId, sessionId, expiresAtSeconds: expiresAt });
});

test('session verification fails closed on every tampering path', async () => {
  const secret = 'secret-value-1234567890';
  const memberId = newB64MemberId();
  const token = await mintB64SessionToken({
    sessionSecret: secret,
    memberId,
    sessionId: newB64SessionId(),
    expiresAtSeconds: Math.floor(Date.now() / 1000) + 3600,
  });
  assert.ok(token);
  assert.equal(await verifyB64SessionToken(token, 'a-different-secret-9999'), null, 'another key does not verify');
  assert.equal(await verifyB64SessionToken(`${token}x`, secret), null, 'a mutated signature does not verify');
  const [body] = token.split('.');
  const swapped = await mintB64SessionToken({
    sessionSecret: secret,
    memberId,
    sessionId: newB64SessionId(),
    expiresAtSeconds: Math.floor(Date.now() / 1000) + 7200,
  });
  const [otherBody] = swapped.split('.');
  assert.equal(await verifyB64SessionToken(`${otherBody}.${token.split('.')[1]}`, secret), null,
    'a signature cannot be moved onto another body');
  assert.equal(await verifyB64SessionToken(body, secret), null, 'a token without a signature is refused');
  assert.equal(await verifyB64SessionToken(null, secret), null);
  assert.equal(await verifyB64SessionToken(token, undefined), null, 'no secret configured means no identity');

  const expired = await mintB64SessionToken({
    sessionSecret: secret,
    memberId,
    sessionId: newB64SessionId(),
    expiresAtSeconds: Math.floor(Date.now() / 1000) - 1,
  });
  assert.equal(await verifyB64SessionToken(expired, secret), null, 'expiry is enforced');
});

test('the session cookie is HttpOnly, Secure, SameSite=Lax and scoped to the path', async () => {
  const value = b64SessionCookieValue('token-value');
  assert.ok(value.startsWith(`${B64_SESSION_COOKIE_NAME}=token-value;`));
  for (const attribute of ['Path=/', 'HttpOnly', 'SameSite=Lax', 'Secure', 'Max-Age=']) {
    assert.ok(value.includes(attribute), value);
  }
});
