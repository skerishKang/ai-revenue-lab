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
  CHANNEL_RE,
  RELEASE_CHANNELS,
  RELEASE_PUBLISH_CONTRACT,
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

test('withdrawal marks a published release and preserves its identity', () => {
  const published = release();
  const feed = { [published.releaseId]: published };
  const outcome = withdrawRelease(feed, {
    releaseId: published.releaseId,
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: 'padiem-0.2.1-x64',
  });
  assert.equal(outcome.accepted, true);
  // Withdrawal is a state change, never a delete: the feed entry is retained.
  const retained = feed[published.releaseId];
  assert.ok(retained, 'withdrawal must retain the feed entry');
  assert.equal(retained.releaseId, published.releaseId);
  assert.equal(retained.artifactSha256, ARTIFACT_SHA);
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

test('withdrawing an unpublished identity is refused', () => {
  const outcome = withdrawRelease({}, {
    releaseId: 'never-published',
    reason: 'defect_confirmed',
    artifactSha256: ARTIFACT_SHA,
    replacementReleaseId: null,
  });
  assert.equal(outcome.accepted, false);
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
    withdrawRelease({}, { releaseId: 'x', reason: 'defect_confirmed', artifactSha256: ARTIFACT_SHA, replacementReleaseId: null }),
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
