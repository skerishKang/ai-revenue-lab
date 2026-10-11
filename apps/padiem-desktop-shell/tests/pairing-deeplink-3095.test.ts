import test from 'node:test';
import assert from 'node:assert/strict';

import {
  PAIRING_SEAM,
  PairingDeepLinkError,
  parsePairingDeepLink,
  takePairingCodeTransfer,
} from '../src/contract/pairing-deeplink.js';

/** A code with the exact #3080 shape: 32 lowercase hex characters. */
const CODE = '0123456789abcdef0123456789abcdef';

test('#3095 transfers exactly one allowlisted pairing code across the seam', () => {
  const parsed = parsePairingDeepLink(`padiem://pair?code=${CODE}&source=shell`);
  assert.equal(parsed.pairingCodeTransferBounded, true);
  assert.equal(parsed.pairingCodeTransfer, CODE);
  // Everything else keeps the #3083 names-only behaviour.
  assert.equal(parsed.valueHandling, 'names-only');
  assert.deepEqual([...parsed.paramNames], ['code', 'source']);
});

test('#3095 transfer field is null when the deep link carries no code', () => {
  const parsed = parsePairingDeepLink('padiem://pair?source=shell');
  assert.equal(parsed.pairingCodeTransfer, null);
  assert.equal(takePairingCodeTransfer(parsed), null);
});

test('#3095 never transfers an out-of-shape code, and never fails the parse for one', () => {
  // A malformed code must not break the seam: it yields no transfer, and the
  // canonical #3080 redemption client remains the thing that refuses it.
  const wrongLength = 'abc123';
  const wrongCase = CODE.toUpperCase();
  const wrongCharset = `${CODE.slice(0, 31)}g`;
  for (const bad of [wrongLength, wrongCase, wrongCharset]) {
    const parsed = parsePairingDeepLink(`padiem://pair?code=${bad}`);
    assert.equal(parsed.pairingCodeTransfer, null, `expected no transfer for ${bad}`);
    // The param name is still observed; only the value is withheld.
    assert.deepEqual([...parsed.paramNames], ['code']);
    assert.equal(JSON.stringify(parsed).includes(bad), false);
  }
});

test('#3095 refuses a repeated pairing code parameter', () => {
  assert.throws(
    () => parsePairingDeepLink(`padiem://pair?code=${CODE}&code=${CODE}`),
    (error: unknown) =>
      error instanceof PairingDeepLinkError && error.code === 'PAIRING_CODE_REPEATED',
  );
});

test('#3095 does not generalise the transfer to any other parameter name', () => {
  for (const name of ['pairing_code', 'token', 'secret', 'CODE2', 'code2']) {
    const parsed = parsePairingDeepLink(`padiem://pair?${name}=${CODE}`);
    assert.equal(
      parsed.pairingCodeTransfer,
      null,
      `${name} must not become a transfer field`,
    );
  }
  // The allowlist is exactly one name, and it is matched case-insensitively.
  assert.equal(PAIRING_SEAM.PAIRING_CODE_PARAM, 'code');
  assert.equal(
    parsePairingDeepLink(`padiem://pair?CODE=${CODE}`).pairingCodeTransfer,
    CODE,
  );
});

test('#3095 keeps the correlation reference independent of the code value', () => {
  const a = parsePairingDeepLink(`padiem://pair?code=${CODE}&source=shell`);
  const b = parsePairingDeepLink('padiem://pair?code=abc123&source=shell');
  // Same canonical shape -> same reference, so correlation cannot leak the code.
  assert.equal(a.correlationRef, b.correlationRef);
  assert.equal(a.correlationRef.includes(CODE), false);
});

test('#3095 seam still implements no authority of its own', () => {
  assert.equal(PAIRING_SEAM.PAIRING_AUTHORITY_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.SESSION_MINT_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.CREDENTIAL_PERSISTENCE, false);
  assert.equal(PAIRING_SEAM.BROKER_TRANSPORT_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.AUTHORITY_OWNER, '#3080');
  // The transfer is a single-use handoff, not application state.
  assert.equal(PAIRING_SEAM.PAIRING_CODE_TRANSFER_BOUNDED, true);
  assert.equal(PAIRING_SEAM.PAIRING_CODE_GENERAL_PERSISTENCE, false);
  assert.equal(PAIRING_SEAM.PAIRING_CODE_LOGGED, false);
  assert.equal(PAIRING_SEAM.PAIRING_CODE_RENDERER_DIAGNOSTIC, false);
  assert.equal(PAIRING_SEAM.PAIRING_CODE_HEX_CHARS, 32);
});
