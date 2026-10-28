/**
 * B64 product-local password credentials (issue #987, owner boundary decision
 * 2026-10-27: B64 members are not PADIEM Chat accounts).
 *
 * The stored shape follows the repository's reviewed convention —
 * `pbkdf2_sha512$<iterations>$<base64 salt>$<base64 derived>` with a 16-byte
 * salt and a 32-byte key — but the ITERATION COUNT is B64's own and is capped
 * by the platform, not chosen freely (issue #5978):
 *
 *   The Cloudflare Workers runtime rejects PBKDF2 iteration counts above
 *   `WORKERS_PBKDF2_MAX_ITERATIONS` before doing any work
 *   (cloudflare/workerd#1346). Node and the local `workerd` dev server do NOT
 *   enforce that ceiling, which is why CI passed while every live signup and
 *   every live sign-in returned 503.
 *
 * Consequence the owner must keep in view: 100,000 SHA-512 rounds is below the
 * current OWASP PBKDF2-SHA-512 guidance (~210,000). It is the maximum this
 * runtime allows, not a relaxed target. Raising B64's real strength means
 * adopting a memory-hard KDF (argon2id/scrypt via WASM) — no iteration count
 * inside PBKDF2 will reach the guidance here. There are no live members yet, so
 * that swap has no legacy hashes to migrate.
 */

import { timingSafeEqualBytes } from './hmac.js';

/** The ceiling the hosted Workers runtime enforces on one PBKDF2 call. */
export const WORKERS_PBKDF2_MAX_ITERATIONS = 100_000;

/** The cost B64 actually uses. Exported so CI can assert it against the ceiling. */
export const PASSWORD_KDF_ITERATIONS = WORKERS_PBKDF2_MAX_ITERATIONS;
const PBKDF2_SALT_BYTES = 16;
const PBKDF2_DKLEN_BYTES = 32;
const PASSWORD_HASH_PREFIX = 'pbkdf2_sha512';

export const PASSWORD_MIN_CHARS = 8;
export const PASSWORD_MAX_CHARS = 128;
export const EMAIL_MAX_CHARS = 320;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * A fixed, non-secret verifier so a sign-in for an address that is not
 * registered still costs one full KDF. Without it, response time tells an
 * attacker which addresses exist — the same equalization the reviewed Python
 * path applies. Its cost matches `PASSWORD_KDF_ITERATIONS`, because a higher-cost
 * dummy would throw on the platform instead of equalizing.
 */
const DUMMY_HASH =
  'pbkdf2_sha512$100000$YjY0LWR1bW15LXNhbHQwMQ==$HAC39CpyVD0BkNqW0FWrneIvr6psCXKoWgTyMIge4nQ=';

/**
 * The credential machinery itself is unavailable — the runtime refused the KDF.
 * Distinct from a storage failure on purpose: #5978 hid a rejected iteration
 * count behind `storage_unavailable`, which sent the investigation to D1 while
 * no D1 statement had run yet.
 */
export class PasswordHashingUnavailableError extends Error {
  readonly code = 'kdf_unsupported';

  constructor(message: string) {
    super(message);
    this.name = 'PasswordHashingUnavailableError';
  }
}

export class CredentialError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'CredentialError';
    this.code = code;
  }
}

export function normalizeEmail(value: unknown): string {
  if (typeof value !== 'string') {
    throw new CredentialError('invalid_email', '이메일 형식이 올바르지 않습니다.');
  }
  const email = value.trim().toLowerCase();
  if (email.length === 0 || email.length > EMAIL_MAX_CHARS || !EMAIL_RE.test(email)) {
    throw new CredentialError('invalid_email', '이메일 형식이 올바르지 않습니다.');
  }
  return email;
}

export function validatePassword(value: unknown): string {
  if (typeof value !== 'string') {
    throw new CredentialError('invalid_password', '비밀번호는 8자 이상이어야 합니다.');
  }
  if (value.length < PASSWORD_MIN_CHARS || value.length > PASSWORD_MAX_CHARS) {
    throw new CredentialError('invalid_password', '비밀번호는 8자 이상 128자 이하입니다.');
  }
  return value;
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(text: string): Uint8Array {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(text) || text.length % 4 === 1) {
    throw new CredentialError('invalid_password_hash', '저장된 비밀번호 형식이 올바르지 않습니다.');
  }
  const decoded = atob(text);
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) {
    bytes[index] = decoded.charCodeAt(index);
  }
  return bytes;
}

async function derive(password: string, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  // Checked here so an out-of-range cost is named as what it is. The hosted
  // runtime refuses above its ceiling before doing any work, so a stored hash
  // with a foreign cost must never be retried hoping the platform allows it.
  if (iterations > WORKERS_PBKDF2_MAX_ITERATIONS) {
    throw new PasswordHashingUnavailableError(
      `PBKDF2 cost ${iterations} exceeds the ${WORKERS_PBKDF2_MAX_ITERATIONS} the Workers runtime allows`,
    );
  }
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  let bits: ArrayBuffer;
  try {
    bits = await crypto.subtle.deriveBits(
      { name: 'PBKDF2', salt: salt as unknown as ArrayBuffer, iterations, hash: 'SHA-512' },
      key,
      PBKDF2_DKLEN_BYTES * 8,
    );
  } catch (error) {
    // The runtime said no. Report it as credential machinery being
    // unavailable — never as storage, and never by retrying at a weaker cost.
    throw new PasswordHashingUnavailableError(
      `PBKDF2 derive failed at cost ${iterations}: ${error instanceof Error ? error.message : 'unknown'}`,
    );
  }
  return new Uint8Array(bits);
}

export async function hashPassword(password: string): Promise<string> {
  validatePassword(password);
  const salt = crypto.getRandomValues(new Uint8Array(PBKDF2_SALT_BYTES));
  const derived = await derive(password, salt, PASSWORD_KDF_ITERATIONS);
  return `${PASSWORD_HASH_PREFIX}$${PASSWORD_KDF_ITERATIONS}$${toBase64(salt)}$${toBase64(derived)}`;
}

/**
 * Verifies a candidate password against a stored hash. A missing or malformed
 * stored value still runs one bounded KDF against the fixed dummy verifier, so
 * the answer never arrives cheaper for an unregistered address.
 */
export async function verifyPassword(password: string, encoded: string | null): Promise<boolean> {
  const candidate = typeof encoded === 'string' && encoded.length > 0 ? encoded : DUMMY_HASH;
  let salt: Uint8Array;
  let expected: Uint8Array;
  let iterations = PASSWORD_KDF_ITERATIONS;
  let shapeAccepted = true;
  try {
    const [prefix, iterationsRaw, saltRaw, digestRaw] = candidate.split('$', 4);
    if (prefix !== PASSWORD_HASH_PREFIX) throw new Error('unsupported prefix');
    const parsedIterations = Number(iterationsRaw);
    if (!Number.isInteger(parsedIterations) || parsedIterations <= 0) throw new Error('bad cost');
    salt = fromBase64(saltRaw ?? '');
    expected = fromBase64(digestRaw ?? '');
    if (salt.length !== PBKDF2_SALT_BYTES || expected.length !== PBKDF2_DKLEN_BYTES) {
      throw new Error('bad length');
    }
    iterations = parsedIterations;
  } catch {
    salt = fromBase64(DUMMY_HASH.split('$', 4)[2]!);
    expected = fromBase64(DUMMY_HASH.split('$', 4)[3]!);
    shapeAccepted = false;
  }

  const derived = await derive(password, salt, iterations);
  return shapeAccepted && timingSafeEqualBytes(derived, expected);
}
