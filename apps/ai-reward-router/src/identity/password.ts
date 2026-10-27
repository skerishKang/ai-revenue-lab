/**
 * B64 product-local password credentials (issue #987, owner boundary decision
 * 2026-10-27: B64 members are not PADIEM Chat accounts).
 *
 * This is a port of the repository's already-proven password contract, not a
 * new design: `apps/padiem-chat/app/password_auth.py` stores
 * `pbkdf2_sha512$<iterations>$<base64 salt>$<base64 derived>` with
 * PBKDF2-HMAC-SHA512, 220000 iterations, a 16-byte salt and a 32-byte derived
 * key. Keeping the same format means one reviewed KDF and one reviewed stored
 * credential shape across the products, and it lets a credential be re-read by
 * either implementation if the businesses ever share an account store.
 *
 * What is deliberately NOT reused is any PADIEM secret, table or session: this
 * module never talks to another product, and B64's own signing key stays
 * product-local.
 */

const PBKDF2_ITERATIONS = 220_000;
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
 * path applies.
 */
const DUMMY_HASH =
  'pbkdf2_sha512$220000$cGFkaWVtLWR1bW15LXNhbHQtMDE=$RsPCZ1wcH0+GxN9zW+zqsNlwPiylbJdzVeHjLxWd7Yw=';

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
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, [
    'deriveBits',
  ]);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: salt as unknown as ArrayBuffer, iterations, hash: 'SHA-512' },
    key,
    PBKDF2_DKLEN_BYTES * 8,
  );
  return new Uint8Array(bits);
}

export async function hashPassword(password: string): Promise<string> {
  validatePassword(password);
  const salt = crypto.getRandomValues(new Uint8Array(PBKDF2_SALT_BYTES));
  const derived = await derive(password, salt, PBKDF2_ITERATIONS);
  return `${PASSWORD_HASH_PREFIX}$${PBKDF2_ITERATIONS}$${toBase64(salt)}$${toBase64(derived)}`;
}

function timingSafeEqualBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let index = 0; index < left.length; index += 1) diff |= left[index]! ^ right[index]!;
  return diff === 0;
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
  let iterations = PBKDF2_ITERATIONS;
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
