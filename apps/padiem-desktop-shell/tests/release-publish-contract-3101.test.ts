/**
 * CLAW3 #3101 M3/G3 — release publish, immutability and withdrawal tests.
 *
 * These drive the real `admitPublish` / `verifyReleaseForInstall` /
 * `withdrawRelease` functions.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  ALLOWED_RELEASE_REJECTIONS,
  ALLOWED_WITHDRAWAL_REJECTIONS,
  CHANNEL_RE,
  RELEASE_CHANNELS,
  RELEASE_PUBLISH_CONTRACT,
  WITHDRAWAL_REASONS,
  admitPublish,
  verifyReleaseForInstall,
  withdrawRelease,
  type ReleaseArtifact,
  type ReleaseToolchain,
} from '../src/contract/release-publish-contract.js';

const TOOLCHAIN: ReleaseToolchain = Object.freeze({
  electronBuilder: '26.16.1',
  winCodeSignToolset: '0.0.0',
  nsisToolset: '0.0.0',
});

const SOURCE_SHA = 'a'.repeat(40);
const OTHER_SOURCE_SHA = 'b'.repeat(40);
const ARTIFACT_SHA = 'c'.repeat(64);
const OTHER_ARTIFACT_SHA = 'd'.repeat(64);

function release(overrides: Partial<ReleaseArtifact> = {}): ReleaseArtifact {
  return {
    releaseId: 'padiem-0.2.0-x64',
    channel: 'internal',
    appVersion: '0.2.0',
    artifactSha256: ARTIFACT_SHA,
    sourceSha: SOURCE_SHA,
    toolchain: TOOLCHAIN,
    ...overrides,
  } as ReleaseArtifact;
}

test('a fully provenanced release is admitted', () => {
  const outcome = admitPublish({ release: release(), existing: {} });
  assert.equal(outcome.accepted, true);
  if (outcome.accepted) assert.equal(outcome.releaseId, 'padiem-0.2.0-x64');
});

test('publish is additive only — republishing the same identity is refused', () => {
  const first = release();
  const outcome = admitPublish({ release: first, existing: { [first.releaseId]: first } });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_IDENTITY_ALREADY_PUBLISHED');
    assert.match(outcome.detail, /additive only/);
  }
});

test('a different artifact cannot silently overwrite a published identity', () => {
  const published = release();
  const outcome = admitPublish({
    release: release({ artifactSha256: OTHER_ARTIFACT_SHA }),
    existing: { [published.releaseId]: published },
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_IDENTITY_ALREADY_PUBLISHED');
    assert.match(outcome.detail, /silent overwrite refused/);
  }
});

test('an abbreviated source SHA is refused — provenance must be exact', () => {
  const outcome = admitPublish({ release: release({ sourceSha: 'abc1234' }), existing: {} });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_SOURCE_SHA');
});

test('a branch name is refused as provenance', () => {
  const outcome = admitPublish({ release: release({ sourceSha: 'main' }), existing: {} });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_SOURCE_SHA');
});

test('missing toolchain provenance is refused', () => {
  for (const bad of [null, undefined, {}, { electronBuilder: '26.16.1' }]) {
    const outcome = admitPublish({
      release: release({ toolchain: bad as never }),
      existing: {},
    });
    assert.equal(outcome.accepted, false, JSON.stringify(bad));
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_TOOLCHAIN');
  }
});

test('a malformed artifact digest is refused', () => {
  for (const bad of ['', 'short', 'z'.repeat(64), null]) {
    const outcome = admitPublish({
      release: release({ artifactSha256: bad as never }),
      existing: {},
    });
    assert.equal(outcome.accepted, false, String(bad));
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_ARTIFACT_SHA');
  }
});

test('an unknown channel is refused', () => {
  const outcome = admitPublish({ release: release({ channel: 'nightly' as never }), existing: {} });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_CHANNEL');
});

// CENTRAL #3101 blocker: the channel validator was `/^internal|beta|stable$/`.
// Alternation has the lowest precedence, so that parsed as
// `(^internal)|(beta)|(stable$)` and accepted anything starting with
// "internal", containing "beta", or ending with "stable".
test('a channel with trailing junk is refused', () => {
  for (const bad of ['internal-junk', 'internal ', 'internal\n', 'internalx']) {
    const outcome = admitPublish({ release: release({ channel: bad as never }), existing: {} });
    assert.equal(outcome.accepted, false, bad);
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_CHANNEL', bad);
  }
});

test('a channel with embedded text is refused', () => {
  for (const bad of ['xbetay', 'junk-beta', 'beta-internal', 'a beta b', 'prebeta']) {
    const outcome = admitPublish({ release: release({ channel: bad as never }), existing: {} });
    assert.equal(outcome.accepted, false, bad);
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_CHANNEL', bad);
  }
});

test('a channel with leading junk is refused', () => {
  for (const bad of ['junk-stable', 'xstable', 'stable-junk', ' stable']) {
    const outcome = admitPublish({ release: release({ channel: bad as never }), existing: {} });
    assert.equal(outcome.accepted, false, bad);
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_CHANNEL', bad);
  }
});

test('channel membership is case-sensitive and exact', () => {
  for (const bad of ['INTERNAL', 'Beta', 'STABLE', 'Internal', '']) {
    const outcome = admitPublish({ release: release({ channel: bad as never }), existing: {} });
    assert.equal(outcome.accepted, false, JSON.stringify(bad));
    if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MALFORMED_CHANNEL');
  }
});

test('the three canonical channels are still accepted', () => {
  for (const good of ['internal', 'beta', 'stable']) {
    const outcome = admitPublish({ release: release({ channel: good as never }), existing: {} });
    assert.equal(outcome.accepted, true, good);
  }
});

test('the channel pattern agrees with the RELEASE_CHANNELS vocabulary', () => {
  // The validator is membership against RELEASE_CHANNELS; the exported pattern
  // is an independent cross-check. This asserts they cannot disagree, which is
  // what stops the two channel definitions from drifting apart.
  const corpus = [
    ...RELEASE_CHANNELS,
    'internal-junk',
    'xbetay',
    'junk-stable',
    'beta-internal',
    'INTERNAL',
    '',
    'nightly',
  ];
  for (const value of corpus) {
    assert.equal(
      CHANNEL_RE.test(value),
      (RELEASE_CHANNELS as readonly string[]).includes(value),
      `pattern and vocabulary disagree on ${JSON.stringify(value)}`,
    );
  }
});

test('a release missing appVersion is refused as incomplete provenance', () => {
  const outcome = admitPublish({ release: release({ appVersion: '' }), existing: {} });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MISSING_PROVENANCE');
});

test('install verification accepts a matching release when no signature is required', () => {
  const outcome = verifyReleaseForInstall({
    offered: release(),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(outcome.accepted, true);
});

test('artifact SHA mismatch is rejected', () => {
  const outcome = verifyReleaseForInstall({
    offered: release(),
    observedArtifactSha256: OTHER_ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_ARTIFACT_SHA_MISMATCH');
});

test('source SHA mismatch is rejected', () => {
  const outcome = verifyReleaseForInstall({
    offered: release(),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: OTHER_SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_SOURCE_SHA_MISMATCH');
});

test('a withdrawn release is refused even when bytes and provenance match', () => {
  const outcome = verifyReleaseForInstall({
    offered: release({ withdrawn: true }),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_WITHDRAWN_RELEASE');
});

test('requiring a signature without evidence is rejected', () => {
  const outcome = verifyReleaseForInstall({
    offered: release(),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: true,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MISSING_SIGNING_EVIDENCE');
});

test('incomplete signing evidence is never treated as probably fine', () => {
  const partial = {
    certificateThumbprint: 'ABC123',
    signingIdentity: '',
    signatureSha256: ARTIFACT_SHA,
  };
  const outcome = verifyReleaseForInstall({
    offered: release({ signatureEvidence: partial as never }),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) assert.equal(outcome.rejection, 'REJECT_MISSING_SIGNING_EVIDENCE');
});

test('complete signing evidence satisfies a required signature', () => {
  const outcome = verifyReleaseForInstall({
    offered: release({
      signatureEvidence: {
        certificateThumbprint: 'ABC123',
        signingIdentity: 'padiem-release@project',
        signatureSha256: OTHER_ARTIFACT_SHA,
      },
    }),
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: true,
  });
  assert.equal(outcome.accepted, true);
});

test('withdrawal PRODUCES withdrawn state and preserves identity and bytes', () => {
  // CENTRAL #3101 blocker: the previous implementation returned
  // `{accepted: true}` without producing any withdrawn state, and its test only
  // asserted the feed entry still existed. A success that changes nothing is
  // not a withdrawal.
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: 'padiem-0.2.1-x64',
  });

  assert.equal(outcome.accepted, true);
  if (!outcome.accepted) return;

  // 1. The state is actually produced.
  assert.equal(outcome.withdrawnRelease.withdrawn, true);

  // 2. Identity and bytes are preserved.
  assert.equal(outcome.withdrawnRelease.releaseId, published.releaseId);
  assert.equal(outcome.withdrawnRelease.artifactSha256, ARTIFACT_SHA);
  assert.equal(outcome.withdrawnRelease.sourceSha, published.sourceSha);
  assert.equal(outcome.withdrawnRelease.appVersion, published.appVersion);

  // 3. Withdrawal provenance is recorded.
  assert.equal(outcome.withdrawnRelease.withdrawal?.reason, 'defect_confirmed');
  assert.equal(
    outcome.withdrawnRelease.withdrawal?.replacementReleaseId,
    'padiem-0.2.1-x64',
  );

  // 4. The updated feed carries the withdrawn state, and the input feed is
  //    untouched (the transition is pure).
  const updated = outcome.updatedFeed[published.releaseId];
  assert.ok(updated, 'updated feed must contain the withdrawn release');
  assert.equal(updated.withdrawn, true);
  const original = feed[published.releaseId];
  assert.ok(original, 'input feed entry must still exist');
  assert.equal(original.withdrawn, undefined);
});

test('a WITHDRAWN result is refused by verifyReleaseForInstall', () => {
  // The runbook requires that a withdrawal actually changes install behaviour.
  // Driving the produced state through the verifier is the only way to prove the
  // withdrawal protects anyone.
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'signature_invalid',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(outcome.accepted, true);
  if (!outcome.accepted) return;

  const verdict = verifyReleaseForInstall({
    offered: outcome.withdrawnRelease,
    observedArtifactSha256: ARTIFACT_SHA,
    expectedSourceSha: SOURCE_SHA,
    requireSigned: false,
  });
  assert.equal(verdict.accepted, false);
  if (!verdict.accepted) {
    assert.equal(verdict.rejection, 'REJECT_WITHDRAWN_RELEASE');
  }
});

test('a withdrawal for the wrong artifact digest is rejected', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'defect_confirmed',
    artifactSha256: OTHER_ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_WITHDRAWAL_ARTIFACT_MISMATCH');
  }
});

test('a malformed withdrawal artifact digest is rejected', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  for (const bad of ['', 'not-a-digest', 'z'.repeat(64), null]) {
    const outcome = withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'defect_confirmed',
      artifactSha256: bad as never,
      replacementReleaseId: null,
    });
    assert.equal(outcome.accepted, false, String(bad));
    if (!outcome.accepted) {
      assert.equal(outcome.rejection, 'REJECT_WITHDRAWAL_ARTIFACT_MISMATCH');
    }
  }
});

test('an unknown withdrawal reason is rejected at runtime', () => {
  // The TypeScript union is erased, so a value from JSON or a CLI flag can be
  // anything. Recording `made_up_reason` would produce a withdrawal nobody can
  // audit.
  const published = release();
  const feed = { [published.releaseId]: published };
  for (const bad of ['made_up_reason', 'DEFECT_CONFIRMED', '', 'defect confirmed']) {
    const outcome = withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: bad,
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: null,
    });
    assert.equal(outcome.accepted, false, bad);
    if (!outcome.accepted) {
      assert.equal(outcome.rejection, 'REJECT_MALFORMED_WITHDRAWAL_REASON');
    }
  }
});

test('every canonical withdrawal reason is accepted', () => {
  const published = release();
  for (const reason of WITHDRAWAL_REASONS) {
    const feed = { [published.releaseId]: published };
    const outcome = withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason,
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: null,
    });
    assert.equal(outcome.accepted, true, reason);
  }
});

test('a malformed replacement reference is rejected', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  for (const bad of ['!!bad id!!', '', 'x'.repeat(200), 42]) {
    const outcome = withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'defect_confirmed',
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: bad as never,
    });
    assert.equal(outcome.accepted, false, String(bad));
    if (!outcome.accepted) {
      assert.equal(outcome.rejection, 'REJECT_MALFORMED_REPLACEMENT_REF');
    }
  }
});

test('a release cannot be its own replacement', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'superseded_by_emergency_release',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: published.releaseId,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_REPLACEMENT_IS_SELF');
  }
});

test('a null replacement is accepted and recorded as null', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'provenance_unverifiable',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(outcome.accepted, true);
  if (outcome.accepted) {
    assert.equal(outcome.withdrawnRelease.withdrawal?.replacementReleaseId, null);
  }
});

test('withdrawing an unpublished identity is rejected', () => {
  const outcome = withdrawRelease({}, {
    releaseId: 'never-published',
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_WITHDRAWAL_NOT_PUBLISHED');
  }
});

test('withdrawing an already-withdrawn release is refused, not repeated', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const first = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(first.accepted, true);
  if (!first.accepted) return;

  const second = withdrawRelease(first.updatedFeed, {
    releaseId: published.releaseId,
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(second.accepted, false);
  if (!second.accepted) {
    assert.equal(second.rejection, 'REJECT_WITHDRAWAL_ALREADY_WITHDRAWN');
  }
});

test('a non-object withdrawal is rejected', () => {
  for (const bad of [null, undefined, 'withdraw', 7]) {
    const outcome = withdrawRelease({}, bad as never);
    assert.equal(outcome.accepted, false, String(bad));
    if (!outcome.accepted) {
      assert.equal(outcome.rejection, 'REJECT_MISSING_PROVENANCE');
    }
  }
});

test('every withdrawal rejection is inside the closed contract set', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcomes = [
    withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'made_up',
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: null,
    }),
    withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'defect_confirmed',
      artifactSha256: OTHER_ARTIFACT_SHA,
      replacementReleaseId: null,
    }),
    withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'defect_confirmed',
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: '!!bad!!',
    }),
    withdrawRelease(feed, {
      releaseId: published.releaseId,
      reason: 'defect_confirmed',
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: published.releaseId,
    }),
    withdrawRelease({}, {
      releaseId: 'nope',
      reason: 'defect_confirmed',
      artifactSha256: ARTIFACT_SHA,
      replacementReleaseId: null,
    }),
    withdrawRelease(feed, null as never),
  ];
  for (const outcome of outcomes) {
    if (outcome.accepted === false && outcome.rejection !== undefined) {
      assert.ok(
        ALLOWED_WITHDRAWAL_REJECTIONS.includes(outcome.rejection),
        `withdrawal rejection leaked outside the contract: ${outcome.rejection}`,
      );
    }
  }
});

test('a withdrawn identity can never be re-published, even with identical bytes', () => {
  const published = release({ withdrawn: true });
  const outcome = admitPublish({ release: published, existing: { [published.releaseId]: published } });
  assert.equal(outcome.accepted, false);
  if (!outcome.accepted) {
    assert.equal(outcome.rejection, 'REJECT_IDENTITY_ALREADY_PUBLISHED');
    assert.match(outcome.detail, /withdrawn/);
  }
});

test('every rejection is inside the closed contract set', () => {
  const outcomes = [
    admitPublish({ release: release(), existing: {} }),
    admitPublish({ release: release(), existing: { 'padiem-0.2.0-x64': release() } }),
    admitPublish({ release: release({ sourceSha: 'x' }), existing: {} }),
    admitPublish({ release: null as never, existing: {} }),
    verifyReleaseForInstall({
      offered: release(),
      observedArtifactSha256: 'nope',
      expectedSourceSha: SOURCE_SHA,
      requireSigned: false,
    }),
  ];
  for (const outcome of outcomes) {
    if (outcome.accepted === false && outcome.rejection !== undefined) {
      assert.ok(
        ALLOWED_RELEASE_REJECTIONS.includes(outcome.rejection),
        `rejection leaked outside the contract: ${outcome.rejection}`,
      );
    }
  }
});

test('the publish contract declares no live signing and no publish', () => {
  assert.equal(RELEASE_PUBLISH_CONTRACT.SILENT_ARTIFACT_OVERWRITE, false);
  assert.equal(RELEASE_PUBLISH_CONTRACT.PUBLISH_IS_APPEND_ONLY, true);
  assert.equal(RELEASE_PUBLISH_CONTRACT.REQUIRES_EXACT_SOURCE_SHA, true);
  assert.equal(RELEASE_PUBLISH_CONTRACT.REQUIRES_TOOLCHAIN_PROVENANCE, true);
  assert.equal(RELEASE_PUBLISH_CONTRACT.WITHDRAWN_RELEASE_INSTALLABLE, false);
  assert.equal(RELEASE_PUBLISH_CONTRACT.SIGNED_INSTALLER_PRODUCED, false);
  assert.equal(RELEASE_PUBLISH_CONTRACT.AZURE_ARTIFACT_SIGNING_LIVE, false);
  assert.equal(RELEASE_PUBLISH_CONTRACT.PRODUCTION_PUBLISH, false);
});
