import test from 'node:test';
import assert from 'node:assert/strict';

import { PAIRING_SEAM, PairingDeepLinkError, parsePairingDeepLink } from '../src/contract/pairing-deeplink.js';

test('#3083 pairing seam parses a bounded padiem://pair deep link without exposing values', () => {
  const parsed = parsePairingDeepLink('padiem://pair?code=abc123&source=shell');
  assert.equal(parsed.kind, 'pair');
  assert.deepEqual([...parsed.paramNames], ['code', 'source']);
  assert.equal(parsed.valueHandling, 'names-only');
  assert.match(parsed.correlationRef, /^pairref-[0-9a-f]{16}$/);
  // The parser returns no token value at all.
  assert.equal(JSON.stringify(parsed).includes('abc123'), false);
});

test('#3083 pairing seam is deterministic for the same canonical shape', () => {
  const a = parsePairingDeepLink('padiem://pair?code=1&source=shell');
  const b = parsePairingDeepLink('padiem://pair?source=shell&code=1');
  assert.equal(a.correlationRef, b.correlationRef);
});

test('#3083 pairing seam refuses a foreign scheme, wrong host and empty input', () => {
  const cases: Array<[string, string]> = [
    ['https://pair?code=1', 'SCHEME_MISMATCH'],
    ['padiem:/pair?code=1', 'SCHEME_MISMATCH'],
    ['padiem://pairing?code=1', 'UNKNOWN_KIND'],
    ['padiem://', 'UNKNOWN_KIND'],
    ['', 'EMPTY'],
  ];
  for (const [input, code] of cases) {
    assert.throws(
      () => parsePairingDeepLink(input),
      (error: unknown) => error instanceof PairingDeepLinkError && error.code === code,
      `expected ${code} for ${input}`,
    );
  }
  assert.throws(
    () => parsePairingDeepLink(42),
    (error: unknown) => error instanceof PairingDeepLinkError && error.code === 'NOT_A_STRING',
  );
});

test('#3083 pairing seam is bounded in length, parameter count, value length and charset', () => {
  assert.throws(
    () => parsePairingDeepLink(`padiem://pair?code=${'a'.repeat(PAIRING_SEAM.MAX_URL_LENGTH)}`),
    (error: unknown) => error instanceof PairingDeepLinkError && error.code === 'TOO_LONG',
  );
  const many = Array.from({ length: PAIRING_SEAM.MAX_PARAM_COUNT + 1 }, (_, i) => `p${i}=1`).join('&');
  assert.throws(
    () => parsePairingDeepLink(`padiem://pair?${many}`),
    (error: unknown) => error instanceof PairingDeepLinkError && error.code === 'TOO_MANY_PARAMS',
  );
  const longValue = 'x'.repeat(PAIRING_SEAM.MAX_PARAM_VALUE_LENGTH + 1);
  assert.throws(
    () => parsePairingDeepLink(`padiem://pair?code=${longValue}`),
    (error: unknown) =>
      error instanceof PairingDeepLinkError && error.code === 'PARAM_VALUE_TOO_LONG',
  );
  assert.throws(
    () => parsePairingDeepLink('padiem://pair?CODE VALUE=1'),
    (error: unknown) => error instanceof PairingDeepLinkError && error.code === 'BAD_PARAM_NAME',
  );
  assert.throws(
    () => parsePairingDeepLink('padiem://pair?code=bad'),
    (error: unknown) =>
      error instanceof PairingDeepLinkError && error.code === 'CONTROL_CHARACTER',
  );
});

test('#3083 pairing seam implements no authority: no minting, no storage, no broker', () => {
  assert.equal(PAIRING_SEAM.PAIRING_AUTHORITY_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.SESSION_MINT_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.CREDENTIAL_PERSISTENCE, false);
  assert.equal(PAIRING_SEAM.BROKER_TRANSPORT_IMPLEMENTED, false);
  assert.equal(PAIRING_SEAM.AUTHORITY_OWNER, '#3080');
});
