import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { hashPassword, verifyPassword, normalizeEmail, validatePassword, CredentialError } from '../src/identity/password.js';
import {
  B64_SESSION_COOKIE_NAME,
  b64SessionCookieValue,
  mintB64SessionToken,
  newB64MemberId,
  newB64SessionId,
  verifyB64SessionToken,
} from '../src/identity/session.js';

/**
 * B64's own credential and session primitives (#987). The password format is
 * the repository's reviewed one, so the cross-language check below is the load
 * bearing proof: a hash produced by the real Python authority must verify here
 * and vice versa.
 */

// The compiled test runs from apps/ai-reward-router/dist/tests, so the
// repository root is four levels up.
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const CHAT_APP = path.join(REPO_ROOT, 'apps', 'padiem-chat');

/**
 * Node's spawn does not resolve the `python3` shell alias on Windows, so both
 * spellings are tried. The first that imports the chat password module wins.
 *
 * PYTHONDONTWRITEBYTECODE keeps the probe from writing __pycache__: `npm test`
 * runs test files as parallel processes, and concurrent bytecode caching of the
 * same module intermittently failed the spawn.
 */
let lastPythonError = 'not attempted';

function runPython(args: readonly string[]): string | null {
  for (const executable of ['python3', 'python']) {
    const probe = spawnSync(executable, args, {
      cwd: CHAT_APP,
      encoding: 'utf8',
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
    });
    if (probe.status === 0) return probe.stdout.trim();
    lastPythonError = probe.error
      ? `${probe.error.message}`
      : `status=${probe.status} stderr=${(probe.stderr ?? '').trim().slice(0, 200)}`;
  }
  return null;
}

function pythonPasswordHash(password: string): string | null {
  return runPython([
    '-c', 'import sys; from app.password_auth import hash_password; print(hash_password(sys.argv[1]))', password,
  ]);
}

function pythonVerifies(password: string, encoded: string): boolean | null {
  const answer = runPython([
    '-c',
    'import sys; from app.password_auth import verify_password; print("YES" if verify_password(sys.argv[1], sys.argv[2]) else "NO")',
    password,
    encoded,
  ]);
  return answer === null ? null : answer === 'YES';
}

// One probe decides whether the cross-language legs can run at all. They are
// reported as skipped when the chat app's environment is absent, never as
// passed.
const PYTHON_AVAILABLE = pythonPasswordHash('probe-probe-123') !== null;

test('a B64 hash is accepted by the reviewed Python verifier', { skip: PYTHON_AVAILABLE ? false : 'python with app.password_auth is unavailable on this host' }, async () => {
  const password = 'correct horse battery staple';
  const tsHash = await hashPassword(password);
  // Standard base64 fields (A-Za-z0-9+/ with = padding), so a digest that
  // happens to contain + or / still matches.
  assert.match(tsHash, /^pbkdf2_sha512\$220000\$[A-Za-z0-9+/]+={0,2}\$[A-Za-z0-9+/]+={0,2}$/);
  assert.equal(pythonVerifies(password, tsHash), true, `the TS KDF output must satisfy the Python verifier (${lastPythonError})`);
  assert.equal(pythonVerifies('wrong password entirely', tsHash), false);
});

test('a Python-produced hash verifies in B64', { skip: PYTHON_AVAILABLE ? false : 'python with app.password_auth is unavailable on this host' }, async () => {
  const password = 'cross-language journey';
  const pyHash = pythonPasswordHash(password)!;
  assert.equal(await verifyPassword(password, pyHash), true,
    'the same stored credential works in both implementations');
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
