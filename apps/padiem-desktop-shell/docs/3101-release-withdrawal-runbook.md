# CLAW3 #3101 M3/G3 — bad-release withdrawal and rollback runbook

```text
SCOPE=source-contract-and-procedure
LIVE_PUBLISH=NO
LIVE_SIGNING=NO
PRODUCTION_MUTATION=NO
```

This runbook describes the procedure the release contract in
`src/contract/release-publish-contract.ts` implements. It is written so a human
operator can follow it, and so the fail-closed behaviour is reviewable without
reading the TypeScript.

## 0. What this runbook is not

It does not authorise a publish. Publishing remains a separately approved gate
(`PRODUCTION_PUBLISH=SEPARATE_APPROVED_GATE`). Nothing here has been executed
against a real feed, a real Azure tenant, or Production.

## 1. Release identity model

A published release is identified by `releaseId` and is immutable.

```text
releaseId  +  artifactSha256  +  sourceSha  +  toolchain  ->  one immutable fact
```

Two rules follow, and both are enforced by `admitPublish`:

1. **Publish is additive only.** A `releaseId` that already exists in the feed
   is refused, whether the offered bytes are identical or different. Republishing
   is not an update operation.
2. **A version number is not an identity.** Publishing different bytes under an
   existing `releaseId` is refused as a silent-overwrite attempt, even when the
   `appVersion` string is unchanged.

## 2. Withdrawal decision tree

Use this when a release is suspected bad. Work top-down; the first match wins.

```text
Is the artifact digest wrong for its identity?
  -> REJECT_ARTIFACT_SHA_MISMATCH : do not withdraw, fix the download/transport
                                    first; the feed may be fine

Was it built from the wrong source revision?
  -> REJECT_SOURCE_SHA_MISMATCH   : do not withdraw; the consumer's expected
                                    source SHA is the thing to reconcile

Is the signature missing/incomplete when one is required?
  -> REJECT_MISSING_SIGNING_EVIDENCE : withdraw (reason: signature_invalid)

Did the signing identity not match, or was the certificate revoked?
  -> withdraw immediately, reason: signature_invalid

Is provenance unprovable (bad source SHA, missing toolchain, unresolvable)?
  -> withdraw, reason: provenance_unverifiable

Is the defect confirmed in the shipped bytes?
  -> withdraw, reason: defect_confirmed

Is a corrected build superseding it?
  -> withdraw, reason: superseded_by_emergency_release, and set
     replacementReleaseId to the NEW release's id
```

Key distinction: a **verification mismatch** on the consumer side is not
automatically a reason to withdraw. `verifyReleaseForInstall` refuses the install
locally either way, so the operator is protected immediately. Withdrawal is for
when the *published* artifact itself is bad and other machines must be protected
too.

## 3. Withdrawal procedure

`withdrawRelease()` is a **pure** transition: it never mutates the feed you pass
in. It returns the withdrawn artifact and an updated feed, and the success path
is only reachable together with that state. A caller that discards the return
value has not withdrawn anything — which is visible rather than silent.

```text
1. Identify the exact releaseId and its artifactSha256.
2. Record the reason from the decision tree above.
3. Call withdrawRelease(feed, withdrawal). Every input is validated BEFORE any
   state is produced; any mismatch is a refusal and nothing changes:
     - the release must already be published
     - it must not already be withdrawn
     - artifactSha256 must equal the published digest
     - reason must be a canonical runtime value
     - replacementReleaseId, if present, must be well formed and not self
4. Persist outcome.updatedFeed (or outcome.withdrawnRelease).
   - Withdrawal PRESERVES the identity and the bytes.
   - Never delete the entry: the audit trail is the point.
   - The withdrawal reason is recorded on the artifact itself
     (withdrawal.reason), not only in a log line.
5. Verify the withdrawal took effect:
   verifyReleaseForInstall(outcome.withdrawnRelease, ...) must now return
   REJECT_WITHDRAWN_RELEASE even when observed bytes and source SHA still match.
   Step 5 matters: a withdrawal that does not change install-time behaviour has
   not actually protected anyone.
6. Publish the replacement under a NEW releaseId.
   - Never re-publish the withdrawn id. admitPublish refuses it, and that
     refusal is intentional.
7. Roll the installed fleet back if needed, using the M2/G2 authority:
   intent='rollback' against a rollbackEligible release.
   - Rollback changes app bytes only. It does not touch durable run truth and
     does not make any terminal local command replayable.
```

## 4. Rollback procedure (app bytes only)

```text
1. evaluateVersionTransition({
     installedVersion: <current>,
     targetVersion:   <previous>,
     intent:          'rollback',
     compatibility:   <declared by the target release>,
   })

2. If the decision is not INSTALL, STOP. Do not force the downgrade.
   Common refusals:
     - REJECT_UNSUPPORTED_DOWNGRADE  : target release is not rollbackEligible
     - REJECT_INCOMPATIBLE_SCHEMA    : installed version is outside the target's
                                       declared schema range
     - REJECT_UNSUPPORTED_DOWNGRADE  : intent was omitted

3. On INSTALL: replace app bytes only.

   Explicitly NOT permitted, at any point:
     - replaying a terminal local run
     - rewriting #3082 durable run state
     - resuming or retrying a broker command
     - altering conversation or task state
```

The rollback verdict carries `mayReplayLocalRun: false` and
`mayRewriteDurableRunState: false` as types, not comments, so a caller cannot
accidentally treat a rollback as licence to re-run work.

## 5. Verification checklist before any real publish

This slice claims no publish, so the checklist is unexecuted. It is the gate a
later slice must satisfy.

```text
[ ] sourceSha is a full 40-hex commit id
[ ] toolchain names electron-builder + both pinned toolsets
[ ] artifactSha256 computed from the exact produced bytes
[ ] releaseId is new (not present in the feed)
[ ] verifyReleaseForInstall passes with the real observed digest
[ ] signing evidence complete, when a signature is claimed
[ ] no long-lived signing secret anywhere in the path
[ ] withdrawal path rehearsed against a non-production feed
```

## 6. Failure modes this runbook cannot cover

```text
- A compromised signing identity: the contract can detect a mismatch and
  revocation, but key compromise before use is an Azure-side problem.
- A malicious rebuild with valid provenance: provenance proves origin, not
  correctness. Code review is the control there.
- Feed storage corruption: the contract validates shape on read, but the
  transport and storage of the feed itself are out of this slice.
```

These are stated rather than papered over. A runbook that implied full coverage
would be worse than one that names its edges.
