export const STATE_RPC_TOLERANCE_SECONDS = 300;
export const STATE_RPC_MAX_BODY_BYTES = 64 * 1024;

const encoder = new TextEncoder();
const noncePattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const proofPattern = /^v1=[0-9a-f]{64}$/;

function validSecret(secret) {
  return typeof secret === 'string' && encoder.encode(secret).length >= 32;
}

function canonicalBytes({ method, path, at, nonce, body }) {
  const prefix = encoder.encode(`v1\n${method}\n${path}\n${at}\n${nonce}\n`);
  const bytes = body instanceof Uint8Array ? body : encoder.encode(body);
  const canonical = new Uint8Array(prefix.length + bytes.length);
  canonical.set(prefix);
  canonical.set(bytes, prefix.length);
  return canonical;
}

async function proofFor(secret, input) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const signature = new Uint8Array(await crypto.subtle.sign('HMAC', key, input));
  return 'v1=' + [...signature].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

function constantTimeEqual(left, right) {
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index++) mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return mismatch === 0;
}

export async function signStateRpc({ secret, method = 'POST', path, at, nonce, body }) {
  const atText = String(at);
  if (!validSecret(secret) || method !== 'POST' || typeof path !== 'string' || !path.startsWith('/rpc/') ||
      !/^(0|[1-9][0-9]{0,10})$/.test(atText) || !noncePattern.test(nonce ?? '')) {
    throw new Error('invalid_state_rpc_request');
  }
  const bytes = body instanceof Uint8Array ? body : encoder.encode(body);
  if (!bytes.length || bytes.length > STATE_RPC_MAX_BODY_BYTES) throw new Error('invalid_state_rpc_body');
  const proof = await proofFor(secret, canonicalBytes({ method, path, at: atText, nonce, body: bytes }));
  return {
    'content-type': 'application/json',
    'x-padiem-auth-at': atText,
    'x-padiem-auth-nonce': nonce,
    'x-padiem-auth-proof': proof,
  };
}

export async function verifyStateRpc({ secret, method = 'POST', path, at, nonce, proof, body, now, tolerance = STATE_RPC_TOLERANCE_SECONDS }) {
  const atText = String(at ?? '');
  const bytes = body instanceof Uint8Array ? body : encoder.encode(body ?? '');
  if (!validSecret(secret) || method !== 'POST' || typeof path !== 'string' || !path.startsWith('/rpc/') ||
      !/^(0|[1-9][0-9]{0,10})$/.test(atText) || !noncePattern.test(nonce ?? '') ||
      !proofPattern.test(proof ?? '') || !bytes.length || bytes.length > STATE_RPC_MAX_BODY_BYTES ||
      !Number.isSafeInteger(now) || !Number.isSafeInteger(tolerance) || tolerance < 0) return null;
  const seconds = Number(atText);
  if (!Number.isSafeInteger(seconds) || Math.abs(now - seconds) > tolerance) return null;
  const expected = await proofFor(secret, canonicalBytes({ method, path, at: atText, nonce, body: bytes }));
  return constantTimeEqual(proof, expected) ? { at: seconds, nonce } : null;
}
