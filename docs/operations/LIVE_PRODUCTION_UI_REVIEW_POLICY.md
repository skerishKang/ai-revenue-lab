# Live Production UI Review Policy

- Status: portfolio operating policy
- Owner: Web CTO
- Authority: Issue #451
- Applies from: 2026-08-09
- Related deployment policy: `DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md`

## 1. Decision

For AI Revenue Lab internal web Businesses that are already authorized for internal development, owner visual review uses the **actual Production surface** by default.

A separate Preview or staging review is not required before the owner sees a UI change.

The default UI loop is:

```text
implementation
→ CTO exact-head / scope / regression validation
→ merge to the configured Production branch
→ existing Git integration deploys Production automatically
→ owner reviews the actual Production screen
→ accept, fix, or restore
```

This policy changes the **owner visual-review sequence**. It does not weaken technical validation, security, privacy, or product-local authorization gates.

## 2. Standing merge authority for UI-only changes

For UI-only or frontend visual changes in an internal, non-excluded AI Revenue Lab web Business, successful CTO technical validation is sufficient authority to merge the reviewed change for live Production owner review.

The CTO must verify at minimum:

- exact current `main` / Production branch;
- exact proposed head and changed-file scope;
- no unintended backend, Auth, DB, secret, persistence, billing, migration, or destructive change;
- applicable static, browser, responsive, accessibility, and regression tests;
- no unresolved review thread or known critical runtime defect;
- last known-good source or a clear source-recovery point.

A separate owner confirmation such as "merge it" is not required for each qualifying UI-only revision while this standing policy remains in force.

## 3. Final owner UI approval remains separate

Technical validation and successful Production deployment do **not** mean the owner approved the design.

The owner-facing UI verdict may be set to `OWNER_APPROVED` only after the owner actually views the current Production UI and explicitly accepts it.

Before that decision, the correct state is one of:

```text
OWNER_REVIEW_REQUIRED
OWNER_REJECTED / REDESIGN_REQUIRED
```

Models, CI, validators, and the Web CTO may declare technical readiness, but they must not promote that evidence to final owner visual approval.

## 4. Rejection handling: fix or restore

If the owner reviews Production and does not like the UI:

1. record the owner verdict as rejected / redesign required;
2. if the direction is mostly correct, prepare the smallest focused UI correction;
3. if the direction is broadly unsatisfactory, unstable, or difficult to repair safely, restore the last known-good source with a reviewed revert/restoration change;
4. merge the reviewed correction or restoration to the configured Production branch;
5. let the existing Git integration deploy it automatically;
6. re-check the actual Production screen.

Do not create a separate manual Cloudflare deployment to recover source code. Source recovery follows the Git-connected recovery policy.

## 5. Preview and staging

Preview/staging is not part of the normal owner UI-review loop.

Do not create Preview or staging merely so the owner can decide whether a design looks good.

Preview or staging may be used only when a new explicit owner decision or an already approved Business-specific contract requires it for a concrete risk, such as:

- destructive migration rehearsal;
- payment or billing verification;
- high-risk authentication/authorization work;
- regulated/compliance-sensitive review;
- external stakeholder access that must not touch Production.

A model, worker, or CTO cannot invent this exception on its own.

## 6. Scope exclusions

This standing UI merge authority does not apply to:

- Businesses classified as external, successor, integrated, or excluded from this repository's internal development authority;
- backend or database changes;
- authentication or authorization changes;
- secrets, credentials, bindings, or infrastructure mutations;
- persistence changes;
- billing or payment behavior;
- destructive migration or irreversible external action;
- security-sensitive changes that materially alter trust boundaries.

Those changes keep their own authorization and risk gates.

## 7. Portfolio Console behavior

For an internal web Business under owner review, Portfolio Console should link to the **current canonical Production URL**, not a stale branch Preview URL.

The Console should distinguish:

- `UI · 사용자 승인` — explicit owner acceptance of the current accepted visual baseline;
- `UI · 검토 필요` — live Production screen exists but owner has not accepted it;
- `UI · 재설계` — owner rejected the current direction and a correction/rebuild is required;
- external/successor/non-web cases — owner UI gate is not applicable in this portfolio.

Historical technical `UI_APPROVED` evidence remains useful engineering history but must not be displayed as owner approval unless explicit owner evidence exists.

## 8. First application — Business 1

Business 1 · Personal Edition PR #448 is the first change governed by this policy.

The intended sequence is:

```text
PR #448 exact-head validation against current main
→ merge without a separate Preview approval
→ automatic Personal Edition Production deployment
→ Portfolio Console B1 opens canonical Production
→ owner visually reviews B1
→ approve, request focused changes, or restore previous source
```

Until the owner views and accepts the new Production UI, B1 remains `UI · 재설계` or `UI · 검토 필요`; the merge itself does not set `OWNER_APPROVED`.

## 9. Evidence record

For each live owner UI review, record:

- Business number and name;
- source PR and reviewed exact head;
- resulting Production-branch SHA;
- automatic deployment status when available;
- canonical Production URL;
- last known-good source/recovery point;
- owner verdict;
- follow-up: retain, focused fix, or restore.

Canonical markers:

```text
OWNER_LIVE_PRODUCTION_UI_REVIEW
PREVIEW_NOT_REQUIRED_FOR_OWNER_VISUAL_REVIEW
TECHNICAL_VALIDATION_BEFORE_MERGE
FINAL_OWNER_APPROVAL_AFTER_LIVE_VIEW
FIX_OR_RESTORE_ON_REJECTION
```
