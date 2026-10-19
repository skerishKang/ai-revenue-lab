import test from 'node:test';
import assert from 'node:assert/strict';

import {
  REDACTION_PLACEHOLDER,
  SAFE_LOG_PROJECTION,
  projectBoundedLog,
  redactEvidenceLine,
  redactLine,
} from '../src/contract/safe-log-projection.js';

/**
 * Credential-shaped fixtures are assembled from fragments on purpose.
 *
 * A literal `Bearer <token>` or `ghp_...` string in a test file is
 * indistinguishable from a leaked secret to a repository secret scanner, and
 * these values are only ever used as redaction inputs. Assembling them keeps the
 * assertion honest and the repository clean.
 */
const BEARER_VALUE = ['abcdefghij', 'klmnop', 'qrstuvwxyz012345'].join('.');
const GITHUB_VALUE = ['ghp', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123'].join('_');
const SLACK_VALUE = ['xoxb', '1234567890', 'abcdefghijkl'].join('-');
const PADIEM_VALUE = ['padi', 'live', 'abcdefgh12345678'].join('_');
const AWS_VALUE = ['AK', 'IA', 'IOSF', 'ODNN7', 'EXAMPLE'].join('');

test('#3083 safe log projection redacts common credential shapes', () => {
  const samples = [
    `padiem key ${PADIEM_VALUE}`,
    `Authorization: Bearer ${BEARER_VALUE}`,
    `github token ${GITHUB_VALUE}`,
    `slack token ${SLACK_VALUE}`,
    `jwt ${['eyJhbGciOiJIUzI1NiIs', 'eyJzdWIiOiIxMjM0NTY3ODkwIn0', 'dozjgNryP4J3jVmNHl0w5N'].join('.')}`,
    `aws ${AWS_VALUE}`,
  ];
  for (const sample of samples) {
    const redacted = redactLine(sample);
    assert.equal(
      redacted.includes(REDACTION_PLACEHOLDER),
      true,
      `expected redaction marker for: ${sample}`,
    );
  }
  assert.equal(redactLine(`aws ${AWS_VALUE}`).includes(AWS_VALUE), false);
  assert.equal(redactLine(`github token ${GITHUB_VALUE}`).includes(GITHUB_VALUE), false);
});

test('#3472 persisted evidence adds pairing-code masking on top of common redaction', () => {
  const pairingCode = ['0123456789abcdef', 'fedcba9876543210'].join('');
  const pairingLine = `pairing material ${pairingCode}`;
  const bearerLine = `Authorization: Bearer ${BEARER_VALUE}`;

  const projectedPairing = redactEvidenceLine(pairingLine);
  const projectedBearer = redactEvidenceLine(bearerLine);

  assert.equal(projectedPairing.includes(pairingCode), false);
  assert.equal(projectedPairing.includes(REDACTION_PLACEHOLDER), true);
  assert.equal(projectedBearer.includes(BEARER_VALUE), false);
  assert.equal(projectedBearer.includes(REDACTION_PLACEHOLDER), true);

  // Pairing masking happens before the persistent line bound. A code crossing
  // the truncation edge must not leave even a prefix of the secret behind.
  const boundaryLine = `${'x'.repeat(SAFE_LOG_PROJECTION.MAX_LINE_LENGTH - 8)}${pairingCode}`;
  const boundaryProjected = redactEvidenceLine(boundaryLine);
  assert.equal(boundaryProjected.includes(pairingCode), false);
  assert.equal(boundaryProjected.includes(pairingCode.slice(0, 8)), false);
  assert.equal(boundaryProjected.length <= SAFE_LOG_PROJECTION.MAX_LINE_LENGTH + 20, true);
});

test('#3083 safe log projection redacts a multi-line private key block', () => {
  const begin = ['-----BEGIN RSA ', 'PRIVATE KEY-----'].join('');
  const body = ['MIIE', 'owIB', 'AAKCAQEA'].join('');
  const end = ['-----END RSA ', 'PRIVATE KEY-----'].join('');
  const block = [begin, body, end].join('\n');
  const projected = projectBoundedLog([block]);
  assert.equal(projected.lines.join('\n').includes(body), false);
});

test('#3083 safe log projection returns only the bounded tail', () => {
  const lines = Array.from({ length: 500 }, (_, i) => `line-${i}`);
  const projected = projectBoundedLog(lines, 10);
  assert.equal(projected.lines.length, 10);
  assert.equal(projected.truncated, true);
  assert.equal(projected.lines[9], 'line-499');
  assert.equal(projectBoundedLog(lines).lines.length, SAFE_LOG_PROJECTION.DEFAULT_LINES);
  assert.equal(projectBoundedLog(lines, 10_000).lines.length, SAFE_LOG_PROJECTION.MAX_LINES);
});

test('#3083 safe log projection bounds a single very long line', () => {
  const projected = projectBoundedLog(['y'.repeat(5000)]);
  assert.equal(projected.lines.length, 1);
  assert.equal(projected.lines[0]!.length <= SAFE_LOG_PROJECTION.MAX_LINE_LENGTH + 20, true);
  assert.equal(projected.lines[0]!.endsWith('[TRUNCATED]'), true);
});

test('#3083 safe log projection fails closed on an invalid bound', () => {
  for (const bad of [0, -1, 1.5, Number.NaN]) {
    assert.throws(() => projectBoundedLog(['a'], bad), /maxLines must be a positive integer/);
  }
});

test('#3083 safe log projection never exposes raw logs and always records redaction', () => {
  assert.equal(SAFE_LOG_PROJECTION.RAW_LOG_TO_RENDERER, false);
  assert.equal(SAFE_LOG_PROJECTION.ARBITRARY_PATH_READ, false);
  assert.equal(SAFE_LOG_PROJECTION.REDACTION_APPLIED, true);
  assert.equal(projectBoundedLog(['anything']).redactionApplied, true);
});
