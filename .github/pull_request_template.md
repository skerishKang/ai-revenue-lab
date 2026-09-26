## Authority / revision

- Issue / work order:
- Exact starting base SHA:
- Branch:
- Exact current head SHA:
- Product-evidence stage:

## Purpose

State the smallest product/business question this change is intended to answer.

## Technology adoption / build decision

For substantial new commodity capability work:

- Landscape scan required? yes/no + reason:
- Parent adoption decision:
- Internal/OSS/commercial candidates reviewed:
- Selected approach:
- Adoption mode:
- Upstream version/commit:
- License/model-artifact/commercial posture:
- `SECOND_PRODUCT_AUTHORITY=0`:
- `BUILD_FROM_SCRATCH_JUSTIFIED=YES/NO/N/A`:

## Scope

- Allowed paths:
- Forbidden/out-of-scope paths:
- Exact changed files:
- Diff statistics:
- Explicit non-goals:

## Evidence dimensions

Mark `REQUIRED`, `NOT_REQUIRED`, or `PENDING` and link evidence.

- Technical implementation:
- UI / visual:
- UX / journey:
- Backend / runtime:
- Security / privacy:
- Market / reference:
- Commercial / business:
- Production:

## Implementation evidence

- Commands/checks run against this head:
- Exit/status and pass/fail/skip counts:
- CI/check runs:
- Implementation self-check limitations:

Do not present implementer-run local/browser checks as independent Local Validation.

## Independent validation

- Required? yes/no + reason:
- Validator actor:
- Exact tested head:
- Same actor as implementation? yes/no:
- Source modified during validation? yes/no:
- Result / artifacts:
- PR review/comment record for this validation:
- Immutable report/artifact pointer:
- If NOT_REQUIRED, explicit reason:

If the same actor implemented and executed the checks, label them implementation self-check/non-independent verification. A validation report that cannot be discovered from this PR is not a complete merge audit trail.

## Owner-only decisions

- Required? yes/no:
- Decision/status:
- `OWNER_UI_APPROVED` or equivalent must not be inferred when the contract reserves that decision to the owner.

## Risks and limitations

- Known defects:
- Deferred items:
- Environment limitations:
- Data/secret boundary:
- External security/compliance checks:
- Any red signal + exact disposition/waiver authority:
- Runtime trust-boundary review needed? yes/no + parser/builder/projector/serializer/export/write coverage:
- Load-bearing mutation/differential proof required? yes/no + evidence:

## CTO final status

```text
NOT_REVIEWED / NOT_READY / CONDITIONALLY_READY / READY
```

Only the Web CTO assigns the final technical/review status.

## Merge / deployment

- Merge authority:
- Expected head for merge:
- Deployment target/risk level when applicable:
- Last known-good Production source/configuration:
- Recovery fix/revert path:
- Preview/staging/manual deployment exception: none unless explicitly authorized.

For Git-connected projects, an authorized merge to the configured Production branch is the deployment action; do not create a second manual deployment path.

## Completion checklist

- [ ] Current remote main/head/diff were re-read before final review.
- [ ] Acceptance criteria are demonstrated for the exact reviewed revision.
- [ ] Required technology-landscape/adoption evidence exists, or the parent decision makes it N/A.
- [ ] No unrelated files are included.
- [ ] Failed/skipped/unexecuted checks are reported truthfully.
- [ ] No secrets, tokens, credentials, personal data, or private evidence were committed.
- [ ] Independent validation claims satisfy the actor-separation rule and the exact-head validator/result/report pointer is discoverable from this PR, or NOT_REQUIRED is explicitly justified.
- [ ] Any external red security/compliance signal is resolved or has an explicit authorized disposition/waiver; unrelated green CI is not used as a substitute.
- [ ] Contract defects were traced through downstream trust boundaries when applicable; explicit null/undefined/missing semantics are preserved.
- [ ] Load-bearing mutation/differential proof was recorded when required by the work contract/review.
- [ ] Owner-only decisions are not inferred.
- [ ] Production claims, when applicable, are tied to the actual deployed revision.
